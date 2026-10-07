"""Company lifecycle (B1, docs/SPEC.md F8; marketbrief/lifecycle/, scripts/company.py): the loader switch, the seed,
the watchlist accessor, the validator, onboarding on a fixture company, the CLI end to end, the inbox import, no
look-ahead, deleted companies hidden, inactive companies collected but not predicted or displayed, idempotency.
Offline: a synthetic data root, the real market configs, fixture identifier sources and fixture bars.
Run: pytest -q tests/test_lifecycle.py"""
from __future__ import annotations

import io
import json
import shutil
import sys
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.contracts.watchlist import company, trade_amount, watchlist  # noqa: E402
from marketbrief.core import calendar  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.lifecycle import commands  # noqa: E402
from marketbrief.lifecycle.cli import main  # noqa: E402
from marketbrief.lifecycle.events import stored_events  # noqa: E402
from marketbrief.lifecycle.loader import active_sectors, active_tickers  # noqa: E402
from marketbrief.lifecycle.seed import seed  # noqa: E402
from marketbrief.lifecycle.store import stored_rows  # noqa: E402

REAL_CONFIG = Path(__file__).resolve().parents[1] / "config"
NOW = "2026-10-07T12:00:00+00:00"          # US: 08:00 New York, before the 07:45 pre-open of the 8th
HISTORY_START = date(2026, 7, 1)
FIXT_CIK = 1234567
FIXTURES = {
    "sec": {"FIXT": {"cik": FIXT_CIK, "name": "Fixture Software Corp", "exchange": "NYSE"},
            "OTCX": {"cik": 7654321, "name": "Over The Counter Inc", "exchange": "OTC"}},
    "sec_industry": {str(FIXT_CIK): ["SERVICES-PREPACKAGED SOFTWARE"]},
    "nse": {"FIXTIN": {"name": "Fixture India Ltd", "series": "EQ", "isin": "INE000000000"},
            "NIFTYBEES": {"name": "Nippon ETF", "series": "EQ", "isin": "INF000000000"}},
    "nse_industry": {"FIXTIN": {"strings": ["Cement & Cement Products", "Construction Materials"], "etf": False},
                     "NIFTYBEES": {"strings": [], "etf": True}},
    "yahoo": {"FIXT": {"instrument_type": "EQUITY", "years": 16.2}, "SPY": {"instrument_type": "ETF", "years": 33},
              "FIXTIN.NS": {"instrument_type": "EQUITY", "years": 9.5}, "BSEONLY.BO": {"instrument_type": "EQUITY"},
              "BSEETF.BO": {"instrument_type": "ETF"}},
    "bars": {},
}


def sessions(market: str, start: date, end: date) -> list[date]:
    """The market's sessions from start to end."""
    cfg, out, day = load_market(market), [], start
    while day <= end:
        if calendar.is_session(cfg, day):
            out.append(day)
        day += timedelta(days=1)
    return out


def fixture_bars(market: str, end: date) -> list[list]:
    """Daily bars of a fixture company from the history start to `end`."""
    return [[day.isoformat(), 100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1, 100.5 + i * 0.1, 10000 + i]
            for i, day in enumerate(sessions(market, HISTORY_START, end))]


class FakeSec:
    """The seed's SEC answers for the real US config tickers (exchange NYSE, CIK by position)."""

    offline = True

    def sec_company(self, ticker: str) -> dict:
        return {"cik": 1000 + sum(map(ord, ticker)), "name": ticker, "exchange": "Nasdaq" if ticker < "M" else "NYSE"}


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    """A data root with one stored price day per market, the real config, the clock at NOW, fixture sources."""
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setenv("MB_NOW", NOW)
    for market, ticker in (("us", "AAPL"), ("india", "HDFCBANK")):
        path = tmp_path / "data" / market / "prices" / "2026" / "07" / f"{HISTORY_START}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n"   # csv.writer's endings
                          f"{HISTORY_START},{ticker},1,1,1,1,1,1,2026-07-02T00:00:00+00:00\r\n").encode())
    data = json.loads(json.dumps(FIXTURES))
    data["bars"] = {"FIXT": fixture_bars("us", date(2026, 10, 6)),
                    "FIXTIN.NS": fixture_bars("india", date(2026, 10, 7))}
    (tmp_path / "fixtures.json").write_text(json.dumps(data))
    monkeypatch.setenv("MB_LIFECYCLE_FIXTURES", str(tmp_path / "fixtures.json"))
    return tmp_path


def cli(*args: str) -> tuple[int, dict]:
    """Run scripts/company.py in-process; (exit code, JSON output)."""
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(list(args))
    return code, json.loads(out.getvalue())


def at(monkeypatch, when: str) -> None:
    """Move the clock."""
    monkeypatch.setenv("MB_NOW", when)


def raw_config(market: str) -> dict:
    return yaml.safe_load((REAL_CONFIG / "markets" / f"{market}.yaml").read_text())


# ---------------- loader and seed ----------------

