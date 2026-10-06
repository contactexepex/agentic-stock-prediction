#!/usr/bin/env python3
"""Collect recent SEC filings for watchlist tickers from SEC EDGAR's free JSON endpoints
into data/<market>/filings/YYYY/MM/<today>.jsonl. Only for markets with `filings: sec`.
SEC requires a descriptive User-Agent with contact info: set
SEC_USER_AGENT="your-name your@email.com". Non-SEC-registered tickers are skipped.
A ticker's filings are those of its mapped CIK plus its predecessor/related CIKs
(`fundamentals.predecessor_ciks`), each accession once; `cik` and `url` name the CIK listing it.
Requests go through scripts/sec.py (one throttle, backoff on 429/503, offline fixtures for tests);
if SEC still refuses, the JSON summary lists what failed and the exit code is 1 (non-fatal for
the routine), never a bare traceback."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

from common import append_jsonl, day_file, market_arg, recent_ids, require_market, utc_now, utc_today

from sec import Edgar, related_ciks, ticker_submissions, time_summary

# SEC renamed beneficial-ownership forms "SCHEDULE 13D/13G" (structured XML) in Dec 2024; keep both.
DEFAULT_FORMS = ["8-K", "10-Q", "10-K", "6-K", "20-F", "4", "SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G"]


def main() -> int:
    watchlist = require_market(market_arg(__doc__).parse_args())
    market = watchlist["market"]
    if watchlist.get("filings") != "sec":
        print(json.dumps({"collector": "filings", "market": market, "skipped": "no SEC filings for this market"}))
        return 0
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        print(json.dumps({"collector": "filings", "error": "SEC_USER_AGENT not set"}))
        return 1
    forms = set(watchlist.get("filing_forms", DEFAULT_FORMS))
    since = utc_today() - timedelta(days=int(watchlist.get("filing_lookback_days", 7)))
    seen = recent_ids(market, "filings", days=60)
    now = utc_now()

    edgar = Edgar(ua)
    try:
        cik_by_ticker = edgar.cik_map()
    except Exception as exc:  # SEC refused even after backoff: report, don't crash
        print(json.dumps({"collector": "filings", "market": market, "new_filings": 0,
                          "failed": [{"url": "company_tickers.json", "error": str(exc)[:200]}]}, indent=2))
        return 1

    related = related_ciks(watchlist)
    rows, skipped, failed, unanswered = [], [], [], 0
    for ticker, meta in watchlist["tickers"].items():
        cik = cik_by_ticker.get(meta.get("sec_ticker", ticker).upper())
        if cik is None:
            skipped.append(ticker)
            continue
        # the mapped CIK plus the ticker's predecessor/related CIKs, de-duplicated by accession
        recent, errors = ticker_submissions(edgar, ticker, cik, related)
        failed += errors
        if recent is None:
            unanswered += 1
            continue
        for i, acc in enumerate(recent["accessionNumber"]):
            form, filed = recent["form"][i], recent["filingDate"][i]
            if form not in forms or date.fromisoformat(filed) < since or acc in seen:
                continue
            doc, src = recent["primaryDocument"][i], recent["cik"][i]   # src: the CIK listing the filing
            rows.append({
                "id": acc, "ticker": ticker, "cik": str(src), "form": form, "filing_date": filed,
                "accepted_at": recent["acceptanceDateTime"][i] or None,
                "description": recent["primaryDocDescription"][i] or form,
                "url": f"https://www.sec.gov/Archives/edgar/data/{src}/{acc.replace('-', '')}/{doc}",
                "first_seen_at": now,
            })
            seen.add(acc)

    written = append_jsonl(day_file(market, "filings", utc_today()), rows)
    print(json.dumps({"collector": "filings", "market": market, "new_filings": written,
                      "skipped_not_sec": skipped, "failed": failed, "requests": edgar.requests,
                      "sec_times": time_summary(edgar)}, indent=2))
    return 1 if unanswered and unanswered == len(watchlist["tickers"]) - len(skipped) else 0


if __name__ == "__main__":
    sys.exit(main())
