#!/usr/bin/env python3
"""Collect daily OHLCV bars via yfinance (free, unofficial Yahoo Finance access; personal use)
for a market's tickers and market-level symbols (benchmark, vol index, cues, factors) into
data/<market>/prices/YYYY/MM/<trading-date>.csv. One file per trading date; a bar is written
once. Today's bar (UTC) is skipped because it may be incomplete.
First run: --period 2y (needed for 1-year beta and the range backtest).
A symbol is listed in `failed` when Yahoo returns nothing, no completed bar, or only stale bars:
the newest completed bar is older than the market's previous session (its stocks, benchmark, vol
index and sector indices) or than STALE_DAYS calendar days (cues and factors on other exchanges).
Stale bars are still stored; the entry says how old the newest one is."""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta

import events as ev
from common import STALE_DAYS, day_file, market_arg, require_market, utc_now, utc_today

FIELDS = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "collected_at"]
OWN_EXCHANGE = ("benchmark", "vol_index", "sector_etf")   # roles that follow the market's calendar


def expected_bar(cfg: dict, key: str, today: date) -> date:
    """Oldest acceptable newest bar for a symbol on a run on UTC date `today`."""
    if key in cfg["tickers"] or cfg["symbols"].get(key, {}).get("role") in OWN_EXCHANGE:
        return ev.prev_session(cfg, today, include=False)
    return today - timedelta(days=STALE_DAYS)


def frame_error(cfg: dict, key: str, df, today: date) -> str | None:
    """Why a yfinance daily frame is no usable update (no data, no completed bar, stale), or None."""
    if df is None or df.empty:
        return "no data"
    done = [idx.date() for idx, row in df.iterrows()
            if idx.date() < today and not row.isna()[["Open", "High", "Low", "Close"]].any()]
    if not done:
        return "no completed bar"
    newest, expected = max(done), expected_bar(cfg, key, today)
    return f"stale: newest bar {newest}, expected {expected} or later" if newest < expected else None


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--period", default="1mo", help="yfinance period, e.g. 1mo, 3mo, 1y, 2y")
    args = ap.parse_args()
    cfg = require_market(args)

    import yfinance as yf  # imported here so the rest of the repo works without it

    targets = {**{k: v["yahoo"] for k, v in cfg["symbols"].items()},
               **{k: v["yahoo"] for k, v in cfg["tickers"].items()}}
    now, today = utc_now(), utc_today()
    written, failed = 0, []

    for key, symbol in targets.items():
        try:
            df = yf.Ticker(symbol).history(period=args.period, interval="1d", auto_adjust=False)
        except Exception as exc:  # network or symbol errors must not stop other symbols
            failed.append({"ticker": key, "yahoo": symbol, "error": str(exc)[:200]})
            continue
        error = frame_error(cfg, key, df, today)
        if error:
            failed.append({"ticker": key, "yahoo": symbol, "error": error})
            if not error.startswith("stale"):
                continue
        for idx, row in df.iterrows():
            d = idx.date()
            if d >= today or row.isna()[["Open", "High", "Low", "Close"]].any():
                continue
            path = day_file(cfg["market"], "prices", d, "csv")
            existing = path.read_text() if path.exists() else ""
            if f",{key}," in existing:
                continue
            with path.open("a", newline="") as f:
                w = csv.writer(f)
                if not existing:
                    w.writerow(FIELDS)
                close = float(row["Close"])
                adj = float(row["Adj Close"]) if "Adj Close" in row else close
                vol = int(row["Volume"]) if row["Volume"] == row["Volume"] else 0
                w.writerow([d.isoformat(), key, round(float(row["Open"]), 4),
                            round(float(row["High"]), 4), round(float(row["Low"]), 4),
                            round(close, 4), round(adj, 4), vol, now])
            written += 1

    print(json.dumps({"collector": "prices", "market": cfg["market"], "symbols": len(targets),
                      "new_bars": written, "failed": failed}, indent=2))
    return 1 if failed and len(failed) == len(targets) else 0


if __name__ == "__main__":
    sys.exit(main())