@pytest.mark.parametrize("market", ["india", "us"])
def test_without_events_the_loader_reproduces_the_config(market):
    cfg, raw = load_market(market), raw_config(market)
    assert list(cfg["tickers"]) == list(raw["tickers"])
    assert cfg["sectors"] == raw["sectors"]
    assert cfg["active_tickers"] == list(raw["tickers"])
    assert [c["ticker"] for c in watchlist(market, state="collected")] == sorted(
        raw["tickers"], key=lambda t: (next(s for s, m in raw["sectors"].items() if t in m), t))


@pytest.mark.parametrize("market", ["india", "us"])
def test_seed_reproduces_the_config_even_without_config_tickers(root, monkeypatch, market):
    before = load_market(market)
    result = seed(market, FakeSec())
    assert result["ok"], result
    assert result["seeded"] == 20 and result["effective_from"] == "2026-07-01T00:00:00+00:00"
    assert load_market(market) == before                       # seed + config: identical config
    rows = stored_events(market)
    assert all(r["channel"] == "seed" and r["recorded_at"] == "2026-10-07T12:00:00+00:00" for r in rows)
    # Wave 5 removes `tickers:` and the sector lists: the seed alone gives the same lists and order
    config = root / "config"
    shutil.copytree(REAL_CONFIG, config)
    stripped = raw_config(market)
    stripped.pop("tickers")
    stripped["sectors"] = {}
    (config / "markets" / f"{market}.yaml").write_text(yaml.safe_dump(stripped, sort_keys=False))
    monkeypatch.setattr(common, "CONFIG", config)
    seeded = load_market(market)
    assert list(seeded["tickers"]) == list(before["tickers"])
    assert seeded["sectors"] == before["sectors"]
    for field in ("name", "yahoo"):
        assert {t: m[field] for t, m in seeded["tickers"].items()} == {
            t: m[field] for t, m in before["tickers"].items()}
    # a replay dated before the seeding still sees the seeded watchlist (seed rule), one before history does not
    at(monkeypatch, "2026-09-01T00:00:00+00:00")
    assert list(load_market(market)["tickers"]) == list(before["tickers"])
    at(monkeypatch, "2026-06-30T00:00:00+00:00")
    assert load_market(market)["tickers"] == {}


def test_seed_runs_once():
    assert seed("us", FakeSec())["ok"]
    again = seed("us", FakeSec())
    assert not again["ok"] and "already has seed events" in again["errors"][0]
    assert len(stored_events("us")) == 20


# ---------------- end to end on a fixture company ----------------

def test_lifecycle_end_to_end_on_a_fixture_company(monkeypatch):
    code, added = cli("--market", "us", "add", "--symbol", "FIXT", "--key", "add-fixt-0001")
    assert code == 0 and added["ok"], added
    event = added["event"]
    assert (event["name"], event["exchange"], event["sector"], event["cik"]) == (
        "Fixture Software Corp", "NYSE", "Tech", "0001234567")
    assert event["effective_from"] == event["recorded_at"] == "2026-10-07T12:00:00+00:00"
    assert added["onboarding"]["backfill_prices"] == "ok" and added["onboarding"]["collect_gate"] == "ok"
    assert added["onboarding"]["backfill_filings"] == "skipped"     # offline fixture sources
    assert added["details"]["prices"]["new_bars"] == len(sessions("us", HISTORY_START, date(2026, 10, 6)))
    cfg = load_market("us")
    assert "FIXT" in cfg["tickers"] and "FIXT" in cfg["active_tickers"] and "FIXT" in cfg["sectors"]["Tech"]
    assert cfg["tickers"]["FIXT"]["cik"] == "0001234567"

    code, done = cli("--market", "us", "deactivate", "--ticker", "FIXT", "--reason", "pause", "--key", "deact-fixt-1")
    assert code == 0, done
    pre_open = "2026-10-08T11:45:00+00:00"                          # 07:45 New York on the next session
    assert done["event"]["effective_from"] == pre_open
    assert "FIXT" in load_market("us")["active_tickers"]            # not before the next pre-open run
    at(monkeypatch, pre_open)
    cfg = load_market("us")
    assert "FIXT" in cfg["tickers"] and "FIXT" not in cfg["active_tickers"]   # collected, not predicted
    assert "FIXT" not in active_sectors(cfg)["Tech"]
    assert [c["ticker"] for c in watchlist("us", state="inactive")] == ["FIXT"]

    code, done = cli("--market", "us", "reactivate", "--ticker", "FIXT", "--key", "react-fixt-1")
    assert code == 0 and done["event"]["effective_from"] == "2026-10-09T11:45:00+00:00"
    at(monkeypatch, "2026-10-09T12:00:00+00:00")
    assert "FIXT" in load_market("us")["active_tickers"]

    code, done = cli("--market", "us", "set-amount", "--ticker", "FIXT", "--amount", "2500", "--key", "amt-fixt-01")
    assert code == 0, done
    at(monkeypatch, "2026-10-12T12:00:00+00:00")
    assert company("us", "FIXT")["amount"] == 2500.0 and company("us", "FIXT")["amount_overridden"]
    assert trade_amount("us", "FIXT", datetime(2026, 10, 9, 12, tzinfo=timezone.utc)) == 1000.0
    code, done = cli("--market", "us", "set-amount", "--ticker", "FIXT", "--default", "--key", "amt-fixt-02")
    assert code == 0
    at(monkeypatch, "2026-10-14T12:00:00+00:00")
    assert company("us", "FIXT")["amount"] == 1000.0 and not company("us", "FIXT")["amount_overridden"]

    code, refused = cli("--market", "us", "delete", "--ticker", "FIXT", "--confirm", "FIX", "--key", "del-fixt-01")
    assert code == 2 and "typed confirmation" in refused["errors"][0]
    code, done = cli("--market", "us", "delete", "--ticker", "FIXT", "--confirm", "FIXT", "--key", "del-fixt-02")
    assert code == 0 and done["event"]["event"] == "delete"
    assert_hidden(load_market("us"), "FIXT")
    assert company("us", "FIXT")["state"] == "deleted"
    log = stored_rows("us", "command_log")
    assert [row["result"] for row in log] == ["accepted"] * 5 + ["refused", "accepted"]
    assert all(row["actor"] == "cli:session" and row["channel"] == "cli" for row in log)
    events = stored_events("us")
    assert [row["event"] for row in events] == ["add", "deactivate", "reactivate", "set_amount", "set_amount",
                                                "delete"]
    assert all(row["requested_by"] == "cli:session" and row["idempotency_key"] for row in events)


