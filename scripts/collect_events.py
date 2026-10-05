#!/usr/bin/env python3
"""Collect upcoming company events (earnings, ex-dividend) for watchlist tickers via yfinance
into data/<market>/events/YYYY/MM/<today>.jsonl. Append-only: an event id
(<ticker>-<type>-<date>) is written once; a moved date is a new event id, and the newest
first_seen_at wins when reading (see the `company_events` view)."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime

from common import append_jsonl, day_file, market_arg, recent_ids, require_market, utc_now, utc_today

FIELDS = {"Earnings Date": "earnings", "Ex-Dividend Date": "ex_dividend"}


def as_dates(value) -> list[date]:
    values = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for v in values:
        if isinstance(v, datetime):
            out.append(v.date())
        elif isinstance(v, date):
            out.append(v)
        elif hasattr(v, "date"):
            out.append(v.date())
    return out


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    import yfinance as yf

    market, now, today = cfg["market"], utc_now(), utc_today()
    seen = recent_ids(market, "events", days=400)
    rows, failed = [], []
    for key, meta in cfg["tickers"].items():
        try:
            cal = yf.Ticker(meta["yahoo"]).calendar or {}
        except Exception as exc:
            failed.append({"ticker": key, "error": str(exc)[:200]})
            continue
        for field, etype in FIELDS.items():
            for d in as_dates(cal.get(field)):
                eid = f"{key}-{etype}-{d}"
                if d < today or eid in seen:
                    continue
                name = "Earnings" if etype == "earnings" else "Ex-dividend"
                rows.append({"id": eid, "date": d.isoformat(), "type": etype, "ticker": key,
                             "name": f"{meta['name']} {name.lower()}", "source": "yfinance",
                             "first_seen_at": now})
                seen.add(eid)
    written = append_jsonl(day_file(market, "events", today), rows)
    print(json.dumps({"collector": "events", "market": market, "new_events": written,
                      "failed": failed}, indent=2))
    return 1 if failed and len(failed) == len(cfg["tickers"]) else 0


if __name__ == "__main__":
    sys.exit(main())
