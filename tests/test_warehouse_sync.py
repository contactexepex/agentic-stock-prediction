"""The warehouse sync (scripts/warehouse_sync.py, marketbrief/warehouse/) on the local fallback DuckDB file:
idempotent (two runs, same rows), every run in meta.sync_runs and rm.builds, read models keyed (market,
page_key), upserted by hash and cut from the dashboard's data, nothing stored after the run's clock (MB_NOW)
copied, --full rebuilds, a failure is recorded with the token redacted, and a dry run writes nothing.

The data is a copy of the repo's stored US data (append-only, so rows stored by the fixed cut-off never
change), plus rows of several kinds stored after the cut-off."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core import database  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.constants.rm_company import LIFECYCLE_SESSIONS  # noqa: E402
from marketbrief.lab import registry  # noqa: E402
from marketbrief.pipeline import market_status  # noqa: E402
from marketbrief.presentation.dashboard.assemble import gather_dashboard  # noqa: E402
from marketbrief.warehouse import cli as wh_cli  # noqa: E402
from marketbrief.warehouse import openapi_spec, read_models, rm_company, rm_registry, sync  # noqa: E402
from marketbrief.warehouse.connection import WarehouseError  # noqa: E402
from marketbrief.warehouse.read_models import READ_MODEL_COLUMNS  # noqa: E402
from marketbrief.warehouse.tables import TABLES  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CUTOFF = "2026-10-07T05:00:00+00:00"
LATER = "2026-10-07T20:00:00+00:00"
LATE_NEWS = "feedfacefeedface"
SECRET = "sync-secret/+="
WAREHOUSE = Path("work/warehouse/market_brief.duckdb")
MIRRORED = {"tickers", "bars", *(t.name for t in TABLES)}
RM_TABLES = rm_registry.tables()  # every registered builder's table
TICKER_TABLES = ("stock", "bars", "stock_strategies")  # one page per ticker (B12)
MARKET_AND_TICKER_TABLES = ("compare", "trades")  # the market's page `_` and one page per ticker (B13, B12)
MARKET_AND_STRATEGY_TABLES = ("strategies",)  # the market's page `_` and one page per registry strategy (B13)
STRATEGY_IDS = [spec["id"] for spec in registry.strategies()]
TICKER_DAY_TABLES = ("lifecycle",)  # one page per ticker and session, `<ticker>:<date>` (B12)
SESSION_DAYS = rm_company.sessions_back(
    load_market("us"), market_status.status(load_market("us"), datetime.fromisoformat(CUTOFF))["session_date"],
    LIFECYCLE_SESSIONS)


def expected_keys(tickers: list[str]) -> dict[str, list[str]]:
    """table -> the page keys a sync of the market writes (every other table: the market's one page `_`)."""
    out = {}
    for table in RM_TABLES:
        if table in TICKER_TABLES:
            out[table] = list(tickers)
        elif table in MARKET_AND_TICKER_TABLES:
            out[table] = ["_", *tickers]
        elif table in MARKET_AND_STRATEGY_TABLES:
            out[table] = ["_", *STRATEGY_IDS]
        elif table in TICKER_DAY_TABLES:
            out[table] = [f"{ticker}:{day}" for ticker in tickers for day in SESSION_DAYS]
        else:
            out[table] = ["_"]
    return out


US_TICKERS = [f"T{i}" for i in range(20)]  # only the count matters for the totals (20 US companies)
PAGES = {table: len(keys) for table, keys in expected_keys(US_TICKERS).items()}
TOTAL_PAGES = sum(PAGES.values())
SPEC = REPO / "api" / "openapi.yaml"


def append(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / "us" / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def later_rows(root: Path) -> None:
    """Rows stored after the cut-off: none of them may reach the warehouse."""
    feature = {
        "id": "2026-10-07-JPM",
        "as_of_date": "2026-10-07",
        "ticker": "JPM",
        "computed_at": LATER,
        "close": 999.0,
    }
    append(root, "features", "2026-10-07", [feature])
    news = {
        "id": LATE_NEWS,
        "title": "Later JPM news",
        "url": "https://example.com/x",
        "source": "Test",
        "published_at": "2026-10-07T04:00:00+00:00",
        "first_seen_at": LATER,
        "tickers": ["JPM"],
    }
    append(root, "news", "2026-10-07", [news])
    append(root, "reviews", "2026-10-07", [{"id": "2026-W41", "computed_at": LATER, "model_skill": True, "detail": {}}])
    prices = root / "data" / "us" / "prices" / "2026" / "10" / "2026-10-07.csv"
    prices.write_bytes(
        b"date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n"
        + f"2026-10-07,JPM,500.0,510.0,490.0,505.0,505.0,1000,{LATER}\r\n".encode()
    )


@pytest.fixture(scope="module")
def synced(tmp_path_factory):
    """Two replace runs, a dry run and a third run after an extra table appears, on one copied root."""
    root = tmp_path_factory.mktemp("warehouse")
    shutil.copytree(REPO / "data" / "us", root / "data" / "us")
    later_rows(root)
    saved_root, mp = common.ROOT, pytest.MonkeyPatch()
    common.ROOT = root
    mp.setenv("MB_NOW", CUTOFF)
    mp.delenv("MOTHERDUCK_TOKEN", raising=False)
    try:
        cfg = load_market("us")
        dry = sync.sync_market(cfg, dry_run_only=True, force_local=True)
        dry_left_files = (
            sorted(p.relative_to(root).as_posix() for p in (root / "work").rglob("*"))
            if (root / "work").exists()
            else []
        )
        first = sync.sync_market(cfg, force_local=True)
        snap1 = snapshot(root / WAREHOUSE)
        second = sync.sync_market(cfg, force_local=True)
        snap2 = snapshot(root / WAREHOUSE)
        snap_bare = snapshot(root / WAREHOUSE, envelope=False)
        con = database.connect("us")
        dashboard = gather_dashboard(cfg, con, datetime.fromisoformat(CUTOFF))
        yield {
            "root": root,
            "cfg": cfg,
            "dry": dry,
            "dry_left_files": dry_left_files,
            "first": first,
            "second": second,
            "snap1": snap1,
            "snap2": snap2,
            "snap_bare": snap_bare,
            "dashboard": dashboard,
            "mp": mp,
        }
    finally:
        common.ROOT = saved_root
        mp.undo()


def snapshot(path: Path, envelope: bool = True) -> dict:
    """Every mirrored table's rows (sorted) and every read-model row; without built_at and cutoff when
    `envelope` is false (a --full rebuild writes every page anew)."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        out = {}
        for name in sorted(MIRRORED):
            out[name] = sorted(map(repr, con.execute(f"SELECT * FROM us.{name}").fetchall()))
        drop = "" if envelope else " EXCLUDE (built_at, cutoff)"
        for table in RM_TABLES:
            rows = con.execute(f"SELECT *{drop} FROM rm.{table} ORDER BY market, page_key").fetchall()
            out[f"rm.{table}"] = [tuple(str(v) for v in r) for r in rows]
        return out
    finally:
        con.close()


def query(root: Path, sql: str, params=None):
    con = duckdb.connect(str(root / WAREHOUSE), read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


def test_sync_is_idempotent(synced):
    assert synced["first"]["ok"] and synced["second"]["ok"]
    assert synced["first"]["tables"] == synced["second"]["tables"]
    assert set(synced["first"]["tables"]) == MIRRORED
    assert synced["snap1"] == synced["snap2"]  # built_at and cutoff of the unchanged pages included
    assert synced["first"]["pages_written"] == TOTAL_PAGES and synced["first"]["pages_unchanged"] == 0
    assert synced["second"]["pages_written"] == 0 and synced["second"]["pages_unchanged"] == TOTAL_PAGES
    assert synced["first"]["tables"]["bars"] > 1000 and synced["first"]["tables"]["tickers"] == 20


def test_dry_run_writes_nothing_and_counts_the_same_rows(synced):
    dry = synced["dry"]
    assert dry["mode"] == "dry_run" and dry["written"] is False
    assert synced["dry_left_files"] == []  # no warehouse file, no stage folder, no summary
    assert dry["tables"] == synced["first"]["tables"]
    assert dry["read_model_pages"] == PAGES
    assert dry["invalid_pages"] == [] and dry["as_of"] == synced["dashboard"]["as_of"]


def test_sync_runs_are_recorded(synced):
    rows = query(
        synced["root"],
        "SELECT run_id, market, mode, ok, error, rows, read_models, cutoff, target, tables, table_rows, "
        "started_at <= finished_at, connected_s, epoch(finished_at) - epoch(started_at) "
        "FROM meta.sync_runs ORDER BY started_at",
    )
    for r in rows[:2]:  # the connected time is part of the run's wall time
        assert 0 < r[12] <= r[13]
    assert [r[0] for r in rows[:2]] == [synced["first"]["run_id"], synced["second"]["run_id"]]
    for r in rows[:2]:
        assert r[1:5] == ("us", "replace", True, None)
        assert r[5] == sum(synced["first"]["tables"].values()) and r[6] == TOTAL_PAGES
        assert r[7] == datetime.fromisoformat(CUTOFF) and r[8] == WAREHOUSE.as_posix()
        assert set(r[9]) == MIRRORED and json.loads(r[10]) == synced["first"]["tables"] and r[11]
    summary = json.loads((synced["root"] / "work" / "warehouse" / "us-sync.json").read_text())
    assert summary["run_id"] == synced["second"]["run_id"] and summary["ok"] is True
    assert summary["connected_s"] == rows[1][12]
    assert not list((synced["root"] / "work" / "warehouse").glob("stage-*"))  # staging removed
    builds = query(
        synced["root"],
        "SELECT build_id, market, kind, ok, pages_written, pages_unchanged, error, source_commit, cutoff "
        "FROM rm.builds ORDER BY started_at",
    )
    assert [b[0] for b in builds[:2]] == [r[0] for r in rows[:2]]
    assert [b[1:7] for b in builds[:2]] == [
        ("us", "daily", True, TOTAL_PAGES, 0, None),
        ("us", "daily", True, 0, TOTAL_PAGES, None),
    ]
    assert builds[0][7] == "unknown"  # the copied root is no git checkout
    assert builds[0][8] == datetime.fromisoformat(CUTOFF)


def stored_pages(root: Path, table: str) -> dict:
    rows = query(root, f"SELECT page_key, market, as_of, schema_version, payload_sha256, payload FROM rm.{table}")
    return {r[0]: r[1:] for r in rows}


def test_read_models_keys_envelope_and_payloads(synced):
    data, root = synced["dashboard"], synced["root"]
    as_of = datetime.fromisoformat(data["as_of"]).date()
    tickers = list(synced["cfg"]["tickers"])
    keys = expected_keys(tickers)
    for table, expected in keys.items():
        pages = stored_pages(root, table)
        assert sorted(pages) == sorted(expected)
        for market, page_as_of, version, sha, payload in pages.values():
            assert (market, page_as_of, version) == ("us", as_of, openapi_spec.version())
            assert hashlib.sha256(payload.encode()).hexdigest() == sha  # the ETag hashes the stored text
            assert "generated_at" not in payload  # no cut-off inside a payload (the envelope has it)
    company = next(c for c in data["companies"] if c["ticker"] == "JPM")
    # 2.0: the company page (B12, rm_company.py) carries its bars; rm.bars holds the same list
    jpm = json.loads(stored_pages(root, "stock")["JPM"][4])
    assert jpm["ticker"] == "JPM" and jpm["company"]["ticker"] == "JPM" and jpm["as_of"] == data["as_of"]
    bars = json.loads(stored_pages(root, "bars")["JPM"][4])
    assert bars["bars"] == jpm["bars"] and bars["bars"][-1]["date"] == company["last"]["date"]
    assert all(e["date"] >= jpm["status"]["session"]["session_date"] for e in jpm["events"])
    overview = json.loads(stored_pages(root, "overview")["_"][4])
    assert overview["overview"] == json.loads(json.dumps(data["overview"]))
    assert overview["disclaimer"] == data["disclaimer"] and overview["plan"] == data["plan"]
    watch = json.loads(stored_pages(root, "watchlist")["_"][4])  # B11's 2.0 page (warehouse/rm_watchlist.py)
    assert sorted(c["ticker"] for c in watch["companies"]) == sorted(tickers)
    assert watch["status"]["market"] == "us" and set(watch["agreement"]) == {"1", "2", "3", "4", "5"}
    track = json.loads(stored_pages(root, "track_record")["_"][4])
    assert {k: track["track"][k] for k in data["track"]} == json.loads(json.dumps(data["track"]))  # B13's page


def test_version_and_envelope_match_the_spec():
    spec = openapi_spec.spec()
    assert spec["info"]["version"] == "2.0.0"
    meta = spec["components"]["schemas"]["ReadModelMeta"]["required"]
    assert set(meta) | {"payload"} == set(READ_MODEL_COLUMNS)


def test_nothing_after_the_clock_is_copied(synced):
    root = synced["root"]
    assert query(root, "SELECT count(*) FROM us.features WHERE computed_at > ?::TIMESTAMPTZ", [CUTOFF]) == [(0,)]
    assert query(root, "SELECT count(*) FROM us.news WHERE id = ?", [LATE_NEWS]) == [(0,)]
    assert query(root, "SELECT count(*) FROM us.reviews WHERE computed_at > ?::TIMESTAMPTZ", [CUTOFF]) == [(0,)]
    assert query(root, "SELECT count(*) FROM us.bars WHERE ticker = 'JPM' AND date = DATE '2026-10-07'") == [(0,)]
    assert query(root, "SELECT max(date) FROM us.bars")[0][0] < datetime(2026, 10, 7).date()
    # every newest row the dashboard shows is there: the warehouse's newest JPM bar is the page's last session
    jpm = next(c for c in synced["dashboard"]["companies"] if c["ticker"] == "JPM")
    last = query(root, "SELECT max(date) FROM us.bars WHERE ticker = 'JPM'")[0][0]
    assert last.isoformat() == jpm["last"]["date"]


def test_track_summary_keeps_the_label_bases_apart(synced):
    rows = query(synced["root"], "SELECT label_basis, horizon_days, calls FROM us.track_summary")
    assert len({(b, h) for b, h, _ in rows}) == len(rows)  # one row per basis and horizon, never pooled


def test_replace_deletes_departed_pages_and_full_rebuilds(synced):
    root, cfg = synced["root"], synced["cfg"]
    con = duckdb.connect(str(root / WAREHOUSE))
    con.execute("CREATE TABLE us.stale_table (a INTEGER)")
    con.execute("INSERT INTO rm.stock SELECT * REPLACE ('OLD' AS page_key) FROM rm.stock WHERE page_key = 'JPM'")
    con.close()
    res = sync.sync_market(cfg, force_local=True)
    assert res["pages_deleted"] == 1 and res["pages_written"] == 0  # a ticker that left the watchlist
    assert query(root, "SELECT count(*) FROM rm.stock WHERE page_key = 'OLD'") == [(0,)]
    assert query(root, "SELECT count(*) FROM information_schema.tables WHERE table_name = 'stale_table'") == [(1,)]
    full = sync.sync_market(cfg, full=True, force_local=True)
    assert full["mode"] == "full" and full["kind"] == "full" and full["ok"] and full["pages_written"] == TOTAL_PAGES
    assert query(root, "SELECT count(*) FROM information_schema.tables WHERE table_name = 'stale_table'") == [(0,)]
    # same payloads and hashes as the incremental build; only built_at and cutoff are new
    assert snapshot(root / WAREHOUSE, envelope=False) == synced["snap_bare"]


def test_invalid_page_keeps_its_old_row(synced, monkeypatch):
    root, cfg = synced["root"], synced["cfg"]
    con = duckdb.connect(str(root / WAREHOUSE))
    con.execute("UPDATE rm.track_record SET payload_sha256 = 'old', payload = '{\"old\": 1}'")  # a stale row
    con.close()
    real = read_models.page_problems
    monkeypatch.setattr(
        read_models,
        "page_problems",
        lambda builder, payload, document: (
            ["$: missing 'not_built_yet'"] if builder.table == "track_record" else real(builder, payload, document)
        ),
    )
    res = sync.sync_market(cfg, force_local=True)
    assert res["ok"] and not res["build_ok"]
    assert res["invalid_pages"] == ["track_record/_: $: missing 'not_built_yet'"]
    assert stored_pages(root, "track_record")["_"][3:] == ("old", '{"old": 1}')  # neither replaced nor deleted
    last = query(root, "SELECT ok, error FROM rm.builds ORDER BY started_at DESC LIMIT 1")[0]
    assert last == (False, "track_record/_: $: missing 'not_built_yet'")


def test_kill_switch_skips_without_writing(synced, monkeypatch, tmp_path):
    root, cfg = synced["root"], synced["cfg"]
    runs = query(root, "SELECT count(*) FROM meta.sync_runs")[0][0]
    config = tmp_path / "config"
    shutil.copytree(REPO / "config", config)
    text = (config / "warehouse.yaml").read_text()
    monkeypatch.setattr(common, "CONFIG", config)
    (config / "warehouse.yaml").write_text(text.replace("enabled: true", "enabled: false"))
    res = sync.sync_market(cfg, force_local=True)
    assert res["ok"] and "enabled: false" in res["skipped"]
    assert query(root, "SELECT count(*) FROM meta.sync_runs")[0][0] == runs  # not even connected
    (config / "warehouse.yaml").write_text(text.replace("monthly_hours_ceiling: 7", "monthly_hours_ceiling: 0"))
    before = snapshot(root / WAREHOUSE)
    res = sync.sync_market(cfg, force_local=True)
    assert res["ok"] and "monthly_hours_ceiling 0" in res["skipped"] and "write_s" not in res
    assert snapshot(root / WAREHOUSE) == before
    last = query(root, "SELECT ok, error FROM rm.builds ORDER BY started_at DESC LIMIT 1")[0]
    assert last[0] is False and last[1].startswith("skipped:")
    monkeypatch.setattr(sys, "argv", ["warehouse_sync.py", "--market", "us", "--local"])
    assert wh_cli.main() == 0  # a skip is not a failure of the step


def test_failure_is_recorded_redacted_and_rolled_back(synced, monkeypatch):
    """A --full run failing at COMMIT: its DROP SCHEMA is rolled back (a table it would drop survives), the
    run is recorded with ok false, and the token in the error is redacted everywhere."""
    root, cfg = synced["root"], synced["cfg"]
    con = duckdb.connect(str(root / WAREHOUSE))
    con.execute("CREATE TABLE us.keep_me (a INTEGER)")
    con.close()
    before = snapshot(root / WAREHOUSE)
    monkeypatch.setenv("MOTHERDUCK_TOKEN", SECRET)
    real = sync.write_market

    class FailingAtCommit:
        def __init__(self, wh):
            self.wh = wh

        def execute(self, sql, *args):
            if sql.startswith("COMMIT"):
                raise RuntimeError(f"upload refused for token {SECRET}")
            return self.wh.execute(sql, *args)

    monkeypatch.setattr(sync, "write_market", lambda wh, *a, **k: real(FailingAtCommit(wh), *a, **k))
    with pytest.raises(WarehouseError) as err:
        sync.sync_market(cfg, full=True, force_local=True)
    assert SECRET not in str(err.value) and "***" in str(err.value)
    last = query(root, "SELECT ok, error, mode FROM meta.sync_runs ORDER BY started_at DESC LIMIT 1")[0]
    assert last[0] is False and last[2] == "full" and SECRET not in last[1] and "***" in last[1]
    summary = (root / "work" / "warehouse" / "us-sync.json").read_text()
    assert SECRET not in summary and json.loads(summary)["ok"] is False
    assert query(root, "SELECT count(*) FROM information_schema.tables WHERE table_name = 'keep_me'") == [(1,)]
    assert snapshot(root / WAREHOUSE) == before


def test_cli_dry_run_and_missing_token(synced, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["warehouse_sync.py", "--market", "us", "--dry-run", "--local"])
    assert wh_cli.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tables"] == synced["first"]["tables"] and out["written"] is False and out["kind"] == "daily"
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["warehouse_sync.py", "--market", "us"])
    assert wh_cli.main() == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "MOTHERDUCK_TOKEN" in out["error"]


def test_a_failed_rollback_does_not_hide_the_original_error(tmp_path):
    """write_market re-raises the error that broke the transaction even when ROLLBACK fails too."""

    class BrokenWarehouse:
        def execute(self, sql, *_args):
            if sql.startswith("CREATE OR REPLACE TABLE"):
                raise RuntimeError("the original failure")
            if sql == "ROLLBACK":
                raise duckdb.TransactionException("no transaction is active")
            return self

    staged = sync.Staged(tmp_path, {"bars": 1}, {}, [])
    with pytest.raises(RuntimeError, match="the original failure"):
        sync.write_market(BrokenWarehouse(), "us", staged, full=False)


def test_safe_url_sql_mirrors_view_data_safe_url():
    """Issue #48: the warehouse's SQL copy percent-encodes " ' < > and backtick exactly as view_data.safe_url does."""
    from marketbrief.warehouse.tables import SAFE_URL_SQL
    from view_data import safe_url

    query = f"SELECT {SAFE_URL_SQL.format(col='u')} FROM (SELECT ?::VARCHAR AS u)"
    urls = ["https://a.example/x\"y'z<b>`c", " https://ok.example/p?q=1 ", "javascript:alert(1)", "https://a b", None]
    for url in urls:
        assert duckdb.execute(query, [url]).fetchone()[0] == safe_url(url), url
    assert duckdb.execute(query, ["https://a.example/\"'<>`"]).fetchone()[0] == "https://a.example/%22%27%3C%3E%60"
