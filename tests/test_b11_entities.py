"""B11's entity reads for the market pages (marketbrief/warehouse/news_items.py, calendar_events.py,
company_records.py): News items, Calendar events, lifecycle events and commands as of a cut-off, on a small
synthetic US store. Nothing stored, scored, verified or seen after the cut-off reaches a record; the News page's cap
keeps company and market-wide items apart; a deleted company is never shown and is masked in commands."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core import database  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.warehouse import calendar_events, company_records, news_items  # noqa: E402

CUTOFF = datetime.fromisoformat("2026-10-07T12:00:00+00:00")
BEFORE = "2026-10-07T08:00:00+00:00"
AFTER = "2026-10-07T13:00:00+00:00"


def append(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / "us" / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def news(news_id: str, first_seen: str, tickers: list[str], primary: list[str]) -> dict:
    return {"id": news_id, "title": f"Headline {news_id}", "url": f"https://example.com/{news_id}", "source": "Example",
            "source_domain": "example.com", "published_at": first_seen, "first_seen_at": first_seen,
            "feed": "test", "category": "company" if primary else "macro", "tickers": tickers,
            "primary_tickers": primary}


def enriched(news_id: str, analyzed_at: str, materiality: str = "medium", relevance: float = 0.8,
             event_type: str = "product") -> dict:
    return {"id": news_id, "analyzed_at": analyzed_at, "relevance": relevance, "sentiment": 0.3, "novelty": 0.5,
            "materiality": materiality, "event_type": event_type, "urgency": "low", "geopolitical": False,
            "priced_in": False, "summary": f"Product item on AAPL: {news_id}"}


def verified(row_id: str, as_of: str, status: str, news_id: str, ticker: str = "AAPL") -> dict:
    return {"id": row_id, "as_of": as_of, "inputs_until": as_of, "cluster_id": f"c-{ticker}", "level": "cluster",
            "ticker": ticker, "status": status, "status_ids": [news_id], "id_statuses": [status],
            "independent_origins": 1, "primary_ids": []}


def store(root: Path) -> None:
    day = "2026-10-07"
    append(root, "news", day, [
        news("aapl-ok", BEFORE, ["AAPL"], ["AAPL"]),
        news("aapl-late", AFTER, ["AAPL"], ["AAPL"]),            # first seen after the cut-off
        news("aapl-unscored", BEFORE, ["AAPL"], ["AAPL"]),       # scored only after the cut-off
        news("macro-high", BEFORE, [], []),
        news("macro-offtopic", BEFORE, [], []),                 # relevance below 0.4
        news("aapl-old", "2026-09-20T08:00:00+00:00", ["AAPL"], ["AAPL"]),
    ])
    append(root, "news_enriched", day, [
        enriched("aapl-ok", BEFORE), enriched("aapl-late", AFTER), enriched("aapl-unscored", AFTER),
        enriched("macro-high", BEFORE, materiality="high", event_type="macro"),
        enriched("macro-offtopic", BEFORE, relevance=0.2), enriched("aapl-old", "2026-09-20T09:00:00+00:00"),
    ])
    append(root, "news_verified", day, [verified("v1", BEFORE, "single_source", "aapl-ok"),
                                        verified("v2", AFTER, "contradicted", "aapl-ok"),
                                        verified("v3", BEFORE, "rumour", "aapl-ok", ticker="JPM")])
    append(root, "news_updates", day, [
        {"id": "u1", "news_id": "aapl-ok", "title": "Earlier headline", "seen_at": BEFORE},
        {"id": "u2", "news_id": "aapl-ok", "title": "Later headline", "seen_at": AFTER},
    ])
    append(root, "news_articles", day, [
        {"id": "aapl-ok", "fetched_at": BEFORE, "access": "full", "extract": ["First.", "Second.", "Third."]},
    ])
    append(root, "events", day, [
        {"id": "AAPL-earnings-2026-10-29", "date": "2026-10-29", "type": "earnings", "ticker": "AAPL",
         "name": "Apple earnings", "source": "yfinance", "first_seen_at": BEFORE},
        {"id": "AAPL-earnings-2026-11-02", "date": "2026-11-02", "type": "earnings", "ticker": "AAPL",
         "name": "Apple earnings", "source": "yfinance", "first_seen_at": AFTER},   # moved after the cut-off
        {"id": "DAL-earnings-2026-10-09", "date": "2026-10-09", "type": "earnings", "ticker": "DAL",
         "name": "Delta earnings", "source": "yfinance", "first_seen_at": BEFORE},  # DAL is inactive
    ])
    deactivate = {"id": "we-us-DAL-deactivate-20261005T000000Z", "market": "us", "ticker": "DAL",
                  "event": "deactivate", "effective_from": "2026-10-05T11:45:00+00:00",
                  "recorded_at": "2026-10-05T00:00:00+00:00", "reason": "pause airlines",
                  "requested_by": "dashboard:owner", "channel": "dashboard", "idempotency_key": "deact-dal-1"}
    delete = {**deactivate, "id": "we-us-PGR-delete-20261006T000000Z", "ticker": "PGR", "event": "delete",
              "effective_from": "2026-10-06T00:00:00+00:00", "recorded_at": "2026-10-06T00:00:00+00:00",
              "idempotency_key": "del-pgr-1"}
    later = {**deactivate, "id": "we-us-JPM-deactivate-20261007T130000Z", "ticker": "JPM",
             "effective_from": AFTER, "recorded_at": AFTER, "idempotency_key": "deact-jpm-1"}
    append(root, "watchlist_events", "2026-10-05", [deactivate])
    append(root, "watchlist_events", "2026-10-06", [delete])
    append(root, "watchlist_events", day, [later])
    command = {"id": "cmd-1", "market": "us", "received_at": "2026-10-06T00:00:00+00:00", "channel": "dashboard",
               "actor": "dashboard:owner", "agent": "dashboard", "tool": "delete_company", "kind": "write",
               "arguments": {"market": "us", "ticker": "PGR"}, "idempotency_key": "del-pgr-1", "result": "accepted",
               "message": "PGR deleted", "record_ids": ["we-us-PGR-delete-20261006T000000Z"]}
    other = {**command, "id": "cmd-2", "tool": "add_company", "arguments": {"market": "us", "symbol": "SPY"},
             "idempotency_key": "add-spy-1", "result": "refused", "message": "SPY is an ETF", "record_ids": []}
    read = {**other, "id": "cmd-3", "tool": "get_scoreboard"}
    late = {**other, "id": "cmd-4", "received_at": AFTER}
    append(root, "command_log", "2026-10-06", [command, other, read])
    append(root, "command_log", day, [late])


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    root = tmp_path_factory.mktemp("b11")
    store(root)
    saved, mp = common.ROOT, pytest.MonkeyPatch()
    common.ROOT = root
    mp.setenv("MB_NOW", CUTOFF.isoformat())
    try:
        yield load_market("us"), database.connect("us")
    finally:
        common.ROOT = saved
        mp.undo()


def test_news_items_only_what_was_known_at_the_cutoff(market):
    cfg, con = market
    items = {item["id"]: item for item in news_items.news_items(cfg, con, CUTOFF)}
    assert set(items) == {"aapl-ok", "macro-high", "aapl-old"}
    ok = items["aapl-ok"]
    assert ok["status"] == "single_source"          # the contradicted row is stored after the cut-off
    assert ok["headline_history"] == [{"seen_at": "2026-10-07T08:00:00Z", "title": "Earlier headline"}]
    assert (ok["summary"], ok["summary_source"]) == ("First. Second.", "article")
    assert ok["scope"] == "company" and ok["market_moving"] is False
    macro = items["macro-high"]
    assert macro["scope"] == "market" and macro["market_moving"] is True and macro["status"] is None
    assert macro["summary_source"] == "none"         # the analyst's summary is the templated form
    ordered = news_items.news_items(cfg, con, CUTOFF)
    assert [i["id"] for i in ordered] == ["aapl-ok", "macro-high", "aapl-old"]   # newest first, then by id


def test_news_items_filters_by_ticker_and_since(market):
    cfg, con = market
    since = datetime.fromisoformat("2026-10-01T00:00:00+00:00")
    assert [i["id"] for i in news_items.news_items(cfg, con, CUTOFF, tickers=["AAPL"])] == ["aapl-ok", "aapl-old"]
    assert [i["id"] for i in news_items.news_items(cfg, con, CUTOFF, tickers=["AAPL"], since=since)] == ["aapl-ok"]


def test_news_items_status_of_a_named_ticker(market):
    cfg, con = market
    items = {i["id"]: i for i in news_items.news_items(cfg, con, CUTOFF, status_ticker="JPM")}
    assert (items["aapl-ok"]["status"], items["aapl-ok"]["cluster_id"]) == ("rumour", "c-JPM")
    assert items["aapl-old"]["status"] is None


def test_news_window_counts_and_record(market):
    cfg, con = market
    items, window = news_items.news_window(cfg, con, CUTOFF, 3, 50)
    assert [i["id"] for i in items] == ["aapl-ok", "macro-high"]      # same time: by id
    assert window == {"days": 3, "from": "2026-10-04T12:00:00Z", "to": "2026-10-07T12:00:00Z", "max_items": 50,
                      "stored_in_window": 2, "older_hidden": 1}


def record(news_id: str, scope: str, seen: str, moving: bool = False, materiality: str = "low") -> dict:
    return {"id": news_id, "scope": scope, "first_seen_at": seen, "market_moving": moving,
            "enrichment": {"materiality": materiality}}


def test_cap_splits_company_and_market_items():
    market_items = [record(f"m{i}", "market", f"2026-10-07T0{i}:00:00Z", moving=True) for i in range(6)]
    company_items = [record(f"c{i}", "company", f"2026-10-06T0{i}:00:00Z") for i in range(6)]
    kept = news_items.capped(market_items + company_items, 4)
    assert sorted(i["id"] for i in kept) == ["c4", "c5", "m4", "m5"]     # two each, the newest of each
    assert [i["id"] for i in kept] == ["m5", "m4", "c5", "c4"]           # newest first
    few = news_items.capped(market_items + company_items[:1], 4)          # an unused share goes to the other scope
    assert sorted(i["id"] for i in few) == ["c0", "m3", "m4", "m5"]
    mixed = [record("hi", "market", "2026-10-01T00:00:00Z", materiality="high")] + market_items[:2]
    assert news_items.capped(mixed, 2)[-1]["id"] in ("m0", "m1")          # movers before high materiality


def test_calendar_events_as_of_cutoff(market):
    cfg, con = market
    every = calendar_events.calendar_events(cfg, con, CUTOFF, date(2026, 10, 7), date(2026, 11, 6))
    assert [(r["ticker"], r["date"]) for r in every if r["ticker"]] == [("DAL", "2026-10-09"), ("AAPL", "2026-10-29")]
    active = [r["ticker"] for r in company_records.shown_companies("us", CUTOFF)[0] if r["state"] == "active"]
    rows = calendar_events.calendar_events(cfg, con, CUTOFF, date(2026, 10, 7), date(2026, 11, 6), tickers=active)
    company = [r for r in rows if r["ticker"]]
    assert [(r["ticker"], r["date"]) for r in company] == [("AAPL", "2026-10-29")]
    assert company[0]["reaction_sessions"] == ["2026-10-29", "2026-10-30"]
    assert company[0]["widens"] == "company" and company[0]["event_id"] == "AAPL-earnings-2026-10-29"
    assert all(r["source"] == "config/events.yaml" for r in rows if r["major"])
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)


def test_lifecycle_and_commands_hide_deleted_company(market):
    _cfg, con = market
    shown, deleted = company_records.shown_companies("us", CUTOFF)
    tickers = {r["ticker"]: r["state"] for r in shown}
    assert deleted == {"PGR"} and "PGR" not in tickers
    assert tickers["DAL"] == "inactive" and tickers["JPM"] == "active"   # JPM's deactivation is recorded later
    events = company_records.lifecycle_rows(con, CUTOFF, set(tickers))
    assert [e["id"] for e in events] == ["we-us-DAL-deactivate-20261005T000000Z"]
    assert events[0]["recorded_at"] == "2026-10-05T00:00:00Z"
    commands = company_records.command_rows(con, CUTOFF, deleted)
    assert [c["id"] for c in commands] == ["cmd-1", "cmd-2"]             # read tools and later commands left out
    masked = commands[0]
    assert masked["arguments"] == {"market": "us", "ticker": "(deleted company)"}
    assert masked["idempotency_key"] == "(masked)" and masked["record_ids"] == ["(masked)"]
    assert "PGR" not in json.dumps(masked)
    assert commands[1]["message"] == "SPY is an ETF"


def test_inactive_news_since_deactivation():
    companies = [{"ticker": "DAL", "state": "inactive", "state_since": "2026-10-05T11:45:00Z"},
                 {"ticker": "AAPL", "state": "active", "state_since": "2024-10-07T00:00:00Z"}]
    items = [{"id": "a", "tickers": ["DAL"], "first_seen_at": "2026-10-06T00:00:00Z"},
             {"id": "b", "tickers": ["DAL"], "first_seen_at": "2026-10-04T00:00:00Z"},
             {"id": "c", "tickers": ["AAPL"], "first_seen_at": "2026-10-06T00:00:00Z"}]
    assert [i["id"] for i in company_records.inactive_news(items, companies)] == ["a"]
