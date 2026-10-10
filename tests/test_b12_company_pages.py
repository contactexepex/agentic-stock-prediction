"""B12: the company pages' read models (docs/ws/b12.md). W1's example records (design/catalogue/) are stored as their
data kinds in a temporary data root; the payloads built as of the catalogue's cut-off must equal the mockups'
payloads (design/mockups/03-company/data.json, 04-stock-strategies/data.json) key by key. Plus no look-ahead (a
record stored after the cut-off is never read) and the bars' as-of split rule. Offline."""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.warehouse import company_payloads, rm_company  # noqa: E402
from marketbrief.warehouse.company_sources import read_sources  # noqa: E402
from marketbrief.warehouse.rm_registry import BuildContext  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CATALOGUE = REPO / "design" / "catalogue"
MOCKUPS = REPO / "design" / "mockups"
CUTOFF = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
AS_OF, SESSION = "2026-10-06", "2026-10-07"
STORED = ("lifecycle_event", "head_to_head_pick", "prediction", "paper_trade", "cost_view", "trade_check", "reason_ai",
          "results_digest")
# the catalogue's strategies have no live_from yet (go-live sets it): every strategy is live for this module, so the
# pages hold the example rows (tests/conftest.py all_strategies_live, module-scoped, set up before the page fixtures)
pytestmark = pytest.mark.usefixtures("all_strategies_live")
EMPTY_BLOCKS = {"company": {}, "agreement": {}, "open_trades": [], "news": [], "events": []}


def catalogue(name: str) -> dict:
    return json.loads((CATALOGUE / f"{name}.json").read_text())


def market_of(record: dict) -> str:
    """A digest has no market: its ticker's."""
    if record.get("market"):
        return record["market"]
    return "india" if record["ticker"] in load_market("india")["tickers"] else "us"


def store(root: Path, name: str, extra: list[dict] | None = None) -> None:
    """Append W1's example records of `name` (plus `extra`) to their kind, one file per market."""
    file = catalogue(name)
    for record in file["records"] + (extra or []):
        path = root / "data" / market_of(record) / file["kind"] / "2026" / "10" / "2026-10-07.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "CONFIG", REPO / "config")
    for name in STORED:
        store(tmp_path, name)
    return tmp_path


class FixtureContext(BuildContext):
    """A build context whose as-of date is the catalogue's (the fixture root stores no features)."""

    as_of_date: str = AS_OF

    @property
    def as_of(self) -> str:
        return self.as_of_date


def sources_of(market: str, cutoff: datetime = CUTOFF, as_of: str = AS_OF, session: str = SESSION):
    ctx = FixtureContext(load_market(market), connect(market), cutoff)
    ctx.as_of_date = as_of
    return read_sources(ctx, as_of, session)


def company_mockup() -> dict:
    return json.loads((MOCKUPS / "03-company" / "data.json").read_text())["markets"]


def strategies_mockup() -> dict:
    return json.loads((MOCKUPS / "04-stock-strategies" / "data.json").read_text())["markets"]


@pytest.mark.usefixtures("root")
@pytest.mark.parametrize("market", ["india", "us"])
def test_company_page_keys_equal_the_mockup(market):
    sources = sources_of(market)
    pages = company_mockup()[market]["pages"]
    for ticker, page in pages.items():
        blocks = {key: page[key] for key in ("company", "agreement", "open_trades", "news", "events")}
        built = company_payloads.stock_payload(sources, ticker, {}, blocks)
        trades = company_payloads.trades_payload(sources, ticker, page["open_trades"], None)
        assert trades["settled"] == built["settled"]
        for key in ("lifecycle", "head_to_head", "predictions", "open_trades", "trade_checks", "settled", "reasons",
                    "results", "events", "on_company"):
            assert built[key] == page[key], f"{market} {ticker} {key}"


