"""B12: the company pages' read models (docs/ws/b12.md). W1's example records (design/catalogue/) are stored as their
data kinds in a temporary data root; the payloads built as of the catalogue's cut-off must equal the mockups'
payloads (design/mockups/03-company/data.json, 04-stock-strategies/data.json) key by key. Plus no look-ahead (a
record stored after the cut-off is never read) and the bars' as-of split rule. Offline."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.warehouse import rm_company  # noqa: E402
from marketbrief.warehouse.company_sources import read_sources  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CATALOGUE = REPO / "design" / "catalogue"
MOCKUPS = REPO / "design" / "mockups"
CUTOFF = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
AS_OF, SESSION = "2026-10-06", "2026-10-07"
STORED = ("lifecycle_event", "head_to_head_pick", "prediction", "paper_trade", "cost_view", "trade_check", "reason_ai",
          "results_digest")
EMPTY_BLOCKS = {"company": {}, "agreement": {}, "news": [], "events": []}


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


def utc(value):
    """An ISO time as UTC 'Z' text (stored rows read back as +00:00), other values unchanged."""
    if isinstance(value, str) and len(value) > 10 and value[10] == "T":
        return pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def normal(value):
    """The value with every ISO time in UTC 'Z' text, recursively."""
    if isinstance(value, dict):
        return {key: normal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normal(item) for item in value]
    return utc(value)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "CONFIG", REPO / "config")
    for name in STORED:
        store(tmp_path, name)
    return tmp_path


def sources_of(market: str):
    return read_sources(load_market(market), connect(market), CUTOFF, AS_OF, SESSION)


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
        trades = rm_company.trades_payload(sources, ticker, page["open_trades"])
        blocks = {key: page[key] for key in ("company", "agreement", "news", "events")}
        stock = rm_company.stock_payload(sources, ticker, {}, blocks)
        built = {**stock, **trades, "lifecycle": rm_company.lifecycle_payload(sources, ticker)["lifecycle"]}
        for key in ("lifecycle", "head_to_head", "predictions", "open_trades", "trade_checks", "settled", "reasons",
                    "results", "events", "on_company"):
            assert normal(built[key]) == normal(page[key]), f"{market} {ticker} {key}"


@pytest.mark.usefixtures("root")
@pytest.mark.parametrize("market", ["india", "us"])
def test_stock_strategies_keys_equal_the_mockup(market):
    page = strategies_mockup()[market]
    blocks = {"company": page["company"], "agreement": page["agreement"]}
    built = rm_company.stock_strategies_payload(sources_of(market), page["ticker"], {}, blocks)
    for key in ("predictions", "on_company", "overall"):
        assert normal(built[key]) == normal(page[key]), f"{market} {key}"
    # the mockup keeps the catalogue's order of picks; the read model orders them by family and pick rule
    assert normal(built["head_to_head"]) == normal(sorted(page["head_to_head"],
                                                          key=lambda row: (row["family"], row["pick_rule"])))


@pytest.mark.usefixtures("root")
def test_market_trades_page_holds_every_open_trade_and_the_latest_check():
    for market in ("india", "us"):
        opened = [row for row in catalogue("open_trade")["records"] if row["market"] == market]
        page = rm_company.market_trades_payload(sources_of(market), opened)
        assert len(page["open_trades"]) == len(opened)
        checks = [row for row in catalogue("trade_check")["records"]
                  if row["market"] == market and row["check_at"] <= "2026-10-07T12:00:00Z"]
        newest = max((row["check_at"] for row in checks), default=None)
        assert {row["id"] for row in page["trade_checks"]} == {r["id"] for r in checks if r["check_at"] == newest}
    assert len(rm_company.market_trades_payload(sources_of("india"), [])["trade_checks"]) > 0
    assert rm_company.market_trades_payload(sources_of("us"), [])["trade_checks"] == []   # US checked at 16:27Z


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
        text = json.dumps([rm_company.trades_payload(sources, t, []) for t in tickers], default=str)
        stock = json.dumps([rm_company.stock_payload(sources, t, {}, EMPTY_BLOCKS) for t in tickers], default=str)
        life = json.dumps([rm_company.lifecycle_payload(sources, t) for t in tickers], default=str)
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
    before = rm_company.bars_payload(read_sources(load_market("us"), connect("us"),
                                                  datetime(2026, 10, 2, 21, 15, tzinfo=timezone.utc), "2026-10-02",
                                                  "2026-10-05"), "AAPL")
    assert [(b["date"], b["close"], b["adjusted"]) for b in before["bars"]] == [
        ("2026-10-01", 200.0, False), ("2026-10-02", 100.0, False)]
    after = rm_company.bars_payload(read_sources(load_market("us"), connect("us"), CUTOFF, AS_OF, SESSION), "AAPL")
    assert [(b["date"], b["close"], b["adjusted"]) for b in after["bars"]] == [
        ("2026-10-01", 100.0, True), ("2026-10-02", 100.0, False), ("2026-10-05", 101.0, False)]
