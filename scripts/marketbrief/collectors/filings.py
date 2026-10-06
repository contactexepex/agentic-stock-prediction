"""Collect recent SEC filings for watchlist tickers from SEC EDGAR's free JSON endpoints
into data/<market>/filings/YYYY/MM/<today>.jsonl. Only for markets with `filings: sec`.
SEC requires a descriptive User-Agent with contact info: set
SEC_USER_AGENT="your-name your@email.com". Non-SEC-registered tickers are skipped.
A ticker's filings are those of its mapped CIK plus its predecessor/related CIKs
(`fundamentals.predecessor_ciks`), each accession once; `cik` and `url` name the CIK listing it.
Requests go through marketbrief/sources/sec_client.py (one throttle, backoff on 429/503, offline fixtures for
tests); if SEC still refuses, the JSON summary lists what failed and the exit code is 1 (non-fatal for
the routine), never a bare traceback."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.config_keys import (
    CFG_FILING_FORMS,
    CFG_FILING_LOOKBACK_DAYS,
    CFG_FILINGS,
    CFG_MARKET,
    CFG_SEC_TICKER,
    CFG_TICKERS,
    FILINGS_SOURCE_SEC,
)
from marketbrief.constants.environment import ENV_SEC_USER_AGENT
from marketbrief.constants.filings import (
    COLLECTOR_FILINGS,
    DEFAULT_FILING_FORMS,
    DEFAULT_LOOKBACK_DAYS,
    ERROR_TEXT_LIMIT,
    MSG_SKIPPED_NOT_SEC,
    MSG_TICKER_MAP_FILE,
    SEEN_LOOKBACK_DAYS,
)
from marketbrief.constants.messages import MSG_SEC_USER_AGENT_MISSING
from marketbrief.constants.kinds import KIND_FILINGS
from marketbrief.constants.statuses import (
    SUMMARY_COLLECTOR,
    SUMMARY_ERROR,
    SUMMARY_FAILED,
    SUMMARY_MARKET,
    SUMMARY_REQUESTS,
    SUMMARY_SKIPPED,
    SUMMARY_WARNINGS,
)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file, recent_ids
from marketbrief.sources.sec_acceptance import time_summary, time_warnings
from marketbrief.sources.sec_client import Edgar, archive_url
from marketbrief.sources.sec_filings import related_ciks, ticker_submissions


def filing_rows(recent: dict, ticker: str, forms: set[str], since: date, seen: set[str], now: str) -> list[dict]:
    """The new filing rows of one ticker's merged submissions: wanted forms, filed since `since`, not stored."""
    rows = []
    for index, accession in enumerate(recent["accessionNumber"]):
        form, filed = recent["form"][index], recent["filingDate"][index]
        if form not in forms or date.fromisoformat(filed) < since or accession in seen:
            continue
        document, listing_cik = recent["primaryDocument"][index], recent["cik"][index]  # the CIK listing the filing
        rows.append(
            {
                COL_ID: accession,
                COL_TICKER: ticker,
                "cik": str(listing_cik),
                "form": form,
                "filing_date": filed,
                "accepted_at": recent["acceptanceDateTime"][index] or None,
                "description": recent["primaryDocDescription"][index] or form,
                "url": archive_url(listing_cik, accession, document),
                "first_seen_at": now,
            }
        )
        seen.add(accession)
    return rows


def main() -> int:
    """Entry point of scripts/collect_filings.py."""
    watchlist = require_market(market_arg(__doc__).parse_args())
    market = watchlist[CFG_MARKET]
    if watchlist.get(CFG_FILINGS) != FILINGS_SOURCE_SEC:
        print(
            json.dumps(
                {SUMMARY_COLLECTOR: COLLECTOR_FILINGS, SUMMARY_MARKET: market, SUMMARY_SKIPPED: MSG_SKIPPED_NOT_SEC}
            )
        )
        return 0
    user_agent = os.environ.get(ENV_SEC_USER_AGENT)
    if not user_agent:
        print(json.dumps({SUMMARY_COLLECTOR: COLLECTOR_FILINGS, SUMMARY_ERROR: MSG_SEC_USER_AGENT_MISSING}))
        return 1
    forms = set(watchlist.get(CFG_FILING_FORMS, DEFAULT_FILING_FORMS))
    since = utc_today() - timedelta(days=int(watchlist.get(CFG_FILING_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS)))
    seen = recent_ids(market, KIND_FILINGS, days=SEEN_LOOKBACK_DAYS)
    now = utc_now()

    edgar = Edgar(user_agent)
    try:
        cik_by_ticker = edgar.cik_map()
    except Exception as exc:  # SEC refused even after backoff: report, don't crash
        print(
            json.dumps(
                {
                    SUMMARY_COLLECTOR: COLLECTOR_FILINGS,
                    SUMMARY_MARKET: market,
                    "new_filings": 0,
                    SUMMARY_FAILED: [{"url": MSG_TICKER_MAP_FILE, "error": str(exc)[:ERROR_TEXT_LIMIT]}],
                },
                indent=2,
            )
        )
        return 1

    related = related_ciks(watchlist)
    rows, skipped, failed, unanswered = [], [], [], 0
    for ticker, meta in watchlist[CFG_TICKERS].items():
        cik = cik_by_ticker.get(meta.get(CFG_SEC_TICKER, ticker).upper())
        if cik is None:
            skipped.append(ticker)
            continue
        # the mapped CIK plus the ticker's predecessor/related CIKs, de-duplicated by accession
        recent, errors = ticker_submissions(edgar, ticker, cik, related)
        failed += errors
        if recent is None:
            unanswered += 1
            continue
        rows += filing_rows(recent, ticker, forms, since, seen, now)

    written = append_jsonl(day_file(market, KIND_FILINGS, utc_today()), rows)
    print(
        json.dumps(
            {
                SUMMARY_COLLECTOR: COLLECTOR_FILINGS,
                SUMMARY_MARKET: market,
                "new_filings": written,
                "skipped_not_sec": skipped,
                SUMMARY_FAILED: failed,
                SUMMARY_REQUESTS: edgar.requests,
                "sec_times": time_summary(edgar),
                SUMMARY_WARNINGS: time_warnings(edgar),
            },
            indent=2,
        )
    )
    all_unanswered = unanswered and unanswered == len(watchlist[CFG_TICKERS]) - len(skipped)
    return 1 if all_unanswered else 0
