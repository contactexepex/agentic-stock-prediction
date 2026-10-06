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
is used only when its DATE1 is that session), oldest session first. `adj_close` is set to the close.
Price basis: yfinance's `Close` (auto_adjust=False) is not dividend-adjusted but IS split/bonus-
adjusted as of the collection time, so a stored bar collected after a split or bonus is on the
post-event basis (HDFCBANK 2025-08-22, stored after its 1:1 bonus: close 982.3, volume 19,833,502;
NSE's bhavcopy: 1964.60 and 9,916,751). The bhavcopy is as traded. A bhavcopy bar is therefore
written only when NSE's PREV_CLOSE is within 0.5% of our stored close of the previous session and
the Yahoo frame shows no split or bonus after that session; otherwise it is skipped with a note.
A bar is never overwritten: Yahoo is asked first, and the fallback only writes a (date, ticker)
no file holds yet. The prices CSV keeps its columns (a source column would break the
fixed-column reader); each filled bar gets a row in data/<market>/price_sources/ (view
`bar_sources`) and is listed in the summary's `filled_from_nse`. A watchlist stock that Yahoo
failed (stale, empty, error) moves from `failed` to `resolved_by_nse` (Yahoo's error plus
`filled_dates`, this run's fills, empty when an earlier run stored them) only when every checked
session is stored afterwards and its newest bar before the fallback was no more than `sessions`
sessions behind. Otherwise it stays in `failed` with `missing_after_nse` (date and reason) and/or
`newest_stored_bar` and `sessions_behind`; a gap Yahoo did not flag is added there too."""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import events as ev
from common import STALE_DAYS, append_jsonl, day_file, market_arg, require_market, utc_now, utc_today

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


def stored_bars(path: Path) -> dict[str, dict]:
    """{ticker: row} of the bars in one prices day file (a later row for a ticker wins)."""
    if not path.exists():
        return {}
    return {r["ticker"]: r for r in csv.DictReader(io.StringIO(path.read_text())) if r.get("ticker")}


def write_bar(path: Path, row: list) -> None:
    new = not path.exists() or not path.read_text()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(FIELDS)
        w.writerow(row)


# ---------- NSE bhavcopy fallback (India) ----------

PREV_CLOSE_TOLERANCE = 0.005   # bhavcopy PREV_CLOSE vs our stored close of the previous session
NEWEST_LOOKBACK = 40           # sessions searched back for a stock's newest stored bar


def recent_sessions(cfg: dict, today: date, n: int) -> list[date]:
    """The last `n` completed sessions before UTC `today`, oldest first."""
    out, d = [], today
    for _ in range(n):
        d = ev.prev_session(cfg, d, include=False)
        out.append(d)
    return out[::-1]


def newest_stored(cfg: dict, ticker: str, today: date) -> tuple[date | None, int]:
    """(date of the newest stored bar, sessions after it up to the previous session) for one stock,
    searching NEWEST_LOOKBACK sessions back; (None, NEWEST_LOOKBACK) when none is found."""
    d = today
    for behind in range(NEWEST_LOOKBACK):
        d = ev.prev_session(cfg, d, include=False)
        if ticker in stored_bars(day_file(cfg["market"], "prices", d, "csv")):
            return d, behind
    return None, NEWEST_LOOKBACK


def nse_client(cfg: dict):
    """The NSE archive client (tests replace it with a replay client)."""
    from nse import Nse
    rel = cfg.get("relations") or {}
    return Nse(rel.get("base", "https://www.nseindia.com"), rel.get("archives", "https://nsearchives.nseindia.com"),
               pause=float(rel.get("pause_seconds", 0.7)))


def bhavcopy_bars(text: str, day: date, symbols: dict[str, str]) -> tuple[dict[str, dict], str | None]:
    """Watchlist bars (series EQ) of one sec_bhavdata_full file -> ({ticker: bar}, problem).
    A file whose DATE1 is not `day` (NSE serves the previous session's file on a holiday) gives
    no bars and a problem. Each bar carries NSE's PREV_CLOSE for the corporate-action guard."""
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
        out[ticker] = {"open": o, "high": h, "low": lo, "close": c, "volume": int(vol),
                       "prev_close": num(r.get("PREV_CLOSE"))}
    return out, None


def basis_problem(cfg: dict, ticker: str, d: date, bar: dict, splits: list[date]) -> str | None:
    """Why a bhavcopy bar may be on another price basis than our stored bars, or None.
    Stored Yahoo bars are split/bonus-adjusted as of their collection time; the bhavcopy is as
    traded. So the bar is used only when NSE's PREV_CLOSE matches our stored close of the
    previous session (within PREV_CLOSE_TOLERANCE) and Yahoo reports no split or bonus after it."""
    prev = ev.prev_session(cfg, d, include=False)
    after = sorted(s for s in splits if s > prev)
    if after:
        return f"Yahoo reports a split/bonus on {after[0]}; price basis may differ"
    row = stored_bars(day_file(cfg["market"], "prices", prev, "csv")).get(ticker)
    if row is None:
        return f"no stored close for the previous session {prev} to check the price basis"
    stored, nse_prev = float(row["close"]), bar.get("prev_close")
    if not nse_prev or stored <= 0:
        return f"bhavcopy has no PREV_CLOSE to check the price basis against {prev}"
    gap = nse_prev / stored - 1
    if abs(gap) > PREV_CLOSE_TOLERANCE:
        return (f"price basis mismatch: bhavcopy PREV_CLOSE {nse_prev:g} vs stored close {stored:g} on {prev} "
                f"({gap:+.1%}); split, bonus or other corporate action")
    return None


def nse_fallback(cfg: dict, today: date, now: str, n_sessions: int, splits: dict[str, list[date]] | None = None,
                 nse=None) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    """Fill missing watchlist bars of the last `n_sessions` sessions from the NSE bhavcopy, oldest
    session first (a filled bar can then anchor the next session's basis check).
    Returns (filled bars, {ticker: [{date, reason}] still missing}, notes)."""
    from nse import FetchError, nse_symbols
    symbols, splits = nse_symbols(cfg), splits or {}
    missing = {}
    for d in recent_sessions(cfg, today, n_sessions):
        have = stored_bars(day_file(cfg["market"], "prices", d, "csv"))
        lacking = [t for t in cfg["tickers"] if t not in have]
        if lacking:
            missing[d] = lacking
    filled, still, notes = [], {}, []
    if not missing:
        return filled, still, notes
    nse = nse or nse_client(cfg)
    denied = None
    for d, lacking in missing.items():
        url = f"/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
        bars, problem = {}, denied
        if problem is None:
            try:
                bars, problem = bhavcopy_bars(nse.text(url), d, symbols)
                problem = f"nse {problem}" if problem else None
            except FetchError as exc:
                problem = f"nse bhavcopy {d}: {exc.error[:120]}"
                if exc.host:      # the proxy refuses the host: every other file fails the same way
                    denied = problem
            if problem:
                notes.append(problem)
        path = day_file(cfg["market"], "prices", d, "csv")
        for t in lacking:
            bar = bars.get(t)
            reason = problem or (None if bar else f"no EQ row for {t} in the bhavcopy")
            reason = reason or basis_problem(cfg, t, d, bar, splits.get(t, []))
            if reason:
                still.setdefault(t, []).append({"date": d.isoformat(), "reason": reason})
                if not problem:
                    notes.append(f"nse {d} {t}: {reason}; not filled")
                continue
            if t in stored_bars(path):  # never a second bar for a (date, ticker)
                continue
            write_bar(path, [d.isoformat(), t, bar["open"], bar["high"], bar["low"], bar["close"], bar["close"],
                             bar["volume"], now])
            full_url = f"https://nsearchives.nseindia.com{url}"
            append_jsonl(day_file(cfg["market"], "price_sources", d), [
                {"id": f"{d}-{t}", "date": d.isoformat(), "ticker": t, "source": "nse_bhavcopy", "url": full_url,
                 "filled_at": now}])
            filled.append({"ticker": t, "date": d.isoformat(), **{k: v for k, v in bar.items() if k != "prev_close"},
                           "source": "nse_bhavcopy", "url": full_url})
    return filled, still, notes


def apply_fallback(cfg: dict, today: date, now: str, targets: dict, failed: list[dict],
                   splits: dict[str, list[date]]) -> dict:
    """Run the NSE fallback and sort the Yahoo failures: a stock whose recent sessions are all
    stored afterwards moves to `resolved_by_nse`; one still missing a session, or whose newest
    stored bar (before the fallback) lies further back than the checked sessions, stays in `failed`."""
    n = int((cfg.get("price_fallback") or {}).get("sessions", 5))
    window_start = recent_sessions(cfg, today, n)[0]
    newest = {t: newest_stored(cfg, t, today) for t in cfg["tickers"]
              if any(f["ticker"] == t for f in failed)}
    try:
        filled, still, notes = nse_fallback(cfg, today, now, n, splits)
    except Exception as exc:  # the fallback must never cost the Yahoo bars already written
        filled, still, notes = [], {}, [f"nse fallback error: {str(exc)[:200]}"]
    resolved, keep = [], []
    for f in failed:
        t = f["ticker"]
        if t not in cfg["tickers"]:
            keep.append(f)
            continue
        if t in still:
            f["missing_after_nse"] = still[t]
        last, behind = newest.get(t, (None, 0))
        if last is None or behind > n:   # a gap older than the checked sessions: not closed
            f["newest_stored_bar"] = str(last) if last else f"none in the last {NEWEST_LOOKBACK} sessions"
            f["sessions_behind"] = behind
            f["beyond_nse_window"] = f"the fallback checks only sessions from {window_start}"
        if t in still or "beyond_nse_window" in f:
            keep.append(f)
        else:
            resolved.append({**f, "filled_dates": [b["date"] for b in filled if b["ticker"] == t]})
    for t, days in still.items():   # a gap Yahoo did not flag is listed too
        if not any(f["ticker"] == t for f in keep):
            keep.append({"ticker": t, "yahoo": targets[t], "error": "missing sessions after NSE fallback",
                         "missing_after_nse": days})
    failed[:] = keep
    return {"filled_from_nse": filled, "resolved_by_nse": resolved, "nse_notes": notes}


def yahoo_splits(df) -> list[date]:
    """Dates of the splits and bonus issues in a yfinance frame (column `Stock Splits`)."""
    if df is None or getattr(df, "empty", True) or "Stock Splits" not in df:
        return []
    return [idx.date() for idx, v in df["Stock Splits"].items() if v == v and v not in (0, 1)]


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--period", default="1mo", help="yfinance period, e.g. 1mo, 3mo, 1y, 2y")
    args = ap.parse_args()
    cfg = require_market(args)

    import yfinance as yf  # imported here so the rest of the repo works without it

    targets = {**{k: v["yahoo"] for k, v in cfg["symbols"].items()},
               **{k: v["yahoo"] for k, v in cfg["tickers"].items()}}
    now, today = utc_now(), utc_today()
    written, failed, splits = 0, [], {}

    for key, symbol in targets.items():
        try:
            df = yf.Ticker(symbol).history(period=args.period, interval="1d", auto_adjust=False)
        except Exception as exc:  # network or symbol errors must not stop other symbols
            failed.append({"ticker": key, "yahoo": symbol, "error": str(exc)[:200]})
            continue
        splits[key] = yahoo_splits(df)
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
            if key in stored_bars(path):
                continue
            close = float(row["Close"])
            adj = float(row["Adj Close"]) if "Adj Close" in row else close
            vol = int(row["Volume"]) if row["Volume"] == row["Volume"] else 0
            write_bar(path, [d.isoformat(), key, round(float(row["Open"]), 4),
                             round(float(row["High"]), 4), round(float(row["Low"]), 4),
                             round(close, 4), round(adj, 4), vol, now])
            written += 1

    summary = {"collector": "prices", "market": cfg["market"], "symbols": len(targets), "new_bars": written}
    if (cfg.get("price_fallback") or {}).get("source") == "nse_bhavcopy":
        summary.update(apply_fallback(cfg, today, now, targets, failed, splits))
    summary["failed"] = failed
    print(json.dumps(summary, indent=2))
    return 1 if failed and len(failed) == len(targets) else 0


if __name__ == "__main__":
    sys.exit(main())
