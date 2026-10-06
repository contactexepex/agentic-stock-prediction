#!/usr/bin/env python3
"""Collect daily OHLCV bars via yfinance (free, unofficial Yahoo Finance access; personal use)
for a market's tickers and market-level symbols (benchmark, vol index, cues, factors) into
data/<market>/prices/YYYY/MM/<trading-date>.csv. One file per trading date; a bar is written
once. Today's bar (UTC) is skipped because it may be incomplete.
First run: --period 2y (needed for 1-year beta and the range backtest).
A symbol is listed in `failed` when Yahoo returns nothing, no completed bar, or only stale bars:
the newest completed bar is older than the market's previous session (its stocks, benchmark, vol
index and sector indices) or than STALE_DAYS calendar days (cues and factors on other exchanges).
Stale bars are still stored; the entry says how old the newest one is.

Official fallback (markets with `price_fallback: {source: nse_bhavcopy}`, i.e. India): after the
Yahoo pass, every watchlist stock (`tickers`, not indices, cues or factors) that has no stored bar
for one of the last `price_fallback.sessions` completed sessions of the exchange calendar gets
that day's open, high, low, close and volume from NSE's security-wise bhavcopy
(nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv, series EQ; the file
is used only when its DATE1 is that session). Bhavcopy prices are unadjusted like the stored
Yahoo `close`; `adj_close` is set to the close. The prices CSV keeps its columns (a source column
would break the fixed-column reader), so the source of each such bar is in the summary:
`filled_from_nse` lists every bar written from the bhavcopy. A watchlist stock that Yahoo failed
(stale, empty, error) but whose checked sessions are all stored after the fallback moves from
`failed` to `resolved_by_nse`, with Yahoo's error and `filled_dates` (this run's NSE fills; empty
when an earlier run already stored them). A stock still missing a session afterwards stays in
`failed` with `missing_after_nse`; a gap Yahoo did not flag is added there too. A bar is never
overwritten: Yahoo is asked first, and the fallback only writes a (date, ticker) no file holds yet."""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

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


def stored_tickers(path: Path) -> set[str]:
    """Tickers that already have a bar in one prices day file."""
    if not path.exists():
        return set()
    return {r["ticker"] for r in csv.DictReader(io.StringIO(path.read_text())) if r.get("ticker")}


def write_bar(path: Path, row: list) -> None:
    new = not path.exists() or not path.read_text()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(FIELDS)
        w.writerow(row)


# ---------- NSE bhavcopy fallback (India) ----------

def recent_sessions(cfg: dict, today: date, n: int) -> list[date]:
    """The last `n` completed sessions before UTC `today`, oldest first."""
    out, d = [], today
    for _ in range(n):
        d = ev.prev_session(cfg, d, include=False)
        out.append(d)
    return out[::-1]


def nse_client(cfg: dict):
    """The NSE archive client (tests replace it with a replay client)."""
    from nse import Nse
    rel = cfg.get("relations") or {}
    return Nse(rel.get("base", "https://www.nseindia.com"), rel.get("archives", "https://nsearchives.nseindia.com"),
               pause=float(rel.get("pause_seconds", 0.7)))


