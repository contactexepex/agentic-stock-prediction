"""News mockup (docs/SPEC.md section 6, page 9): the last three days of news, the market movers first.

    python design/mockups/09-news/build.py [--out DIR]

The owner's rules (2026-10-08): nothing older than 3 days; the last 24 hours first; a band of at most 10 items that
move the whole market (rates, results, commodities, index moves, geopolitics); then the rest of the window newest
first with pagination, at most 50 items shown, 10 a page; each item = headline + one or two lines + a link to the
original article, never the stored text; a right rail with the calendar and the news per company. Payload from the
catalogue's News items, Calendar events, Companies and the shell's market status and go-live state. Deterministic.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "scoreboard_row", "news_item", "calendar_event", "company")
REFERENCE_STRATEGY = "rule.model_news.v1"
NEWS_WINDOW_DAYS = 3          # owner decision 2026-10-08: nothing older than 3 days is shown
NEWS_MAX_ITEMS = 50           # owner decision: at most 50 items in the feed
CALENDAR_DAYS = 7             # the rail: the coming week
NEWS_FIELDS = ("id", "market", "tickers", "primary_tickers", "title", "source", "source_domain", "url", "published_at",
               "first_seen_at", "status", "status_as_of", "independent_origins", "primary_ids", "cluster_id")
ENRICHMENT_FIELDS = ("event_type", "materiality", "sentiment", "relevance", "novelty", "urgency", "priced_in", "analyzed_at")
EVENT_FIELDS = ("market", "date", "type", "name", "ticker", "timing", "reaction_sessions", "major", "widens", "provisional",
                "release", "source", "event_id")
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state", "open_trades")


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    cut = parse(cutoff)
    window_start = (cut - timedelta(days=NEWS_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # the window: first seen at or before the cut-off (never later: no look-ahead) and within the last 3 days;
    # newest first; at most NEWS_MAX_ITEMS
    in_window = [r for r in files["news_item"]["records"]
                 if r["market"] == market and window_start < r["first_seen_at"] <= cutoff]
    older = sum(1 for r in files["news_item"]["records"] if r["market"] == market and r["first_seen_at"] <= window_start)
    news = []
    for r in sorted(in_window, key=lambda r: (r["first_seen_at"], r["id"]), reverse=True)[:NEWS_MAX_ITEMS]:
        rec = pick(r, NEWS_FIELDS)
        rec["enrichment"] = pick(r["enrichment"], ENRICHMENT_FIELDS)
        news.append(rec)
    session_date = status["session"]["session_date"]
    calendar_end = (datetime.fromisoformat(session_date) + timedelta(days=CALENDAR_DAYS)).date().isoformat()
    calendar = sorted((pick(r, EVENT_FIELDS) for r in files["calendar_event"]["records"]
                       if r["market"] == market and session_date <= r["date"] <= calendar_end),
                      key=lambda r: (r["date"], not r["major"], r["name"]))
    companies = sorted((pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market),
                       key=lambda r: r["ticker"])
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "window": {"days": NEWS_WINDOW_DAYS, "from": window_start, "to": cutoff, "max_items": NEWS_MAX_ITEMS,
                   "stored_in_window": len(in_window), "older_hidden": older},
        "news": news,
        "calendar": calendar, "calendar_days": CALENDAR_DAYS,
        "companies": companies,
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    data = envelope("news", "docs/SPEC.md section 6, page 9; owner's rules of 2026-10-08", "GET /api/v1/markets/{market}/news",
                    "rm.news", NAMES, cutoff, markets)
    data["_data_requests"] = [
        "market-wide news items (no ticker; scope market; rates, CPI/jobs, commodities, geopolitics, index moves anywhere) "
        "with a region, a one-or-two-line summary per item (the stored key sentences where the page was read), about 30 "
        "items per market in the 3-day window with at least 12 in the last 24 hours and the full mix of statuses, and if "
        "cheap an engine-side market_moving flag: sent to W1 as data request 8 on 2026-10-08; until then the page ranks "
        "the movers itself (market-wide first, then watchlist results, then high materiality, then newest) and shows "
        "the headline without a summary line",
    ]
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"news {len(p['news'])} of {p['window']['stored_in_window']} in the window "
                                  f"({p['window']['older_hidden']} older hidden), calendar {len(p['calendar'])}, "
                                  f"companies {len(p['companies'])}")
