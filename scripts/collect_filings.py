#!/usr/bin/env python3
"""Collect recent SEC filings for watchlist tickers from SEC EDGAR's free JSON endpoints
into data/<market>/filings/YYYY/MM/<today>.jsonl. Only for markets with `filings: sec`.
SEC requires a descriptive User-Agent with contact info: set
SEC_USER_AGENT="your-name your@email.com". Non-SEC-registered tickers are skipped."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import date, timedelta

from common import append_jsonl, day_file, market_arg, recent_ids, require_market, utc_now, utc_today

DEFAULT_FORMS = ["8-K", "10-Q", "10-K", "6-K", "20-F", "4", "SC 13D", "SC 13G"]


def get_json(url: str, ua: str):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


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

    tickmap = get_json("https://www.sec.gov/files/company_tickers.json", ua)
    cik_by_ticker = {v["ticker"].upper(): int(v["cik_str"]) for v in tickmap.values()}

    rows, skipped, failed = [], [], []
    for ticker, meta in watchlist["tickers"].items():
        cik = cik_by_ticker.get(meta.get("sec_ticker", ticker).upper())
        if cik is None:
            skipped.append(ticker)
            continue
        try:
            recent = get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", ua)["filings"]["recent"]
        except Exception as exc:
            failed.append({"ticker": ticker, "error": str(exc)[:200]})
            continue
        time.sleep(0.2)  # stay well under SEC's 10 requests/second limit
        for i, acc in enumerate(recent["accessionNumber"]):
            form, filed = recent["form"][i], recent["filingDate"][i]
            if form not in forms or date.fromisoformat(filed) < since or acc in seen:
                continue
            doc = recent["primaryDocument"][i]
            rows.append({
                "id": acc, "ticker": ticker, "cik": str(cik), "form": form, "filing_date": filed,
                "accepted_at": recent["acceptanceDateTime"][i] or None,
                "description": recent["primaryDocDescription"][i] or form,
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}",
                "first_seen_at": now,
            })
            seen.add(acc)

    written = append_jsonl(day_file(market, "filings", utc_today()), rows)
    print(json.dumps({"collector": "filings", "market": market, "new_filings": written,
                      "skipped_not_sec": skipped, "failed": failed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
