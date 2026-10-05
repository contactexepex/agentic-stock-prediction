#!/usr/bin/env python3
"""Collect daily OHLCV bars via yfinance (free, unofficial Yahoo Finance access; personal use)
into data/prices/YYYY/MM/<trading-date>.csv. One file per trading date; a bar is written once.
Today's bar is skipped because it may be incomplete. Use --period 3mo on the first run to backfill."""
from __future__ import annotations

import argparse
import csv
import json
import sys

import yaml

from common import CONFIG, day_file, utc_now, utc_today

FIELDS = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "collected_at"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="1mo", help="yfinance period, e.g. 1mo, 3mo, 1y")
    args = ap.parse_args()

    import yfinance as yf  # imported here so the rest of the repo works without it

    watchlist = yaml.safe_load((CONFIG / "watchlist.yaml").read_text())
    now, today = utc_now(), utc_today()
    written, failed = 0, []

    for ticker, meta in watchlist["tickers"].items():
        symbol = meta.get("yahoo", ticker)
        try:
            df = yf.Ticker(symbol).history(period=args.period, interval="1d", auto_adjust=False)
        except Exception as exc:  # network or symbol errors must not stop other tickers
            failed.append({"ticker": ticker, "error": str(exc)[:200]})
            continue
        if df is None or df.empty:
            failed.append({"ticker": ticker, "error": "no data"})
            continue
        for idx, row in df.iterrows():
            d = idx.date()
            if d >= today:
                continue
            path = day_file("prices", d, "csv")
            existing = path.read_text() if path.exists() else ""
            if f",{ticker}," in existing:
                continue
            with path.open("a", newline="") as f:
                w = csv.writer(f)
                if not existing:
                    w.writerow(FIELDS)
                close = float(row["Close"])
                adj = float(row["Adj Close"]) if "Adj Close" in row else close
                w.writerow([d.isoformat(), ticker, round(float(row["Open"]), 4),
                            round(float(row["High"]), 4), round(float(row["Low"]), 4),
                            round(close, 4), round(adj, 4), int(row["Volume"]), now])
            written += 1

    print(json.dumps({"collector": "prices", "new_bars": written, "failed": failed}, indent=2))
    return 1 if failed and len(failed) == len(watchlist["tickers"]) else 0


if __name__ == "__main__":
    sys.exit(main())
