"""The API contract harness (docs/ws/b4.md "Contract tests"; marketbrief/warehouse/contract.py, schema_check.py,
rm_registry.py, revalidate.py): the serve rules equal the route's (the fixture shared with web/lib/data), the schema
checker and the shape comparison find what they should, the sync revalidates the app's cache only when it may, and
every registered contract case passes on read models built by the sync from the repo's stored data of both markets
(served as the route serves them, validated against the operation's 200 schema, compared with the mockup)."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.warehouse import (  # noqa: E402
    contract,
    openapi_spec,
    revalidate,
    rm_common,
    rm_registry,
    schema_check,
    sync,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "web" / "lib" / "data" / "tests" / "serve.fixture.json"
CUTOFF = "2026-10-07T12:00:00+00:00"
WAREHOUSE = Path("work/warehouse/market_brief.duckdb")
MARKETS = ("india", "us")


# ---------- serve: the same bodies as web/lib/data/serve.ts ----------
@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text())["cases"], ids=lambda c: c["name"])
def test_serve_matches_the_shared_fixture(case):
    now = datetime.fromisoformat(json.loads(FIXTURE.read_text())["now"].replace("Z", "+00:00"))
    assert contract.serve(case["row"], case["mode"], now) == case["expected"]


# ---------- schema checker ----------
DOCUMENT = {
    "components": {
        "schemas": {
            "Market": {"type": "string", "enum": ["india", "us"]},
            "Row": {
                "type": "object",
                "required": ["market", "n"],
                "properties": {
                    "market": {"$ref": "#/components/schemas/Market"},
                    "n": {"type": "integer", "minimum": 0},
                    "x": {"type": ["number", "null"]},
                    "pair": {"type": "array", "prefixItems": [{"type": "string"}, {"type": "number"}]},
                    "tags": {"type": "array", "items": {"type": "string", "pattern": "^[a-z]+$"}, "maxItems": 2},
                    "either": {"oneOf": [{"type": "string"}, {"type": "null"}]},
                    "map": {"type": "object", "additionalProperties": {"type": "boolean"}},
                },
            },
            "Closed": {"type": "object", "additionalProperties": False, "properties": {"a": {"const": 1}}},
            "Both": {"allOf": [{"$ref": "#/components/schemas/Row"}, {"required": ["x"]}]},
        }
    }
}


def check(value, name: str) -> list[str]:
    return schema_check.errors(value, {"$ref": f"#/components/schemas/{name}"}, DOCUMENT)


def test_schema_checker_accepts_a_valid_value():
    value = {"market": "us", "n": 3, "x": None, "pair": ["a", 1.5], "tags": ["ab"], "either": None, "map": {"k": True}}
    assert check(value, "Row") == []
    assert check({**value, "n": 3.0}, "Row") == []  # an integral float is an integer
    assert check({"a": 1}, "Closed") == []


@pytest.mark.parametrize(
    ("value", "name", "problem"),
    [
        ({"n": 1}, "Row", "$: missing 'market'"),
        ({"market": "eu", "n": 1}, "Row", "$.market: 'eu' not in ['india', 'us']"),
        ({"market": "us", "n": -1}, "Row", "$.n: -1 < minimum 0"),
        ({"market": "us", "n": True}, "Row", "$.n: expected integer, got bool"),
        ({"market": "us", "n": 1, "pair": ["a", "b"]}, "Row", "$.pair[1]: expected number, got str"),
        ({"market": "us", "n": 1, "tags": ["A"]}, "Row", "$.tags[0]: 'A' does not match ^[a-z]+$"),
        ({"market": "us", "n": 1, "tags": ["a", "b", "c"]}, "Row", "$.tags: more than 2 items"),
        ({"market": "us", "n": 1, "either": 3}, "Row", "$.either: matches 0 of oneOf, not exactly 1"),
        ({"market": "us", "n": 1, "map": {"k": 1}}, "Row", "$.map.k: expected boolean, got int"),
        ({"a": 1, "b": 2}, "Closed", "$: unexpected 'b'"),
        ({"a": 2}, "Closed", "$.a: 2 is not 1"),
        ({"market": "us", "n": 1}, "Both", "$: missing 'x'"),
        ([], "Row", "$: expected object, got list"),
    ],
)
def test_schema_checker_names_each_problem(value, name, problem):
    assert problem in check(value, name)


# ---------- shape against the mockup ----------
MOCKUP = {
    "market": "us",
    "status": {"regime": "TRENDING", "benchmark": {"symbol": "SPY", "close": 1.5}},
    "items": [{"id": "a", "n": 1, "note": "x"}, {"id": "b", "n": 2}],
    "strategies": {"s1": {"id": "s1", "live": False}, "s2": {"id": "s2", "live": True}},
    "empty": [],
}


def test_shape_matches_with_nulls_numbers_optional_keys_and_maps():
    payload = {
        "market": "india",
        "status": {"regime": None, "benchmark": None},
        "items": [{"id": "c", "n": 2.5}, {"id": "d", "n": 3, "note": None}],
        "strategies": {"other": {"id": "other", "live": True}},
        "empty": [{"anything": 1}],
    }
    assert contract.shape_problems(payload, MOCKUP, map_paths=("$.strategies",)) == []


def test_shape_names_missing_extra_and_mistyped_keys():
    payload = {
        "market": 1,
        "status": {"regime": "X", "benchmark": {"symbol": "SPY"}},
        "items": [{"n": 1}],
        "strategies": {"s1": {"id": "s1", "live": "no"}},
        "empty": [],
        "extra": True,
    }
    found = contract.shape_problems(payload, MOCKUP, map_paths=("$.strategies",))
    assert "$.market: expected string, got number" in found
    assert "$.status.benchmark: missing 'close'" in found
    assert "$.items[0]: missing 'id'" in found
    assert "$.strategies{s1}.live: expected boolean, got string" in found
    assert "$: 'extra' is not in the mockup" in found
    assert (
        contract.shape_problems({**payload, "market": "us"}, MOCKUP, ("$.strategies",), ("extra",)).count(
            "$: 'extra' is not in the mockup"
        )
        == 0
    )
    # without the map path, a map's own keys are compared and differ
    assert "$.strategies: missing 's2'" in contract.shape_problems(payload, MOCKUP)


# ---------- registry ----------
def test_registry_finds_the_builders_and_refuses_a_table_built_twice(monkeypatch):
    tables = rm_registry.tables()
    assert {"status", "overview", "watchlist", "stock", "bars", "track_record"} <= set(tables)
    assert len(tables) == len(set(tables))
    twice = rm_registry.PageBuilder("status", "MarketStatus", lambda _ctx: {}, owner="test")
    real = rm_registry.importlib.import_module

    def fake_import(name):
        module = real(name)
        if name.endswith(".rm_dashboard"):
            return type("M", (), {"BUILDERS": (*module.BUILDERS, twice)})
        return module

    monkeypatch.setattr(rm_registry.importlib, "import_module", fake_import)
    with pytest.raises(ValueError, match="'status' is built by two modules"):
        rm_registry.discover()


def test_a_builder_refuses_an_unknown_serve_mode():
    with pytest.raises(ValueError):
        rm_registry.PageBuilder("x", "X", lambda _ctx: {}, owner="test", serve="raw")


# ---------- shared blocks against the catalogue's examples (built with B2's engine) ----------
def catalogue(name: str) -> list[dict]:
    return json.loads((REPO / "design" / "catalogue" / name).read_text())["records"]


def example_context(market: str) -> rm_registry.BuildContext:
    """A context whose settled trades are the catalogue's example trades of the market, each with its your-cost
    view (as design/catalogue/catalogue_entities.scoreboard joins them)."""
    your = {r["record_id"]: r for r in catalogue("cost_view.json") if r["record_kind"] == "settlement"}
    trades = [
        {**t, **{k: your[t["id"]][k] for k in ("net_pnl_your", "return_pct_your")}} if t["id"] in your else t
        for t in catalogue("paper_trade.json")
        if t["market"] == market
    ]
    ctx = rm_registry.BuildContext(load_market(market), None, datetime.fromisoformat(CUTOFF))
    ctx.memo.update(settled_trades=trades, status_block={"session": {"session_date": "2026-10-07"}})
    return ctx


@pytest.mark.parametrize("market", MARKETS)
def test_go_live_is_the_reference_strategys_accuracy_row(market):
    expected = next(
        r["go_live"]
        for r in catalogue("scoreboard_row.json")
        if r["market"] == market
        and r["scope"] == "strategy"
        and r["strategy_id"] == "rule.model_news.v1"
        and r["view"] == "accuracy"
        and str(r["horizon_days"]) == "all"
    )
    assert rm_common.go_live(example_context(market)) == {k: expected[k] for k in rm_common.GO_LIVE_FIELDS}


def test_go_live_without_a_settled_trade():
    ctx = rm_registry.BuildContext(load_market("us"), None, datetime.fromisoformat(CUTOFF))
    ctx.memo.update(settled_trades=[])
    assert rm_common.go_live(ctx) == {
        "proven": False,
        "months_forward": 0.0,
        "trades_needed": 300,
        "beats_best_baseline": None,
    }


def test_strategies_count_settled_accuracy_trades_per_market():
    per_market = {market: rm_common.strategies(example_context(market)) for market in MARKETS}
    for spec in catalogue("strategy.json"):
        assert sum(per_market[m][spec["id"]]["settled_trades"] for m in MARKETS) == spec["settled_trades"], spec["id"]
        entry = per_market["us"][spec["id"]]
        assert {k: entry[k] for k in ("id", "family", "name", "threshold", "horizons", "live")} == {
            k: spec[k] for k in ("id", "family", "name", "threshold", "horizons", "live")
        }
    picked = rm_common.strategies(example_context("us"), ("id", "live"))
    assert set(next(iter(picked.values()))) == {"id", "live"}


# ---------- revalidate after a sync ----------
class FakeOpener:
    """Records each request; answers with `status` (an HTTPError for anything but 200)."""

    def __init__(self, status: int = 200):
        self.status, self.requests = status, []

    def open(self, request, timeout):  # noqa: ARG002 - the opener interface
        import urllib.error

        self.requests.append(request)
        if self.status != 200:
            raise urllib.error.HTTPError(request.full_url, self.status, "refused", {}, None)
        response = type("R", (), {"status": 200, "__enter__": lambda own: own, "__exit__": lambda *_: None})()
        return response


def test_revalidate_posts_batches_with_the_secrets_in_headers_only(monkeypatch):
    monkeypatch.setenv("REVALIDATE_SECRET", "sec-ret")
    monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", "by-pass")
    keys = [{"table": "stock", "market": "us", "page_key": f"T{i}"} for i in range(250)]
    opener = FakeOpener()
    assert revalidate.revalidate("https://app.test/", "run-1", keys, opener) == "ok: 250 keys"
    assert [r.full_url for r in opener.requests] == ["https://app.test/api/v1/internal/revalidate"] * 2
    first = opener.requests[0]
    assert first.get_method() == "POST"
    assert first.get_header("X-revalidate-secret") == "sec-ret"
    assert first.get_header("X-vercel-protection-bypass") == "by-pass"
    assert [len(json.loads(r.data)["keys"]) for r in opener.requests] == [200, 50]
    assert "sec-ret" not in first.full_url and "by-pass" not in first.full_url


def test_revalidate_skips_or_reports_without_raising(monkeypatch):
    monkeypatch.delenv("REVALIDATE_SECRET", raising=False)
    key = [{"table": "status", "market": "us", "page_key": "_"}]
    assert revalidate.revalidate("https://app.test", "r", key) == "skipped: REVALIDATE_SECRET is not set"
    assert revalidate.revalidate("https://app.test", "r", []) == "skipped: no page changed"
    monkeypatch.setenv("REVALIDATE_SECRET", "sec-ret")
    result = revalidate.revalidate("https://app.test", "r", key, FakeOpener(401))
    assert result.startswith("failed: HTTP 401") and "sec-ret" not in result


# ---------- end to end: the sync's read models against every contract case ----------
@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    """Both markets synced to the local warehouse file as of CUTOFF from a copy of the repo's stored data."""
    root = tmp_path_factory.mktemp("contract")
    for market in MARKETS:
        shutil.copytree(REPO / "data" / market, root / "data" / market)
    saved_root, mp = common.ROOT, pytest.MonkeyPatch()
    common.ROOT = root
    mp.setenv("MB_NOW", CUTOFF)
    mp.delenv("MOTHERDUCK_TOKEN", raising=False)
    try:
        summaries = {market: sync.sync_market(load_market(market), force_local=True) for market in MARKETS}
        yield {"root": root, "summaries": summaries}
    finally:
        common.ROOT = saved_root
        mp.undo()