@pytest.mark.usefixtures("root")
@pytest.mark.parametrize("market", ["india", "us"])
def test_stock_strategies_keys_equal_the_mockup(market):
    page = strategies_mockup()[market]
    blocks = {"company": page["company"], "agreement": page["agreement"]}
    built = company_payloads.stock_strategies_payload(sources_of(market), page["ticker"], {}, blocks)
    for key in ("predictions", "on_company", "overall"):
        assert built[key] == page[key], f"{market} {key}"
    # the mockup keeps the catalogue's order of picks; the read model orders them by family and pick rule
    assert built["head_to_head"] == (sorted(page["head_to_head"],
                                                          key=lambda row: (row["family"], row["pick_rule"])))


@pytest.mark.usefixtures("root")
def test_market_trades_page_holds_every_open_trade_and_the_latest_check():
    for market in ("india", "us"):
        opened = [row for row in catalogue("open_trade")["records"] if row["market"] == market]
        page = company_payloads.market_trades_payload(sources_of(market), opened, None)
        assert len(page["open_trades"]) == len(opened)
        checks = [row for row in catalogue("trade_check")["records"]
                  if row["market"] == market and row["check_at"] <= "2026-10-07T12:00:00Z"]
        newest = max((row["check_at"] for row in checks), default=None)
        assert {row["id"] for row in page["trade_checks"]} == {r["id"] for r in checks if r["check_at"] == newest}
    assert len(company_payloads.market_trades_payload(sources_of("india"), [], None)["trade_checks"]) > 0
    us = company_payloads.market_trades_payload(sources_of("us"), [], None)
    assert us["trade_checks"] == []  # the US check of 7 Oct ran at 16:27Z, after the cut-off


@pytest.mark.usefixtures("root")
def test_nothing_stored_after_the_cutoff_is_read():
    """A pick, prediction, settlement, check, reason, digest and lifecycle event stored after the cut-off stay out."""
    late = "2026-10-07T12:00:01Z"
    later = {
        "head_to_head_pick": {**catalogue("head_to_head_pick")["records"][0], "id": "late-pick", "made_at": late},
        "prediction": {**catalogue("prediction")["records"][0], "id": "late-pred", "made_at": late},
        "paper_trade": {**catalogue("paper_trade")["records"][0], "id": "late-trade", "trade_id": "late",
                        "settled_at": late},
        "trade_check": {**catalogue("trade_check")["records"][0], "id": "late-check", "check_at": late,
                        "computed_at": late},
        "reason_ai": {**catalogue("reason_ai")["records"][0], "id": "late-reason", "created_at": late},
        "results_digest": {**catalogue("results_digest")["records"][0], "id": "late-digest", "created_at": late},
        "lifecycle_event": {**catalogue("lifecycle_event")["records"][0], "id": "late-event", "recorded_at": late,
                            "channel": "cli", "effective_from": late},
    }
    for name, record in later.items():
        path = common.ROOT / "data" / market_of(record) / catalogue(name)["kind"] / "2026" / "10" / "2026-10-08.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record) + "\n")
    for market in ("india", "us"):
        sources, tickers = sources_of(market), load_market(market)["tickers"]
        text = json.dumps([company_payloads.trades_payload(sources, t, [], None) for t in tickers], default=str)
        stock = json.dumps([company_payloads.stock_payload(sources, t, {}, EMPTY_BLOCKS) for t in tickers], default=str)
        life = json.dumps([company_payloads.bars_payload(sources, t) for t in tickers]
                          + [company_payloads.lifecycle_payload(sources, t, d) for t in tickers
                             for d in ("2026-10-06", "2026-10-07", "2026-10-08")], default=str)
        for record_id in ("late-pick", "late-pred", "late-trade", "late-check", "late-reason", "late-digest",
                          "late-event"):
            assert record_id not in text + stock + life


def write_prices(root: Path, rows: list[tuple]) -> None:
    for day, ticker, close, collected in rows:
        path = root / "data" / "us" / "prices" / day[:4] / day[5:7] / f"{day}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        head = "" if path.exists() else "date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n"
        with path.open("a", newline="") as handle:
            handle.write(f"{head}{day},{ticker},{close},{close},{close},{close},{close},1000,{collected}\r\n")