def bhavcopy_bars(text: str, day: date, symbols: dict[str, str]) -> tuple[dict[str, dict], str | None]:
    """Watchlist bars (series EQ) of one sec_bhavdata_full file -> ({ticker: bar}, problem).
    A file whose DATE1 is not `day` (NSE serves the previous session's file on a holiday) gives
    no bars and a problem."""
    from nse import num, parse_day
    rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]
    served = {parse_day(r.get("DATE1")) for r in rows} - {None}
    if served != {day}:
        held = ", ".join(sorted(map(str, served))) or "no dated rows"
        return {}, f"bhavcopy for {day} holds {held}; not used"
    out = {}
    for r in rows:
        ticker = symbols.get(r.get("SYMBOL", "").upper())
        if not ticker or r.get("SERIES") != "EQ":
            continue
        o, h, lo, c = (num(r.get(k)) for k in ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE"))
        vol = num(r.get("TTL_TRD_QNTY"))
        if None in (o, h, lo, c, vol) or min(o, h, lo, c) <= 0 or not lo <= min(o, c) <= max(o, c) <= h:
            continue
        out[ticker] = {"open": o, "high": h, "low": lo, "close": c, "volume": int(vol)}
    return out, None


def nse_fallback(cfg: dict, today: date, now: str, n_sessions: int, nse=None) -> tuple[list[dict], dict, list[str]]:
    """Fill missing watchlist bars of the last `n_sessions` sessions from the NSE bhavcopy.
    Returns (filled bars, {ticker: sessions still missing}, notes)."""
    from nse import FetchError, nse_symbols
    symbols = nse_symbols(cfg)
    missing = {}
    for d in recent_sessions(cfg, today, n_sessions):
        have = stored_tickers(day_file(cfg["market"], "prices", d, "csv"))
        lacking = [t for t in cfg["tickers"] if t not in have]
        if lacking:
            missing[d] = lacking
    filled, notes = [], []
    if not missing:
        return filled, {}, notes
    nse = nse or nse_client(cfg)
    for d, lacking in missing.items():
        url = f"/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
        try:
            bars, problem = bhavcopy_bars(nse.text(url), d, symbols)
        except FetchError as exc:
            notes.append(f"nse bhavcopy {d}: {exc.error[:120]}")
            if exc.host:          # the proxy refuses the host: every other file fails the same way
                break
            continue
        if problem:
            notes.append(f"nse {problem}")
            continue
        path = day_file(cfg["market"], "prices", d, "csv")
        for t in lacking:
            bar = bars.get(t)
            if bar is None:
                notes.append(f"nse bhavcopy {d}: no EQ row for {t}")
                continue
            if t in stored_tickers(path):  # never a second bar for a (date, ticker)
                continue
            write_bar(path, [d.isoformat(), t, bar["open"], bar["high"], bar["low"], bar["close"], bar["close"],
                             bar["volume"], now])
            filled.append({"ticker": t, "date": d.isoformat(), **bar, "source": "nse_bhavcopy",
                           "url": f"https://nsearchives.nseindia.com{url}"})
    done = {(b["date"], b["ticker"]) for b in filled}
    still = {}
    for d, lacking in missing.items():
        for t in lacking:
            if (d.isoformat(), t) not in done:
                still.setdefault(t, []).append(d.isoformat())
    return filled, still, notes


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
            if key in stored_tickers(path):
                continue
            close = float(row["Close"])
            adj = float(row["Adj Close"]) if "Adj Close" in row else close
            vol = int(row["Volume"]) if row["Volume"] == row["Volume"] else 0
            write_bar(path, [d.isoformat(), key, round(float(row["Open"]), 4),
                             round(float(row["High"]), 4), round(float(row["Low"]), 4),
                             round(close, 4), round(adj, 4), vol, now])
            written += 1

    summary = {"collector": "prices", "market": cfg["market"], "symbols": len(targets), "new_bars": written}
    fb = cfg.get("price_fallback") or {}
    if fb.get("source") == "nse_bhavcopy":
        try:
            filled, still, notes = nse_fallback(cfg, today, now, int(fb.get("sessions", 5)))
        except Exception as exc:  # the fallback must never cost the Yahoo bars already written
            filled, still, notes = [], {}, [f"nse fallback error: {str(exc)[:200]}"]
        # a Yahoo failure for a stock whose recent sessions are now all stored is no gap any more
        resolved = [{**f, "filled_dates": [b["date"] for b in filled if b["ticker"] == f["ticker"]]}
                    for f in failed if f["ticker"] in cfg["tickers"] and f["ticker"] not in still]
        failed = [f for f in failed if not (f["ticker"] in cfg["tickers"] and f["ticker"] not in still)]
        for f in failed:
            if f["ticker"] in still:
                f["missing_after_nse"] = still[f["ticker"]]
        for t, days in still.items():   # a gap Yahoo did not flag (e.g. an older session) is listed too
            if not any(f["ticker"] == t for f in failed):
                failed.append({"ticker": t, "yahoo": targets[t], "error": "missing sessions after NSE fallback",
                               "missing_after_nse": days})
        summary.update({"filled_from_nse": filled, "resolved_by_nse": resolved, "nse_notes": notes})
    summary["failed"] = failed
    print(json.dumps(summary, indent=2))
    return 1 if failed and len(failed) == len(targets) else 0


if __name__ == "__main__":
    sys.exit(main())