def assert_hidden(cfg: dict, ticker: str) -> None:
    """A deleted company is in no company list."""
    assert ticker not in cfg["tickers"] and ticker not in cfg["active_tickers"]
    assert all(ticker not in members for members in cfg["sectors"].values())
    for state in ("active", "inactive", "collected"):
        assert ticker not in [c["ticker"] for c in watchlist(cfg["market"], state=state)]
    listed = commands.list_watchlist(cfg["market"])
    assert ticker not in [c["ticker"] for c in listed["companies"]] and listed["counts"]["deleted"] >= 1


def test_india_add_and_sector_rule():
    code, added = cli("--market", "india", "add", "--symbol", "FIXTIN", "--amount", "50000", "--key", "add-fixtin-1")
    assert code == 0, added
    event = added["event"]
    assert (event["exchange"], event["nse_symbol"], event["yahoo"], event["sector"], event["amount"]) == (
        "NSE", "FIXTIN", "FIXTIN.NS", "Construction", 50000.0)
    history = added["details"]["long_history"]                     # into the long-history cache, as far as served
    assert added["onboarding"]["long_history"] == "ok" and history["requested_from"] == "2011-10-07"
    assert history["first"] == "2026-07-01" and history["rows"] == len(sessions("india", HISTORY_START,
                                                                                date(2026, 10, 7)))
    cfg = load_market("india")
    assert cfg["tickers"]["FIXTIN"]["nse"] == "FIXTIN" and cfg["sectors"]["Construction"][-1] == "FIXTIN"


@pytest.mark.parametrize("market,symbol,code_expected", [
    ("us", "SPY", "etf"), ("us", "NOPE", "unknown_symbol"), ("us", "OTCX", "validation_failed"),
    ("india", "NIFTYBEES", "etf"), ("india", "BSEONLY", "bse_only"), ("india", "BSEETF", "etf"),
    ("india", "NOPE", "unknown_symbol"),
    ("us", "AAPL", "already_active"),
])
def test_add_refusals(market, symbol, code_expected):
    code, result = cli("--market", market, "add", "--symbol", symbol, "--key", f"add-{symbol.lower()}-x1")
    assert code == 2 and result["refusal_code"] == code_expected, result
    assert stored_events(market) == []
    assert stored_rows(market, "command_log")[-1]["result"] == "refused"


def test_validator_refusals():
    cases = [
        (["deactivate", "--ticker", "ZZZZ", "--key", "deact-zzzz-1"], "never added"),
        (["reactivate", "--ticker", "AAPL", "--key", "react-aapl-1"], "not allowed for AAPL in state active"),
        (["set-amount", "--ticker", "AAPL", "--amount", "0.5", "--key", "amt-aapl-01"], "amount must be"),
        (["set-amount", "--ticker", "AAPL", "--key", "amt-aapl-02"], "amount must be"),
        (["deactivate", "--ticker", "AAPL", "--key", "short"], "idempotency key"),
        (["delete", "--ticker", "AAPL", "--confirm", "AAPL", "--key", "del-aapl-01", "--channel", "claude_code"],
         "only allowed from the dashboard or the command line"),
    ]
    for args, message in cases:
        code, result = cli("--market", "us", *args)
        assert code == 2 and any(message in error for error in result["errors"]), (args, result)
    assert stored_events("us") == []


def test_deleted_company_needs_a_new_add():
    assert cli("--market", "us", "delete", "--ticker", "DAL", "--confirm", "DAL", "--key", "del-dal-001")[0] == 0
    code, result = cli("--market", "us", "reactivate", "--ticker", "DAL", "--key", "react-dal-01")
    assert code == 2 and result["refusal_code"] == "deleted_needs_new_add"