def test_bars_apply_only_the_splits_known_by_the_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "CONFIG", REPO / "config")
    write_prices(tmp_path, [("2026-10-01", "AAPL", 200.0, "2026-10-01T21:00:00Z"),
                            ("2026-10-02", "AAPL", 100.0, "2026-10-02T21:00:00Z"),
                            ("2026-10-05", "AAPL", 101.0, "2026-10-05T21:00:00Z"),
                            ("2026-10-06", "AAPL", 999.0, "2026-10-07T13:00:00Z")])   # collected after the cut-off
    split = {"id": "adj-AAPL-2026-10-02", "ticker": "AAPL", "ex_date": "2026-10-02", "factor": 0.5,
             "kind": "split", "detected_at": "2026-10-02T21:30:00Z", "source": "yahoo"}
    path = tmp_path / "data" / "us" / "adjustments" / "2026" / "10" / "2026-10-02.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(split) + "\n")
    before = company_payloads.bars_payload(sources_of("us", datetime(2026, 10, 2, 21, 15, tzinfo=timezone.utc),
                                                "2026-10-02", "2026-10-05"), "AAPL")
    assert [(b["date"], b["close"], b["adjusted"]) for b in before["bars"]] == [
        ("2026-10-01", 200.0, False), ("2026-10-02", 100.0, False)]
    after = company_payloads.bars_payload(sources_of("us"), "AAPL")
    assert [(b["date"], b["close"], b["adjusted"]) for b in after["bars"]] == [
        ("2026-10-01", 100.0, True), ("2026-10-02", 100.0, False), ("2026-10-05", 101.0, False)]


def test_w1_catalogue_modules_still_import():
    """The 1.0 stock/bars removal keeps what W1's catalogue build (design/catalogue/make_examples.py) imports."""
    sys.path.insert(0, str(CATALOGUE))
    try:
        for name in ("catalogue_calendar", "catalogue_entities", "catalogue_more"):
            importlib.import_module(name)
    finally:
        sys.path.remove(str(CATALOGUE))


@pytest.mark.usefixtures("root")
@pytest.mark.parametrize("market", ["india", "us"])
def test_lifecycle_page_holds_the_predictions_made_for_the_session(market):
    """The page of D holds the predictions and picks made for D (as the company page shows them) and only the
    checks, settlements and reasons of those predictions' trades."""
    sources = sources_of(market)
    for ticker, page in company_mockup()[market]["pages"].items():
        day = company_payloads.lifecycle_payload(sources, ticker, SESSION)
        assert day["predictions"] == [p for p in page["predictions"] if p["session_date"] == SESSION]
        assert day["head_to_head"] == sorted(page["head_to_head"], key=lambda r: (r["family"], r["pick_rule"]))
        made = {p["id"] for p in day["predictions"]} | {p["prediction_id"] for p in day["head_to_head"]}
        assert all(row["prediction_id"] in made for row in day["trade_checks"] + day["settled"])
        assert company_payloads.lifecycle_payload(sources, ticker, "2026-09-01") == {
            "market": market, "ticker": ticker, "session_date": "2026-09-01", "predictions": [], "head_to_head": [],
            "trade_checks": [], "settled": [], "reasons": []}