def test_every_contract_case_passes_on_synced_read_models(warehouse):
    for market, summary in warehouse["summaries"].items():
        assert summary["ok"] and summary["build_ok"], summary
        assert summary["invalid_pages"] == []
        assert summary["revalidate"] == "skipped: the local warehouse file has no app cache"
    con = duckdb.connect(str(warehouse["root"] / WAREHOUSE), read_only=True)
    try:
        now = datetime.fromisoformat(CUTOFF)
        for market in MARKETS:
            result = contract.check_market(con, market, now)
            assert result["checked"], market
            assert result["problems"] == [], result["problems"][:10]
    finally:
        con.close()


def test_status_page_values_come_from_the_stored_data(warehouse):
    con = duckdb.connect(str(warehouse["root"] / WAREHOUSE), read_only=True)
    try:
        india = json.loads(con.execute("SELECT payload FROM rm.status WHERE market = 'india'").fetchone()[0])
        version = con.execute("SELECT DISTINCT schema_version FROM rm.status").fetchall()
    finally:
        con.close()
    assert version == [(openapi_spec.version(),)]
    # the catalogue's market_status example reads the same stored bars at this cut-off (docs/DATA_CATALOGUE.md)
    assert india["benchmark"] == {
        "symbol": "NIFTY50",
        "name": "Nifty 50",
        "close": 22776.0996,
        "close_date": "2026-10-06",
        "change_pct": 0.98,
        "change_5d_pct": -0.02,
    }
    assert india["vol_index"]["change_pct"] == -7.92 and india["regime"] == "EVENT_HEAVY"
    assert india["session"]["late_run"] is False and india["as_of"] == "2026-10-06"
    assert india["runs"]["news"] == {"at": None, "ok": None, "new_items": None}  # the first news run is 14:19 UTC
    assert india["runs"]["post_close"]["next_at"] == "2026-10-07T12:15:00Z"  # 17:45 IST
    assert "freshness" not in india and "cutoff" not in india  # added when served, never stored


