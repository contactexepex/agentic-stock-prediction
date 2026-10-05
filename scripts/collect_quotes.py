#!/usr/bin/env python3
"""Snapshot the latest price of overnight / pre-open cues into
data/<market>/quotes/YYYY/MM/<today>.jsonl: benchmark, vol index, cue and factor symbols,
the ADRs of watchlist tickers, and (if `premarket_quotes: true`) every watchlist ticker's
pre-market price. change_pct = latest price vs the previous regular-session close."""
from __future__ import annotations

import json
import sys

from common import append_jsonl, day_file, market_arg, require_market, utc_now, utc_today

ROLES = ("benchmark", "vol_index", "cue", "factor")


def targets(cfg: dict) -> dict[str, str]:
    out = {k: v["yahoo"] for k, v in cfg["symbols"].items() if v.get("role") in ROLES}
    for key, meta in cfg["tickers"].items():
        if meta.get("adr"):
            out[f"{key}:ADR"] = meta["adr"]
        if cfg.get("premarket_quotes"):
            out[key] = meta["yahoo"]
    return out


def snapshot(yf, symbol: str) -> dict:
    t = yf.Ticker(symbol)
    intraday = t.history(period="5d", interval="5m", prepost=True)
    daily = t.history(period="1mo", interval="1d")
    if intraday.empty or daily.empty:
        raise ValueError("no data")
    last_ts = intraday.index[-1]
    session_day = last_ts.tz_convert(daily.index.tz).date() if daily.index.tz else last_ts.date()
    prior = daily[[d.date() < session_day for d in daily.index]]
    if prior.empty:
        raise ValueError("no previous close")
    price, prev = float(intraday["Close"].iloc[-1]), float(prior["Close"].iloc[-1])
    return {"ts": last_ts.tz_convert("UTC").isoformat(), "price": round(price, 4),
            "prev_close": round(prev, 4), "change_pct": round(price / prev - 1, 6)}


def main() -> int:
    args = market_arg(__doc__).parse_args()
    cfg = require_market(args)
    import yfinance as yf

    now, rows, failed = utc_now(), [], []
    todo = targets(cfg)
    for key, symbol in todo.items():
        try:
            rows.append({"symbol": key, "yahoo": symbol, **snapshot(yf, symbol), "collected_at": now})
        except Exception as exc:
            failed.append({"symbol": key, "yahoo": symbol, "error": str(exc)[:200]})
    written = append_jsonl(day_file(cfg["market"], "quotes", utc_today()), rows)
    print(json.dumps({"collector": "quotes", "market": cfg["market"], "symbols": len(todo),
                      "written": written, "failed": failed}, indent=2))
    return 1 if todo and not rows else 0


if __name__ == "__main__":
    sys.exit(main())