@pytest.mark.usefixtures("root")
def test_lifecycle_follows_a_prediction_to_its_checks_settlement_and_reasons():
    """An N+k prediction made for D is checked and settled on later sessions: all of it shows on D's page."""
    checks = [c for c in catalogue("trade_check")["records"] if c["market"] == "india" and c["view"] == "accuracy"]
    settled = {s["prediction_id"]: s for s in catalogue("paper_trade")["records"] if s["market"] == "india"}
    check = checks[0]
    template = next(p for p in catalogue("prediction")["records"] if p["market"] == "india")
    made = {**template, "id": check["prediction_id"], "ticker": check["ticker"], "strategy_id": check["strategy_id"],
            "horizon_days": check["horizon_days"], "session_date": check["entry_date"],
            "exit_date": check["exit_date"], "made_at": f"{check['entry_date']}T02:10:00Z"}
    trade = {**next(iter(settled.values())), "id": "settled-of-made", "trade_id": check["trade_id"],
             "prediction_id": check["prediction_id"], "ticker": check["ticker"], "entry_date": check["entry_date"],
             "exit_date": check["exit_date"], "exit_date_actual": check["exit_date"],
             "settled_at": "2026-10-07T11:00:00Z"}
    reason = {**catalogue("reason_ai")["records"][0], "id": "reason-of-made", "trade_id": check["trade_id"],
              "market": "india", "ticker": check["ticker"], "session_date": check["exit_date"],
              "created_at": "2026-10-07T11:30:00Z"}
    store(common.ROOT, "prediction", [made])
    store(common.ROOT, "paper_trade", [trade])
    store(common.ROOT, "reason_ai", [reason])
    sources = sources_of("india")
    page = company_payloads.lifecycle_payload(sources, check["ticker"], check["entry_date"])
    assert check["entry_date"] < check["session_date"]          # checked on a later session than D
    assert check["prediction_id"] in {p["id"] for p in page["predictions"]}
    assert check["id"] in {c["id"] for c in page["trade_checks"]}
    assert "settled-of-made" in {s["id"] for s in page["settled"]}
    assert "reason-of-made" in {r["id"] for r in page["reasons"]}
    other = company_payloads.lifecycle_payload(sources, check["ticker"], check["session_date"])
    assert check["id"] not in {c["id"] for c in other["trade_checks"]}
    assert "settled-of-made" not in {s["id"] for s in other["settled"]}


def test_sessions_back_skips_closed_days():
    india = load_market("india")    # 2 Oct 2026 is an NSE holiday (Gandhi Jayanti)
    assert rm_company.sessions_back(india, "2026-10-07", 5) == [
        "2026-09-30", "2026-10-01", "2026-10-05", "2026-10-06", "2026-10-07"]
    assert rm_company.sessions_back(india, "2026-10-04", 2) == ["2026-09-30", "2026-10-01"]  # a Sunday: back to Thu
    assert rm_company.sessions_back(india, None, 5) == []


@pytest.mark.usefixtures("root")
def test_trades_windows_keep_recent_settlements_only():
    sources = sources_of("us")
    settled = [row for rows in sources.settled.values() for row in rows]
    first = "2026-10-06"
    page = company_payloads.market_trades_payload(sources, [], first)
    assert page["settled"] and all((r["exit_date_actual"] or r["exit_date"]) >= first for r in page["settled"])
    assert len(page["settled"]) == sum((r["exit_date_actual"] or r["exit_date"]) >= first for r in settled)
    nvda = company_payloads.trades_payload(sources, "NVDA", [], first)
    assert all((r["exit_date_actual"] or r["exit_date"]) >= first for r in nvda["settled"])
    assert all(r["session_date"] >= first for r in nvda["reasons"])


@pytest.mark.usefixtures("root")
def test_a_strategy_not_live_on_its_day_is_left_out(monkeypatch):
    """Go-live: a strategy's predictions and picks (by their session D) and its trades' checks (by entry D) show only
    when it is live on that D (lab/registry.is_live): rehearsal rows never reach the company, lifecycle or trades
    pages."""
    from marketbrief.lab import registry

    reference = "rule.model_news.v1"
    before = sources_of("india")
    assert any(p["strategy_id"] == reference for rows in before.all_predictions.values() for p in rows)
    assert any(c["strategy_id"] == reference for rows in before.all_checks.values() for c in rows)
    monkeypatch.setattr(registry, "is_live", lambda strategy, _day, **_options: strategy != reference)
    after = sources_of("india")
    lists = [after.all_predictions, after.all_picks, after.all_checks, after.predictions, after.picks, after.checks]
    assert all(row.get("strategy_id") != reference for rows in lists for ticker_rows in rows.values()
               for row in ticker_rows)
    assert all(row["strategy_id"] != reference for row in after.market_checks)
    assert after.market_checks and after.all_predictions  # the other strategies' rows stay
    for ticker in company_mockup()["india"]["pages"]:
        page = company_payloads.lifecycle_payload(after, ticker, SESSION)
        assert all(row.get("strategy_id") != reference for row in page["predictions"] + page["trade_checks"])


