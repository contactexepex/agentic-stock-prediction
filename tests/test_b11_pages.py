"""B11's page builders of batch 2 (marketbrief/warehouse/rm_news.py, rm_companies.py) on a small synthetic US store:
the News calendar spans the session being predicted and the 7 days after it for the active companies, and the
Companies page lists the active companies first, counts and masks a deleted company, keeps only the lifecycle events
of the companies shown, and carries the news of an inactive company first seen since it went inactive. The page shell
(B4's blocks) is replaced by a fake here; tests/test_api_contract.py checks the whole payloads."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.analytics.news_tags import TAG_VERSION  # noqa: E402
from marketbrief.core import database  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.warehouse import market_page_parts, rm_companies, rm_news  # noqa: E402
from marketbrief.warehouse.rm_registry import BuildContext  # noqa: E402

CUTOFF = datetime.fromisoformat("2026-10-07T12:00:00+00:00")
BEFORE = "2026-10-07T11:00:00+00:00"
SESSION = "2026-10-07"


def append(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / "us" / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def event(ticker: str, kind: str, recorded_at: str, key: str) -> dict:
    stamp = recorded_at[:19].replace("-", "").replace(":", "")
    return {"id": f"we-us-{ticker}-{kind}-{stamp}Z", "market": "us", "ticker": ticker, "event": kind,
            "effective_from": recorded_at, "recorded_at": recorded_at, "reason": "test",
            "requested_by": "dashboard:owner", "channel": "dashboard", "idempotency_key": key}


def news(news_id: str, first_seen: str, ticker: str, title: str) -> dict:
    return {"id": news_id, "title": title, "url": f"https://example.com/{news_id}", "source": "Example",
            "source_domain": "example.com", "published_at": first_seen, "first_seen_at": first_seen, "feed": "test",
            "category": "company", "tickers": [ticker], "primary_tickers": [ticker], "tag_version": TAG_VERSION}


def store(root: Path) -> None:
    append(root, "watchlist_events", "2026-10-05", [event("DAL", "deactivate", "2026-10-05T11:45:00+00:00", "d-1")])
    append(root, "watchlist_events", "2026-10-06", [event("PGR", "delete", "2026-10-06T00:00:00+00:00", "del-pgr")])
    append(root, "command_log", "2026-10-06", [{
        "id": "cmd-1", "market": "us", "received_at": "2026-10-06T00:00:00+00:00", "channel": "dashboard",
        "actor": "dashboard:owner", "agent": "dashboard", "tool": "delete_company", "kind": "write",
        "arguments": {"market": "us", "ticker": "PGR"}, "idempotency_key": "del-pgr", "result": "accepted",
        "message": "PGR deleted", "record_ids": ["we-us-PGR-delete-20261006T000000Z"]}])
    append(root, "news", "2026-10-07", [
        news("dal-after", BEFORE, "DAL", "Delta Air Lines adds routes"),
        news("dal-before", "2026-10-04T00:00:00+00:00", "DAL", "Delta Air Lines cuts fares"),
    ])
    append(root, "news_enriched", "2026-10-07", [
        {"id": item, "analyzed_at": BEFORE, "relevance": 0.8, "sentiment": 0.1, "novelty": 0.5, "materiality": "low",
         "event_type": "product", "urgency": "low", "geopolitical": False, "priced_in": False, "summary": None}
        for item in ("dal-after", "dal-before")])


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    root = tmp_path_factory.mktemp("b11pages")
    store(root)
    saved, mp = common.ROOT, pytest.MonkeyPatch()
    common.ROOT = root
    mp.setenv("MB_NOW", CUTOFF.isoformat())
    try:
        yield BuildContext(load_market("us"), database.connect("us"), CUTOFF)
    finally:
        common.ROOT = saved
        mp.undo()


def test_news_calendar_spans_the_session_and_seven_days(ctx, monkeypatch):
    seen = {}

    def fake_calendar(_cfg, _con, cutoff, first, last, tickers):
        seen.update(first=first, last=last, tickers=tickers, cutoff=cutoff)
        return []

    monkeypatch.setattr(rm_news, "session_date", lambda _ctx: SESSION)
    monkeypatch.setattr(rm_news, "calendar_events", fake_calendar)
    rm_news.calendar(ctx)
    assert (seen["first"], seen["last"]) == (date(2026, 10, 7), date(2026, 10, 14))
    assert "DAL" not in seen["tickers"] and "AAPL" in seen["tickers"] and seen["cutoff"] == CUTOFF


def test_companies_page(ctx, monkeypatch):
    def fake_companies(context, fields):
        records = [{**company, "open_trades": 0} for company in context.companies]
        return [market_page_parts.pick(record, fields) for record in records]

    monkeypatch.setattr(rm_companies, "shell", lambda _ctx: {"market": "us"})
    monkeypatch.setattr(rm_companies, "companies", fake_companies)
    page = rm_companies.companies_pages(ctx)["_"]
    states = [row["state"] for row in page["companies"]]
    assert states == sorted(states, key=lambda state: state != "active")       # active first
    tickers = [row["ticker"] for row in page["companies"]]
    assert "PGR" not in tickers and "DAL" in tickers and page["deleted_count"] == 1
    assert page["default_amount"] == 1000.0
    assert [e["ticker"] for e in page["lifecycle"]] == ["DAL"]                  # PGR's delete event is left out
    assert page["commands"][0]["arguments"] == {"market": "us", "ticker": "(deleted company)"}
    assert "PGR" not in json.dumps(page["commands"])
    assert [item["id"] for item in page["news_inactive"]] == ["dal-after"]   # first seen since DAL went inactive
    assert set(page["news_inactive"][0]) == {"id", "market", "tickers", "primary_tickers", "title", "source",
                                             "published_at", "first_seen_at", "status", "enrichment"}