# ---------------- no look-ahead ----------------

def test_no_look_ahead_in_the_loader(root, monkeypatch):
    at(monkeypatch, "2026-10-07T12:00:00+00:00")
    assert cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-01")[0] == 0
    effective = "2026-10-08T11:45:00+00:00"
    for when, active in [("2026-10-07T11:59:59+00:00", True), ("2026-10-08T11:44:59+00:00", True),
                         (effective, False)]:
        at(monkeypatch, when)
        assert ("DAL" in load_market("us")["active_tickers"]) is active, when
        assert ("DAL" in [c["ticker"] for c in watchlist("us")]) is active, when
    # an event recorded later never shows in an earlier view, even with an earlier effective_from
    row = {**stored_events("us")[0], "id": "we-us-UAL-deactivate-20261010T000000Z", "ticker": "UAL",
           "effective_from": "2026-10-01T00:00:00+00:00", "recorded_at": "2026-10-10T00:00:00+00:00",
           "idempotency_key": "late-ual-01"}
    row.pop("_order")
    path = root / "data" / "us" / "watchlist_events" / "2026" / "10" / "2026-10-10.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n")
    assert "UAL" in watchlist_tickers("us", datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert "UAL" not in watchlist_tickers("us", datetime(2026, 10, 10, tzinfo=timezone.utc))


def watchlist_tickers(market: str, as_of: datetime) -> list[str]:
    return [c["ticker"] for c in watchlist(market, as_of)]


def test_event_never_takes_effect_before_the_newest():
    assert cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-01")[0] == 0
    code, done = cli("--market", "us", "delete", "--ticker", "DAL", "--confirm", "DAL", "--key", "del-dal-002")
    assert code == 0 and done["event"]["effective_from"] == "2026-10-08T11:45:00+00:00"


# ---------------- deleted hidden, inactive not predicted or displayed ----------------

def test_deleted_and_inactive_companies_in_predict_and_display_sites(root, monkeypatch):
    import pandas as pd
    from marketbrief.pipeline.validate.gate_result import Result
    from marketbrief.pipeline.validate.stages import stage_context
    from marketbrief.presentation.dashboard.market import sector_rows

    assert cli("--market", "india", "delete", "--ticker", "HDFCBANK", "--confirm", "HDFCBANK",
               "--key", "del-hdfc-01")[0] == 0
    assert cli("--market", "india", "deactivate", "--ticker", "INFY", "--key", "deact-infy-1")[0] == 0
    at(monkeypatch, "2026-10-09T03:00:00+00:00")
    cfg = load_market("india")
    assert_hidden(cfg, "HDFCBANK")
    assert "ADR_HDB" not in cfg["symbols"] and "ADR_INFY" in cfg["symbols"]   # deleted: its ADR is not collected
    assert "INFY" in cfg["tickers"] and "INFY" not in active_tickers(cfg)
    feats = pd.DataFrame({"ticker": list(cfg["tickers"]), "ret_1d": 0.0, "ret_5d": 0.0})
    shown = [s["ticker"] for row in sector_rows(cfg, feats) for s in row["stocks"]]
    assert "INFY" not in shown and "HDFCBANK" not in shown and "TCS" in shown
    assert active_sectors(cfg)["IT"] == ["TCS"] and active_sectors(cfg)["Banks"] == ["ICICIBANK"]
    # the context gate wants every active company in the pack, not the inactive or deleted ones
    pack = root / "context.md"
    names = " ".join(t for t in cfg["tickers"] if t != "INFY")
    pack.write_text(f"# Context pack 2026-10-09\n{names}\n## Market regime\n")
    res = Result()
    stage_context(res, cfg, None, None, None, date(2026, 10, 9), None, path=pack)
    assert res.failures == []
    pack.write_text(f"# Context pack 2026-10-09\n{names.replace('TCS', '')}\n## Market regime\n")
    stage_context(res, cfg, None, None, None, date(2026, 10, 9), None, path=pack)
    assert res.failures[0]["tickers"] == ["TCS"]


def test_forecast_gate_refuses_inactive_and_deleted(monkeypatch):
    from marketbrief.core.database import connect
    from marketbrief.pipeline.forecast_gate import forecast_context

    assert cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-01")[0] == 0
    assert cli("--market", "us", "delete", "--ticker", "UAL", "--confirm", "UAL", "--key", "del-ual-001")[0] == 0
    at(monkeypatch, "2026-10-08T12:00:00+00:00")
    ctx, _as_of, _ids = forecast_context(load_market("us"), connect("us"))
    assert "DAL" not in ctx["tickers"] and "UAL" not in ctx["tickers"] and "AAPL" in ctx["tickers"]
    assert len(ctx["tickers"]) == 18


# ---------------- idempotency and the inbox ----------------

def test_same_key_twice_stores_one_event():
    first = cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-01")[1]
    code, second = cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-01")
    assert code == 0 and second["duplicate"] and second["event"]["id"] == first["event"]["id"]
    assert len(stored_events("us")) == 1
    assert [row["result"] for row in stored_rows("us", "command_log")] == ["accepted", "duplicate"]


def make_inbox(path: Path, rows: list[tuple]) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA inbox")
    con.execute("CREATE TABLE inbox.company_commands (inbox_id VARCHAR, market VARCHAR, tool VARCHAR, "
                "arguments JSON, actor VARCHAR, channel VARCHAR, submitted_at TIMESTAMPTZ, command_id VARCHAR)")
    con.executemany("INSERT INTO inbox.company_commands VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.close()


def test_inbox_import_is_idempotent(root):
    inbox = root / "web_inbox.duckdb"
    make_inbox(inbox, [
        ("inbox-0001-add", "us", "add_company", json.dumps({"market": "us", "symbol": "FIXT", "amount": 1500}),
         "slack:U07ABCD123", "slack", "2026-10-07T10:00:00Z", "cmd-20261007T100000Z-aaaaaaaa"),
        ("inbox-0002-del", "us", "delete_company", json.dumps({"ticker": "UAL", "confirm": "UAL"}),
         "slack:U07ABCD123", "slack", "2026-10-07T10:01:00Z", None),
        ("inbox-0003-dea", "us", "deactivate_company", json.dumps({"ticker": "DAL", "reason": "pause airlines"}),
         "dashboard:owner", "dashboard", "2026-10-07T10:02:00Z", None),
        ("inbox-0004-ind", "india", "deactivate_company", json.dumps({"ticker": "INFY"}),
         "dashboard:owner", "dashboard", "2026-10-07T10:03:00Z", None),
        ("inbox-0005-trd", "us", "add_paper_trade", json.dumps({"ticker": "AAPL"}),
         "dashboard:owner", "dashboard", "2026-10-07T10:04:00Z", None),
    ])
    code, first = cli("--market", "us", "import-inbox", "--inbox", str(inbox))
    assert code == 0 and first["imported"] == 3, first
    by_id = {r["inbox_id"]: r for r in first["results"]}
    assert by_id["inbox-0001-add"]["ok"] and by_id["inbox-0003-dea"]["ok"]
    assert by_id["inbox-0002-del"]["refusal_code"] == "validation_failed"      # delete is never allowed from Slack
    events = stored_events("us")
    add = next(row for row in events if row["event"] == "add")
    assert (add["requested_by"], add["channel"], add["command_id"], add["amount"]) == (
        "slack:U07ABCD123", "slack", "cmd-20261007T100000Z-aaaaaaaa", 1500.0)
    code, again = cli("--market", "us", "import-inbox", "--inbox", str(inbox))
    assert again["imported"] == 0 and len(stored_events("us")) == len(events)
    assert stored_events("india") == []


# ---------------- onboarding edges ----------------

def write_benchmark_bar(root: Path, market: str, symbol: str, day: date) -> None:
    path = root / "data" / market / "prices" / f"{day:%Y}" / f"{day:%m}" / f"{day}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "" if path.exists() else "date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n"
    with path.open("ab") as handle:
        handle.write((header + f"{day},{symbol},1,1,1,1,1,1,2026-10-07T00:00:00+00:00\r\n").encode())


@pytest.mark.parametrize("benchmark_day,accepted", [(date(2026, 10, 6), True), (date(2026, 10, 7), False)])
def test_gate_stale_only_when_the_market_is_not(root, benchmark_day, accepted):
    """India at 12:00 UTC on 7 Oct: the session closed, but the candidate's newest bar is 6 Oct. Accepted (with a
    warning) only while the benchmark is equally behind."""
    data = json.loads((root / "fixtures.json").read_text())
    data["bars"]["FIXTIN.NS"] = fixture_bars("india", date(2026, 10, 6))
    (root / "fixtures.json").write_text(json.dumps(data))
    write_benchmark_bar(root, "india", "NIFTY50", benchmark_day)
    code, result = cli("--market", "india", "add", "--symbol", "FIXTIN", "--key", "add-fixtin-2")
    gate = result["details"]["collect_gate"]
    if accepted:
        assert code == 0 and gate["warnings"][0]["code"] == "STALE_BARS_MARKET_WIDE"
    else:
        assert code == 2 and gate["failures"][0]["code"] == "STALE_BARS" and stored_events("india") == []


def test_sector_from_the_yahoo_profile_when_nse_refuses(root, monkeypatch):
    from marketbrief.lifecycle.sources import FixtureSources

    def refuse(_self, _symbol):
        raise OSError("HTTP 403 from www.nseindia.com")

    monkeypatch.setattr(FixtureSources, "nse_industry", refuse)
    data = json.loads((root / "fixtures.json").read_text())
    data["yahoo_profile"] = {"FIXTIN.NS": ["Building Materials", "Basic Materials"]}
    (root / "fixtures.json").write_text(json.dumps(data))
    code, result = cli("--market", "india", "add", "--symbol", "FIXTIN", "--key", "add-fixtin-3")
    assert code == 0 and result["event"]["sector"] == "Construction"
    assert result["details"]["industry"] == ["Building Materials", "Basic Materials"]


def test_unmapped_sector_needs_the_owner(root):
    data = json.loads((root / "fixtures.json").read_text())
    data["sec_industry"][str(FIXT_CIK)] = ["SERVICES-MISC AMUSEMENT & RECREATION"]
    (root / "fixtures.json").write_text(json.dumps(data))
    code, result = cli("--market", "us", "add", "--symbol", "FIXT", "--key", "add-fixt-0002")
    assert code == 2 and "pass --sector" in result["errors"][0]
    code, result = cli("--market", "us", "add", "--symbol", "FIXT", "--sector", "Leisure", "--key", "add-fixt-0003")
    assert code == 0 and load_market("us")["sectors"]["Leisure"] == ["FIXT"]


def test_a_source_that_does_not_answer_is_a_failed_command(monkeypatch):
    from marketbrief.lifecycle.sources import FixtureSources

    def down(_self, _ticker):
        raise TimeoutError("sec.gov timed out")

    monkeypatch.setattr(FixtureSources, "sec_company", down)
    code, result = cli("--market", "us", "add", "--symbol", "FIXT", "--key", "add-fixt-0004")
    assert code == 2 and result["failed"] and "did not answer" in result["errors"][0]
    assert stored_events("us") == [] and stored_rows("us", "command_log")[-1]["result"] == "failed"


def test_long_history_merges_into_the_market_cache(root):
    import gzip

    import pandas as pd

    folder = root / "work" / "model_history" / "us"
    folder.mkdir(parents=True)
    old = "ticker,date,open,high,low,close,volume\nAAPL,2011-01-03,1,1,1,1,1\nFIXT,2011-01-03,9,9,9,9,9\n"
    (folder / "bars.csv.gz").write_bytes(gzip.compress(old.encode(), mtime=0))
    (folder / "manifest.json").write_text(json.dumps({"market": "us", "start": "2011-01-01", "symbols": {
        "AAPL": {"rows": 1}}, "failed": [], "fetched_at": "2026-10-01T00:00:00Z"}))
    code, added = cli("--market", "us", "add", "--symbol", "FIXT", "--key", "add-fixt-0005")
    assert code == 0 and added["details"]["long_history"]["requested_from"] == "2011-01-01"
    bars = pd.read_csv(folder / "bars.csv.gz")
    assert bars[bars["ticker"] == "AAPL"].shape[0] == 1                       # other symbols kept
    fixt = bars[bars["ticker"] == "FIXT"]
    assert fixt["date"].min() == "2026-07-01" and len(fixt) == added["details"]["long_history"]["rows"]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert set(manifest["symbols"]) == {"AAPL", "FIXT"} and manifest["rows"] == len(bars)
    assert manifest["fetched_at"] == "2026-10-01T00:00:00Z"                 # the full fetch's time is kept (#108)
    assert manifest["symbols"]["FIXT"]["fetched_at"] == "2026-10-07T12:00:00Z"


def test_inbox_retries_failed_commands_only(root, monkeypatch):
    from marketbrief.lifecycle.sources import FixtureSources

    inbox = root / "web_inbox.duckdb"
    make_inbox(inbox, [
        ("inbox-0010-add", "us", "add_company", json.dumps({"symbol": "FIXT"}), "dashboard:owner", "dashboard",
         "2026-10-07T10:00:00Z", None),
        ("inbox-0011-cli", "us", "deactivate_company", json.dumps({"ticker": "DAL"}), "dashboard:owner", "cli",
         "2026-10-07T10:01:00Z", None),
    ])
    original = FixtureSources.sec_company
    monkeypatch.setattr(FixtureSources, "sec_company", lambda _self, _ticker: (_ for _ in ()).throw(TimeoutError()))
    first = cli("--market", "us", "import-inbox", "--inbox", str(inbox))[1]
    by_id = {r["inbox_id"]: r for r in first["results"]}
    assert by_id["inbox-0010-add"]["ok"] is False and stored_events("us") == []
    assert "not one of" in by_id["inbox-0011-cli"]["errors"][0]           # an inbox row never acts as the CLI
    monkeypatch.setattr(FixtureSources, "sec_company", original)
    second = cli("--market", "us", "import-inbox", "--inbox", str(inbox))[1]
    assert [r["inbox_id"] for r in second["results"]] == ["inbox-0010-add"] and second["results"][0]["ok"]
    assert [row["event"] for row in stored_events("us")] == ["add"]
    assert cli("--market", "us", "import-inbox", "--inbox", str(inbox))[1]["imported"] == 0
    results = [row["result"] for row in stored_rows("us", "command_log")]
    assert results == ["failed", "refused", "accepted"]


def test_command_ids_stay_unique_within_one_second():
    for _ in range(3):
        cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-01")
    ids = [row["id"] for row in stored_rows("us", "command_log")]
    assert len(set(ids)) == 3 and ids[1] == ids[0] + "-2" and ids[2] == ids[0] + "-3"


# ---------------- Slack replies from the inbox import (B6's onboarding confirmation) ----------------

def make_slack_inbox(path: Path, rows: list[tuple]) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA inbox")
    con.execute("CREATE TABLE inbox.company_commands (inbox_id VARCHAR, market VARCHAR, tool VARCHAR, "
                "arguments JSON, actor VARCHAR, channel VARCHAR, submitted_at TIMESTAMPTZ, command_id VARCHAR, "
                "slack_channel VARCHAR, slack_ts VARCHAR)")
    con.executemany("INSERT INTO inbox.company_commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.close()


SLACK_ROWS = [
    ("inbox-0020-dea", "us", "deactivate_company", json.dumps({"ticker": "DAL"}), "slack:U07ABCD123", "slack",
     "2026-10-07T10:00:00Z", None, "C0MARKET", "1728295200.000100"),
    ("inbox-0021-del", "us", "delete_company", json.dumps({"ticker": "UAL", "confirm": "UAL"}), "slack:U07ABCD123",
     "slack", "2026-10-07T10:01:00Z", None, "C0MARKET", "1728295260.000200"),
    ("inbox-0022-rea", "us", "reactivate_company", json.dumps({"ticker": "DAL"}), "dashboard:owner", "dashboard",
     "2026-10-07T10:02:00Z", None, None, None),
]


def test_inbox_replies_in_the_slack_thread_of_each_command():
    from marketbrief.lifecycle.inbox import import_inbox
    from marketbrief.lifecycle.sources import sources_for

    inbox = common.ROOT / "slack_inbox.duckdb"
    make_slack_inbox(inbox, SLACK_ROWS)
    calls = []
    result = import_inbox("us", str(inbox), sources_for(load_market("us")),
                          reply=lambda record, channel, ts: calls.append((record, channel, ts)) or {"posted": 1})
    by_id = {r["inbox_id"]: r for r in result["results"]}
    assert [(record["result"], channel, ts) for record, channel, ts in calls] == [
        ("accepted", "C0MARKET", "1728295200.000100"), ("refused", "C0MARKET", "1728295260.000200")]
    assert calls[0][0]["id"] == by_id["inbox-0020-dea"]["command_id"] and calls[0][0]["tool"] == "deactivate_company"
    assert by_id["inbox-0022-rea"]["slack_reply"] is None      # no Slack message named: no reply
    assert by_id["inbox-0020-dea"]["slack_reply"] == {"posted": 1}


def test_a_slack_failure_never_stops_the_import():
    from marketbrief.lifecycle.inbox import import_inbox
    from marketbrief.lifecycle.sources import sources_for

    def broken(_record, _channel, _ts):
        raise ConnectionError("slack.com unreachable")

    inbox = common.ROOT / "slack_inbox.duckdb"
    make_slack_inbox(inbox, SLACK_ROWS)
    result = import_inbox("us", str(inbox), sources_for(load_market("us")), reply=broken)
    assert result["imported"] == 3                                     # delete refused (Slack); the reactivate
    assert [row["event"] for row in stored_events("us")] == ["deactivate", "reactivate"]   # cancels the pending one
    assert "slack.com unreachable" in result["results"][0]["slack_reply"]["error"]


def test_inbox_reply_through_b6_onboarding_confirmation_dry_run():
    from marketbrief.alerts.onboarding import post_onboarding_confirmation
    from marketbrief.lifecycle.inbox import import_inbox
    from marketbrief.lifecycle.sources import sources_for

    inbox = common.ROOT / "slack_inbox.duckdb"
    make_slack_inbox(inbox, SLACK_ROWS[:1])
    dry = lambda record, channel, ts: post_onboarding_confirmation(record, channel, ts, dry_run=True)  # noqa: E731
    first = import_inbox("us", str(inbox), sources_for(load_market("us")), reply=dry)["results"][0]["slack_reply"]
    assert first["posted"] and first["thread_ts"] == "1728295200.000100"
    command_id = stored_rows("us", "command_log")[0]["id"]
    assert first["post_key"].endswith(f"{command_id}:accepted")


def test_without_slack_reply_the_cli_posts_nothing(monkeypatch):
    import marketbrief.lifecycle.inbox as inbox_module

    monkeypatch.setattr(inbox_module, "default_reply", lambda *_args: pytest.fail("posted without --slack-reply"))
    inbox = common.ROOT / "slack_inbox.duckdb"
    make_slack_inbox(inbox, SLACK_ROWS[:1])
    code, result = cli("--market", "us", "import-inbox", "--inbox", str(inbox))
    assert code == 0 and result["results"][0]["slack_reply"] is None and len(stored_events("us")) == 1



# ---------------- cosmetic batch (#101, #102, #104, #107, #131) ----------------

def test_yahoo_serving_nothing_for_a_listed_symbol_is_a_failed_command():
    data = json.loads((common.ROOT / "fixtures.json").read_text())
    data["yahoo"].pop("FIXT")                       # SEC lists it; Yahoo answers nothing (blocked, rate-limited)
    (common.ROOT / "fixtures.json").write_text(json.dumps(data))
    code, result = cli("--market", "us", "add", "--symbol", "FIXT", "--key", "add-fixt-0101")
    assert code == 2 and result["failed"] and "Yahoo served no daily bars" in result["errors"][0]
    assert stored_rows("us", "command_log")[-1]["result"] == "failed" and stored_events("us") == []


def test_a_yfinance_error_in_the_price_backfill_is_a_failed_command(monkeypatch):
    from marketbrief.lifecycle import backfill

    def rate_limited(*_args, **_kwargs):
        raise RuntimeError("Too Many Requests")

    monkeypatch.setattr(backfill, "backfill_prices", rate_limited)
    code, result = cli("--market", "us", "add", "--symbol", "FIXT", "--key", "add-fixt-0107")
    assert code == 2 and result["failed"] and "Too Many Requests" in result["errors"][0]
    assert stored_rows("us", "command_log")[-1]["result"] == "failed" and stored_events("us") == []


def test_reactivate_cancels_a_pending_deactivate(monkeypatch):
    assert cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-01")[0] == 0
    code, again = cli("--market", "us", "deactivate", "--ticker", "DAL", "--key", "deact-dal-02")
    assert code == 2 and "state inactive" in again["errors"][0]       # already pending
    code, done = cli("--market", "us", "reactivate", "--ticker", "DAL", "--key", "react-dal-01")
    assert code == 0 and done["event"]["effective_from"] == "2026-10-08T11:45:00+00:00"
    at(monkeypatch, "2026-10-08T12:00:00+00:00")
    assert "DAL" in load_market("us")["active_tickers"]               # the deactivate never took hold


def test_announcement_backfill_asks_from_the_configured_window(monkeypatch):
    import marketbrief.collectors.nse_india as nse_india
    from marketbrief.lifecycle import backfill

    seen = {}
    monkeypatch.setattr(nse_india, "collect", lambda _cfg, _nse, kinds, args=None: seen.update(
        kinds=kinds, since=args.since) or {"new": {"announcements": 2}})
    status, _detail = backfill.backfill_announcements(load_market("india"), object(), 30)
    assert status == "ok" and seen == {"kinds": ["announcements"], "since": date(2026, 9, 7)}


def test_masked_hides_the_inbox_and_slack_tokens(monkeypatch):
    from marketbrief.lifecycle.inbox import masked

    monkeypatch.setenv("MOTHERDUCK_INBOX_TOKEN", "md-secret-123")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret-456")
    assert masked("auth md-secret-123 and xoxb-secret-456 failed") == "auth *** and *** failed"


def test_old_inbox_schema_never_replies():
    from marketbrief.lifecycle.inbox import import_inbox
    from marketbrief.lifecycle.sources import sources_for

    inbox = common.ROOT / "old_inbox.duckdb"
    make_inbox(inbox, [("inbox-0030-dea", "us", "deactivate_company", json.dumps({"ticker": "DAL"}),
                        "dashboard:owner", "dashboard", "2026-10-07T10:00:00Z", None)])
    result = import_inbox("us", str(inbox), sources_for(load_market("us")),
                          reply=lambda *_args: pytest.fail("replied without slack columns"))
    assert result["results"][0]["ok"] and result["results"][0]["slack_reply"] is None


def test_slack_reply_flag_passes_b6s_confirmation(monkeypatch):
    import marketbrief.lifecycle.inbox as inbox_module

    calls = []
    monkeypatch.setattr(inbox_module, "default_reply", lambda record, channel, ts: calls.append(
        (record["result"], channel, ts)) or {"posted": ["x#1"]})
    inbox = common.ROOT / "slack_inbox.duckdb"
    make_slack_inbox(inbox, SLACK_ROWS[:1])
    code, result = cli("--market", "us", "import-inbox", "--inbox", str(inbox), "--slack-reply")
    assert code == 0 and calls == [("accepted", "C0MARKET", "1728295200.000100")]
    assert result["results"][0]["slack_reply"] == {"posted": ["x#1"]}


def test_onboard_workflow_imports_company_commands_then_paper_trades():
    workflow = yaml.safe_load((REAL_CONFIG.parent / ".github" / "workflows" / "onboard.yml").read_text())
    script = next(step["run"] for step in workflow["jobs"]["import"]["steps"]
                  if step.get("name") == "Import the inbox and onboard")
    company = script.index('python scripts/company.py --market "$market" import-inbox --slack-reply')
    trades = script.index('python scripts/portfolio.py --market "$market" import-inbox')
    assert company < trades and "status=$?" in script[trades:]
    env = workflow["jobs"]["import"]["env"]
    assert {"MOTHERDUCK_INBOX_TOKEN", "SEC_USER_AGENT", "SLACK_BOT_TOKEN"} <= set(env)


def test_log_command_keeps_returning_the_id():
    """B2's paper-trade importer stores log_command's return value as its command_log_id (a string)."""
    from marketbrief.lifecycle.store import command_row, log_command

    received = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    row = command_row("us", received, {"idempotency_key": "trade-key-001", "channel": "slack"}, "accepted")
    first, second = log_command("us", row), log_command("us", row)
    assert isinstance(first, str) and second == first + "-2"