def test_a_sync_revalidates_written_and_deleted_pages_in_both_modes(warehouse, monkeypatch):
    """The keys a sync to MotherDuck would post after its commit: every written page and every page no longer built,
    after an incremental sync and after a --full rebuild (which deletes the rows before rebuilding them)."""
    posted = []
    monkeypatch.setattr(sync, "PROVIDER_MOTHERDUCK", "local")  # the local file stands in for MotherDuck here
    monkeypatch.setattr(sync, "revalidate", lambda url, build_id, keys: posted.append((url, keys)) or "ok")
    mp = pytest.MonkeyPatch()
    saved_root = common.ROOT
    common.ROOT = warehouse["root"]
    mp.setenv("MB_NOW", CUTOFF)
    mp.delenv("MOTHERDUCK_TOKEN", raising=False)
    path = warehouse["root"] / WAREHOUSE
    gone = {"table": "status", "market": "us", "page_key": "GONE"}

    def add_gone_page():
        con = duckdb.connect(str(path))
        con.execute("INSERT INTO rm.status SELECT * REPLACE ('GONE' AS page_key) FROM rm.status WHERE market = 'us'")
        con.close()

    try:
        cfg = load_market("us")
        for full in (False, True):
            add_gone_page()
            posted.clear()
            summary = sync.sync_market(cfg, full=full, force_local=True)
            assert summary["revalidate"] == "ok" and summary["pages_deleted"] == 1, (full, summary)
            ((url, keys),) = posted
            assert url == "https://omenix.vercel.app"
            assert gone in keys
            written = summary["pages_written"]
            assert len(keys) == written + 1  # incremental: nothing else changed; full: every page is written anew
            assert (written == 0) if not full else (written == sum(summary["read_model_pages"].values()))
    finally:
        common.ROOT = saved_root
        mp.undo()