def published_range(ticker: str, as_of: str, horizon: int, made_at: str, center: float) -> dict:
    """A ranges.py row (the stored ranges kind's fields) of an as-of date and horizon."""
    session, exit_day = {"2026-10-05": ("2026-10-06", "2026-10-07"), "2026-10-06": ("2026-10-07", "2026-10-08"),
                         "2026-10-07": ("2026-10-08", "2026-10-09")}[as_of]
    return {"id": f"{as_of}-{ticker}-{horizon}d", "made_at": made_at, "as_of_date": as_of, "session_date": session,
            "target_date": exit_day, "ticker": ticker, "horizon_days": horizon, "base_close": 1000.0,
            "center": center, "sigma_h": 0.02, "lo50": 980.0, "hi50": 1020.0, "lo80": 960.0, "hi80": 1040.0,
            "naive_lo50": 981.0, "naive_hi50": 1019.0, "naive_lo80": 961.0, "naive_hi80": 1039.0,
            "direction": None, "confidence": None, "regime": "CALM", "calibration_id": "test", "notes": [],
            "inputs": [], "iv_sigma_h": None, "horizon_label": "n_plus_k", "entry_date": session,
            "exit_date": exit_day}


def test_published_ranges_show_when_no_strategy_is_live(root, monkeypatch):
    """ranges.py publishes a range for every company whatever a strategy's live_from: the company page carries the
    as-of date's ranges (B10's ranges_asof as of the cut-off) when no strategy is live and its predictions are left
    out; an older as-of date, a range stored after the cut-off and a company not collected never show."""
    from marketbrief.lab import registry

    ticker = next(iter(company_mockup()["india"]["pages"]))
    rows = [published_range(ticker, AS_OF, 2, "2026-10-07T02:30:00Z", 0.0),
            published_range(ticker, AS_OF, 1, "2026-10-07T02:30:00Z", 0.01),
            published_range(ticker, "2026-10-05", 1, "2026-10-06T02:30:00Z", 0.0),
            published_range(ticker, "2026-10-07", 1, "2026-10-08T02:30:00Z", 0.0),  # after the cut-off
            published_range("NOTCOLLECTED", AS_OF, 1, "2026-10-07T02:30:00Z", 0.0)]
    for as_of in ("2026-10-05", "2026-10-06", "2026-10-07"):
        path = root / "data" / "india" / "ranges" / "2026" / "10" / f"{as_of}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows if row["as_of_date"] == as_of))
    monkeypatch.setattr(registry, "is_live", lambda _strategy, _day, **_options: False)
    sources = sources_of("india")
    assert not sources.predictions and not sources.all_predictions
    assert set(sources.ranges) == {ticker}
    page = company_payloads.stock_payload(sources, ticker, {}, EMPTY_BLOCKS)
    assert page["predictions"] == []
    assert [(row["id"], row["horizon_days"]) for row in page["published_ranges"]] == [
        (f"{AS_OF}-{ticker}-1d", 1), (f"{AS_OF}-{ticker}-2d", 2)]
    first = page["published_ranges"][0]
    assert first == {"id": f"{AS_OF}-{ticker}-1d", "made_at": "2026-10-07T02:30:00Z", "as_of_date": AS_OF,
                     "session_date": SESSION, "exit_date": "2026-10-08", "horizon_days": 1, "base_close": 1000.0,
                     "target_price": 1010.0502, "lo50": 980.0, "hi50": 1020.0, "lo80": 960.0, "hi80": 1040.0,
                     "regime": "CALM"}
