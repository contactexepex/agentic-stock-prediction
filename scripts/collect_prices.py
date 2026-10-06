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
`newest_stored_bar` and `sessions_behind`; a gap Yahoo did not flag is added there too.

Splits and bonus issues (issue #31, both markets; detect_adjustments, scripts/adjust.py): before a
symbol's new bars are written, Yahoo's frame (today's basis) is compared with our stored bars of
the same dates. A `Stock Splits` row whose stored bars before it sit on the old basis is recorded
once in data/<market>/adjustments/ (summary `adjustments`) and applied on read by the ohlc and bars
views; for India a re-base with no split row can be confirmed from NSE's bhavcopies instead (which
also finds the ex-date after a missed run). Any other mismatch above 2% goes to `warnings` and is
never recorded; when it is a re-base or a split row no source confirms, the symbol's new bars are
held (`held`, `failed`) on every run until a later run can record it (a frame that no longer
covers our stored bars is refetched from before the newest one, so the check keeps its overlap). An older bar Yahoo serves after a recorded
split is written on its date's stored basis (`rebased_bars`), and a recorded split no longer
blocks the bhavcopy fallback."""
from __future__ import annotations

import csv
import io
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import adjust as adj
import events as ev
from marketbrief.constants.collection import STALE_DAYS
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.paths import data_dir
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.utils.sessions import last_completed_sessions

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
    from marketbrief.sources.nse_client import Nse
    rel = cfg.get("relations") or {}
    return Nse(rel.get("base", "https://www.nseindia.com"), rel.get("archives", "https://nsearchives.nseindia.com"),
               pause=float(rel.get("pause_seconds", 0.7)))


def bhavcopy_bars(text: str, day: date, symbols: dict[str, str]) -> tuple[dict[str, dict], str | None]:
    """Watchlist bars (series EQ) of one sec_bhavdata_full file -> ({ticker: bar}, problem).
    A file whose DATE1 is not `day` (NSE serves the previous session's file on a holiday) gives
    no bars and a problem. Each bar carries NSE's PREV_CLOSE for the corporate-action guard."""
    from nse import parse_day
    from marketbrief.utils.numbers import parse_nse_number
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
        o, h, lo, c = (parse_nse_number(r.get(k)) for k in ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE"))
        vol = parse_nse_number(r.get("TTL_TRD_QNTY"))
        if None in (o, h, lo, c, vol) or min(o, h, lo, c) <= 0 or not lo <= min(o, c) <= max(o, c) <= h:
            continue
        out[ticker] = {"open": o, "high": h, "low": lo, "close": c, "volume": int(vol),
                       "prev_close": parse_nse_number(r.get("PREV_CLOSE"))}
    return out, None


def basis_problem(cfg: dict, ticker: str, d: date, bar: dict, splits: list[date],
                  recorded: set[str] | frozenset = frozenset()) -> str | None:
    """Why a bhavcopy bar may be on another price basis than our stored bars, or None.
    Stored Yahoo bars are split/bonus-adjusted as of their collection time; the bhavcopy is as
    traded. So the bar is used only when NSE's PREV_CLOSE matches our stored close of the
    previous session (within PREV_CLOSE_TOLERANCE) and Yahoo reports no split or bonus after it
    that is not already recorded in data/<market>/adjustments/ (ids in `recorded`): a recorded
    one is applied on read, and the as-traded bar then sits on the basis the views expect."""
    prev = ev.prev_session(cfg, d, include=False)
    after = sorted(s for s in splits if s > prev and f"{ticker}-{s}" not in recorded)
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
                 nse=None, recorded: set[str] | frozenset = frozenset(),
                 held: set[str] | frozenset = frozenset()) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    """Fill missing watchlist bars of the last `n_sessions` sessions from the NSE bhavcopy, oldest
    session first (a filled bar can then anchor the next session's basis check).
    Returns (filled bars, {ticker: [{date, reason}] still missing}, notes)."""
    from nse import nse_symbols
    from marketbrief.sources.errors import FetchError
    symbols, splits = nse_symbols(cfg), splits or {}
    missing = {}
    for d in last_completed_sessions(cfg, today, n_sessions):
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
            if not reason and t in held:   # its Yahoo frame failed the split/bonus check this run
                reason = "price basis unconfirmed (split/bonus?); held, see warnings"
            reason = reason or basis_problem(cfg, t, d, bar, splits.get(t, []), recorded)
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
                   splits: dict[str, list[date]], recorded: set[str] | frozenset = frozenset(),
                   held: set[str] | frozenset = frozenset()) -> dict:
    """Run the NSE fallback and sort the Yahoo failures: a stock whose recent sessions are all
    stored afterwards moves to `resolved_by_nse`; one still missing a session, or whose newest
    stored bar (before the fallback) lies further back than the checked sessions, stays in `failed`."""
    n = int((cfg.get("price_fallback") or {}).get("sessions", 5))
    window_start = last_completed_sessions(cfg, today, n)[0]
    newest = {t: newest_stored(cfg, t, today) for t in cfg["tickers"]
              if any(f["ticker"] == t for f in failed)}
    try:
        filled, still, notes = nse_fallback(cfg, today, now, n, splits, recorded=recorded, held=held)
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
        if t in still or "beyond_nse_window" in f or t in held:   # a held stock stays failed
            keep.append(f)
        else:
            resolved.append({**f, "filled_dates": [b["date"] for b in filled if b["ticker"] == t]})
    for t, days in still.items():   # a gap Yahoo did not flag is listed too
        if not any(f["ticker"] == t for f in keep):
            keep.append({"ticker": t, "yahoo": targets[t], "error": "missing sessions after NSE fallback",
                         "missing_after_nse": days})
    failed[:] = keep
    return {"filled_from_nse": filled, "resolved_by_nse": resolved, "nse_notes": notes}


def yahoo_split_ratios(df) -> dict[date, float]:
    """{ex-date: ratio} of the splits and bonus issues in a yfinance frame (column `Stock Splits`;
    2.0 for a 2:1 split or a 1:1 bonus, 0 on other rows)."""
    if df is None or getattr(df, "empty", True) or "Stock Splits" not in df:
        return {}
    return {idx.date(): float(v) for idx, v in df["Stock Splits"].items() if v == v and v not in (0, 1) and v > 0}


def yahoo_splits(df) -> list[date]:
    """Dates of the splits and bonus issues in a yfinance frame (column `Stock Splits`)."""
    return list(yahoo_split_ratios(df))


# ---------- split / bonus detection (issue #31; scripts/adjust.py) ----------

def frame_closes(df, today: date) -> dict[date, float]:
    """{date: close} of the completed bars of a yfinance frame."""
    out = {}
    for idx, row in df.iterrows():
        c = row.get("Close")
        if idx.date() < today and c is not None and c == c and float(c) > 0:
            out[idx.date()] = float(c)
    return out


STORED_LOOKBACK_DAYS = 400   # how far back newest_stored_before searches the prices files
MIN_OVERLAP = 3              # stored bars Yahoo's frame must cover for the basis check


def newest_stored_before(cfg: dict, key: str, d: date) -> tuple[date, float] | None:
    """(date, close) of `key`'s newest stored bar dated before d (within STORED_LOOKBACK_DAYS), or None."""
    base = data_dir(cfg["market"]) / "prices"
    lo = (d - timedelta(days=STORED_LOOKBACK_DAYS)).isoformat()
    for p in sorted((p for p in base.glob("**/*.csv") if lo <= p.stem < d.isoformat()), reverse=True):
        row = stored_bars(p).get(key)
        if row and row.get("close") not in (None, "") and float(row["close"]) > 0:
            return date.fromisoformat(p.stem), float(row["close"])
    return None


def stored_overlap(cfg: dict, key: str, df, today: date) -> int:
    """How many of the frame's completed bars are stored for `key`."""
    return sum(1 for d in frame_closes(df, today) if key in stored_bars(day_file(cfg["market"], "prices", d, "csv")))


def has_stored_before(cfg: dict, key: str, d: date) -> bool:
    """True when any stored prices file dated before d holds a bar of `key`."""
    base = data_dir(cfg["market"]) / "prices"
    files = sorted((p for p in base.glob("**/*.csv") if p.stem < d.isoformat()), reverse=True)
    return any(key in stored_bars(p) for p in files)


def step_matches(step: float, factor: float) -> bool:
    """True when a price step (close / previous close) looks like the split factor: within
    0.8-1.25x of it and nearer to it than to no step at all (log distance)."""
    if step <= 0:
        return False
    return 0.8 <= step / factor <= 1.25 and abs(math.log(step / factor)) < abs(math.log(step))


def detect_adjustments(cfg: dict, key: str, df, today: date, now: str, adjs: list[dict],
                       nse_check=None, seen: set | None = None) -> tuple[list[dict], list[str], bool]:
    """Splits and bonus issues of one symbol, from Yahoo's frame compared with our stored bars
    (run before this run's bars are written). Returns (new adjustments records, warnings, hold);
    hold = True: the stored basis and Yahoo's disagree in a way no source confirms, so this run must
    not write the symbol's new bars (they would sit on Yahoo's new basis next to old-basis bars; a
    later run writes them through to_stored_basis once the split is recorded).

    Yahoo's frame is on today's basis; a stored bar keeps the basis of its collection time.
    `seen` = (ticker, ex_date) pairs already in data/<market>/adjustments/ (superseded ones too).
    1. Each `Stock Splits` row (ex-date E, ratio r, factor 1/r) not yet recorded: the stored bars
       in the frame before E (and on/after the previous split row) are compared with Yahoo's
       closes for the same dates, the stored ones on the basis the recorded adjustments give.
       All at Yahoo/stored = factor (within SPLIT_TOL; whether or not the session before E is
       stored) and Yahoo's own frame without a step of about the factor at E: recorded (source
       yahoo_splits). All at 1 (within MATCH_TOL): collected after the split, nothing to adjust.
       No stored bar before E at all: nothing to adjust. Anything else: a warning, and hold.
    2. Stored bars whose close differs from Yahoo's by more than MATCH_TOL with no split row
       explaining it: when every stored date up to the newest mismatch is off by one ratio that
       is a simple fraction (a re-base), `nse_check` (India watchlist stocks) may confirm it from
       NSE's bhavcopies (source nse_prev_close); else a warning, and hold. A mismatch that is no
       re-base (isolated, mixed, not a simple fraction) is a warning only. An overlap ratio alone
       is never recorded."""
    yc = frame_closes(df, today)
    stored = {}
    for d in yc:
        row = stored_bars(day_file(cfg["market"], "prices", d, "csv")).get(key)
        if row and row.get("close") not in (None, "") and float(row["close"]) > 0:
            stored[d] = float(row["close"])
    known = [a for a in adjs if a["ticker"] == key]
    seen = set(seen or ()) | {(a["ticker"], adj._day(a["ex_date"])) for a in known}
    records, warnings = [], []
    if not stored and yc:   # no stored bar in the frame (main() fetches back to the newest stored bar
        nb = newest_stored_before(cfg, key, min(yc))   # first; this is what is left when Yahoo has none)
        if nb:
            g = yc[min(yc)] / (nb[1] * adj.factor_after(known, key, nb[0]))
            if abs(g - 1) > adj.MATCH_TOL:
                return records, [f"{key}: no stored bar in Yahoo's frame to check the price basis; its first close "
                                 f"({min(yc)}) is {g:.4f}x our newest stored close ({nb[0]}): not verifiable, "
                                 f"new bars held"], True

    def view(d: date) -> float:
        return stored[d] * adj.factor_after(known, key, d)

    ratios = yahoo_split_ratios(df)
    bounds = sorted(ratios)
    hold = False
    for i in range(len(bounds) - 1, -1, -1):          # newest split first
        ex, r = bounds[i], ratios[bounds[i]]
        factor = 1 / r
        if (key, ex) in seen:
            continue
        lower = bounds[i - 1] if i else date.min
        window = [d for d in sorted(stored) if lower <= d < ex]
        if not window:
            if has_stored_before(cfg, key, ex):
                warnings.append(f"{key}: Yahoo reports a split/bonus on {ex} (ratio {r:g}) but no stored bar in the "
                                f"fetched window before it to check the stored basis; not recorded, new bars held")
                hold = True
            continue
        got = {d: yc[d] / view(d) for d in window}
        if all(abs(x / factor - 1) <= adj.SPLIT_TOL for x in got.values()):
            before = [d for d in yc if d < ex]
            if ex in yc and before and step_matches(yc[ex] / yc[max(before)], factor):
                warnings.append(f"{key}: Yahoo reports a split/bonus on {ex} (ratio {r:g}) but its own frame steps by "
                                f"{yc[ex] / yc[max(before)]:.4f} there (not re-based); not recorded, new bars held")
                hold = True
                continue
            d = window[-1]
            rec = adj.record(key, ex, factor, "yahoo_splits", now, yahoo_ratio=r, check_date=str(d),
                             stored_close=stored[d], yahoo_close=yc[d], measured_factor=round(got[d], 6))
            records.append(rec)
            known.append({**rec, "ex_date": ex})
            seen.add((key, ex))
        elif all(abs(x - 1) <= adj.MATCH_TOL for x in got.values()):
            before = [d for d in yc if d < ex]
            if ex in yc and before and step_matches(yc[ex] / yc[max(before)], factor):
                warnings.append(f"{key}: Yahoo reports a split/bonus on {ex} (ratio {r:g}) and steps by "
                                f"{yc[ex] / yc[max(before)]:.4f} there, but neither its history nor ours is "
                                f"adjusted; not recorded, new bars held")
                hold = True
        else:
            lo, hi = min(got.values()), max(got.values())
            warnings.append(f"{key}: Yahoo reports a split/bonus on {ex} (ratio {r:g}) but Yahoo/stored closes before "
                            f"it range {lo:.4f}-{hi:.4f} (expected {factor:.4f} or 1); not recorded, new bars held")
            hold = True
    if hold:
        return records, warnings, True
    mism = {d: yc[d] / view(d) for d in sorted(stored) if abs(yc[d] / view(d) - 1) > adj.MATCH_TOL}
    if not mism:
        return records, warnings, False
    first, last = min(mism), max(mism)
    vals = list(mism.values())
    mid = sorted(vals)[len(vals) // 2]
    detail = (f"{key}: Yahoo's close differs from the stored close on {len(mism)} date(s) {first}..{last} "
              f"(Yahoo/stored {min(vals):.4f}-{max(vals):.4f})")
    rebase = (all(abs(x / mid - 1) <= adj.SPLIT_TOL for x in vals)
              and all(d in mism for d in stored if d <= last))
    if not rebase:
        warnings.append(detail + "; not one re-base of the stored history, not recorded")
        return records, warnings, False
    fr = adj.split_fraction(mid)
    if fr is None:
        warnings.append(detail + "; a re-base by a ratio that is no simple fraction: not recorded, new bars held")
        return records, warnings, True
    later = [d for d in sorted(yc) if d > last]
    if nse_check and later:
        rec, why = nse_check(key, last, stored[last], adj.factor_after(known, key, last), float(fr), later, yc)
        if rec:
            records.append(rec)
            return records, warnings, False
        detail += f"; NSE check: {why}"
    warnings.append(detail + f"; a re-base by {fr} that no Yahoo split row or NSE bhavcopy confirms (yet): "
                    "not recorded, new bars held")
    return records, warnings, True


NSE_SCAN = 5        # frame sessions after the newest re-based stored bar searched for the ex-date
CHAIN_TOL = 0.001   # NSE PREV_CLOSE vs Yahoo's close of the same session (they agree to ~0.0002)
WEAK_FACTOR = 0.9   # from here to 1 a factor is within a normal day's move: the step alone proves nothing


def nse_basis_check(cfg: dict, now: str, nse_getter):
    """India watchlist stocks: confirm a re-base (ratio = factor) of our stored closes from NSE's
    bhavcopies and find its ex-date. NSE's PREV_CLOSE is the as-traded close of the session before;
    it is not adjusted on an ex-date (HDFCBANK's 1:1 bonus, ex 2025-08-26: PREV_CLOSE 1964.10 = its
    25-Aug close). The frame's sessions e after the newest re-based stored bar `last` are walked in
    order, up to NSE_SCAN:
    - PREV_CLOSE(e) must equal the as-traded close of e's previous session within
      PREV_CLOSE_TOLERANCE: our stored close when that session is `last` (the first e must follow
      `last` directly: this ties our stored basis to the traded one), else Yahoo's re-based close /
      factor (e's previous session was still before the ex-date).
    - Exact chain: with the next session n also in the frame, PREV_CLOSE(n) is e's traded close. If
      it equals Yahoo's close of e within CHAIN_TOL, e is on the new basis: e is the ex-date and the
      action is recorded. If it equals Yahoo's close / factor, e is still before the ex-date: next e.
      Anything else stops without a record.
    - Step: for a factor below WEAK_FACTOR, a traded close(e) / PREV_CLOSE(e) that steps by about
      the factor (step_matches) also confirms e as the ex-date (no next session needed). For a factor
      of 0.9 or more (e.g. a 1:10 bonus, 10/11) only the chain confirms, since an ordinary day's move
      can look like the step.
    No confirmation (yet) returns (None, reason): the caller warns and holds the symbol."""
    from nse import nse_symbols
    from marketbrief.sources.errors import FetchError
    symbols = nse_symbols(cfg)

    def check(key, last, stored_last, f_known, factor, later, yc):
        if key not in cfg["tickers"]:
            return None, "not a watchlist stock (no bhavcopy row)"
        cache = {}

        def bar(e):
            if e not in cache:
                url = f"/products/content/sec_bhavdata_full_{e:%d%m%Y}.csv"
                try:
                    bars, problem = bhavcopy_bars(nse_getter().text(url), e, symbols)
                except FetchError as exc:
                    cache[e] = (None, f"bhavcopy {e}: {exc.error[:120]}", url)
                else:
                    b = bars.get(key)
                    why = problem or (None if b and b.get("prev_close") else f"no EQ row with PREV_CLOSE for {key} in the {e} bhavcopy")
                    cache[e] = (None if why else b, why, url)
            return cache[e]

        def found(e, b, url):
            return adj.record(key, e, factor, "nse_prev_close", now, check_date=str(last), stored_close=stored_last,
                              yahoo_close=yc[last], measured_factor=round(yc[last] / (stored_last * f_known), 6),
                              nse_prev_close=b["prev_close"], nse_ex_close=b["close"],
                              url=f"https://nsearchives.nseindia.com{url}"), None

        scan = later[:NSE_SCAN]
        for i, e in enumerate(scan):
            p = ev.prev_session(cfg, e, include=False)
            if p == last:
                expected = stored_last
            elif p in yc and p > last:
                expected = yc[p] / (factor * f_known)
            else:
                return None, f"the session before {e} ({p}) is neither the stored bar {last} nor in Yahoo's frame"
            b, why, url = bar(e)
            if why:
                return None, why
            pc = b["prev_close"]
            if abs(pc / expected - 1) > PREV_CLOSE_TOLERANCE:
                return None, f"{e}: PREV_CLOSE {pc:g} vs the as-traded close {expected:g} of {p}"
            if factor < WEAK_FACTOR and step_matches(b["close"] / pc, factor):
                return found(e, b, url)
            n = later[i + 1] if i + 1 < len(later) else None
            if n is None or ev.prev_session(cfg, n, include=False) != e:
                return None, f"{e}: no step proves the ex-date and the next session's bhavcopy is not available yet"
            bn, why, _ = bar(n)
            if why:
                return None, why
            if abs(bn["prev_close"] / yc[e] - 1) <= CHAIN_TOL:
                return found(e, b, url)
            if abs(bn["prev_close"] * factor * f_known / yc[e] - 1) > CHAIN_TOL:
                return None, (f"{n}: PREV_CLOSE {bn['prev_close']:g} is neither Yahoo's close of {e} ({yc[e]:g}) "
                              f"nor it / {factor:.4f}")
        return None, f"no ex-date found in the bhavcopies of {scan[0]}..{scan[-1]}"
    return check


def to_stored_basis(row: list, f: float) -> list:
    """A Yahoo bar [date, key, open, high, low, close, adj_close, volume, collected_at] on today's
    basis, put on the basis the stored bars of its date have (prices / f, volume x f) when recorded
    splits or bonus issues after that date (factor product f) are applied on read; unchanged at f = 1."""
    if f == 1:
        return row
    return [row[0], row[1], *(round(v / f, 4) for v in row[2:7]), int(round(row[7] * f)), row[8]]


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
    adjs = adj.load(cfg["market"])
    seen = {(a["ticker"], a["ex_date"]) for a in adj.load(cfg["market"], include_superseded=True)}
    new_adjs, warnings, rebased, held, nse_box, nse_check = [], [], [], [], {}, None
    if (cfg.get("price_fallback") or {}).get("source") == "nse_bhavcopy":
        nse_check = nse_basis_check(cfg, now, lambda: nse_box.setdefault("c", nse_client(cfg)))

    for key, symbol in targets.items():
        try:
            df = yf.Ticker(symbol).history(period=args.period, interval="1d", auto_adjust=False)
        except Exception as exc:  # network or symbol errors must not stop other symbols
            failed.append({"ticker": key, "yahoo": symbol, "error": str(exc)[:200]})
            continue
        if df is not None and not df.empty and stored_overlap(cfg, key, df, today) < MIN_OVERLAP:
            first = min(idx.date() for idx in df.index)
            nb = newest_stored_before(cfg, key, first)
            if nb:   # a gap: fetch from before our newest stored bar so the basis check has an overlap
                try:
                    longer = yf.Ticker(symbol).history(start=(nb[0] - timedelta(days=14)).isoformat(),
                                                       interval="1d", auto_adjust=False)
                    if longer is not None and not longer.empty and min(i.date() for i in longer.index) < first:
                        df = longer
                except Exception as exc:  # the check below then compares across the gap
                    warnings.append(f"{key}: longer Yahoo history for the basis check failed: {str(exc)[:120]}")
        splits[key] = yahoo_splits(df)
        error = frame_error(cfg, key, df, today)
        if error:
            failed.append({"ticker": key, "yahoo": symbol, "error": error})
            if not error.startswith("stale"):
                continue
        try:   # before this symbol's bars are written: Yahoo's frame against the stored bars
            recs, warns, hold = detect_adjustments(cfg, key, df, today, now, adjs, nse_check, seen)
        except Exception as exc:  # a failed check must not cost the bars
            recs, warns, hold = [], [f"{key}: split/bonus check failed: {str(exc)[:160]}"], False
        for rec in recs:
            ex = date.fromisoformat(rec["ex_date"])
            append_jsonl(day_file(cfg["market"], "adjustments", ex), [rec])
            adjs.append({**rec, "ex_date": ex})
            seen.add((key, ex))
        new_adjs += recs
        warnings += warns
        if hold:   # Yahoo's frame is on a basis no source confirms: no new bar is written this run
            held.append(key)
            note = "price basis unconfirmed (split/bonus?): new bars held, see warnings"
            entry = next((f for f in failed if f["ticker"] == key), None)
            if entry:
                entry["error"] += f"; {note}"
            else:
                failed.append({"ticker": key, "yahoo": symbol, "error": note})
            continue
        for idx, row in df.iterrows():
            d = idx.date()
            if d >= today or row.isna()[["Open", "High", "Low", "Close"]].any():
                continue
            path = day_file(cfg["market"], "prices", d, "csv")
            if key in stored_bars(path):
                continue
            close = float(row["Close"])
            adj_close = float(row["Adj Close"]) if "Adj Close" in row else close
            vol = int(row["Volume"]) if row["Volume"] == row["Volume"] else 0
            bar = [d.isoformat(), key, round(float(row["Open"]), 4), round(float(row["High"]), 4),
                   round(float(row["Low"]), 4), round(close, 4), round(adj_close, 4), vol, now]
            f = adj.factor_after(adjs, key, d)
            if f != 1:   # an older bar Yahoo serves on today's basis, written on its stored basis
                bar = to_stored_basis(bar, f)
                rebased.append({"ticker": key, "date": d.isoformat(), "factor": f})
            write_bar(path, bar)
            written += 1

    summary = {"collector": "prices", "market": cfg["market"], "symbols": len(targets), "new_bars": written,
               "adjustments": new_adjs}
    if rebased:
        summary["rebased_bars"] = rebased
    if held:
        summary["held"] = held
    if (cfg.get("price_fallback") or {}).get("source") == "nse_bhavcopy":
        summary.update(apply_fallback(cfg, today, now, targets, failed, splits, {a["id"] for a in adjs}, set(held)))
    summary["warnings"] = warnings
    summary["failed"] = failed
    print(json.dumps(summary, indent=2))
    return 1 if failed and len(failed) == len(targets) else 0


if __name__ == "__main__":
    sys.exit(main())
