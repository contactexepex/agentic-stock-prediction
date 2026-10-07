"""One intraday check of a market's watchlist (scripts/intraday_check.py run): fetch the session so far, compare
each ticker with the session's published ranges and open calls as of the check time, flag deviations, list
attribution candidates, and append one row per ticker plus one run row. Market closed: only the run row.
A check time already stored (same minute) writes nothing (idempotent)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from marketbrief.constants.config_keys import (
    CFG_MARKET,
    CFG_SECTOR_ETFS,
    CFG_SYMBOLS,
    CFG_TICKERS,
    CFG_TIMEZONE,
    META_YAHOO,
)
from marketbrief.core import paths
from marketbrief.core.calendar import is_session, prev_session, session_close_utc, session_open_utc
from marketbrief.core.clock import utc_now
from marketbrief.core.market_config import benchmark_key
from marketbrief.intraday import inputs
from marketbrief.intraday.constants import (
    KIND_INTRADAY_CHECKS,
    KIND_INTRADAY_RUNS,
    METHOD_VERSION,
    MSG_ALREADY_CHECKED,
    MSG_MARKET_CLOSED,
    NEWS_SINCE_PREV_CLOSE,
    QUALITY_NO_QUOTE,
    QUALITY_STALE,
    RUN_MARKET_CLOSED,
    RUN_OK,
    RUN_STALE,
)
from marketbrief.intraday.quotes import complete_bars, last_bar_time, session_quote
from marketbrief.intraday.rows import CheckContext, ticker_row
from marketbrief.intraday.settings import check_id, check_time
from marketbrief.intraday.store import stored_ids, write_rows


def symbols_needed(cfg: dict) -> dict[str, str]:
    """{key: Yahoo symbol}: the watchlist, the benchmark and the sector ETFs/indices of watchlist sectors."""
    wanted = {key: meta.get(META_YAHOO, key) for key, meta in cfg[CFG_TICKERS].items()}
    bench = benchmark_key(cfg)
    for key in [bench, *cfg.get(CFG_SECTOR_ETFS, {}).values()]:
        if key:
            wanted[key] = cfg[CFG_SYMBOLS][key].get(META_YAHOO, key)
    return wanted


def fetch_quotes(ctx: CheckContext, fetcher, symbols: dict[str, str]) -> list[dict]:
    """Fill ctx.quotes / ctx.stale from the fetcher; returns the failures."""
    bar = timedelta(minutes=ctx.settings["quotes"]["bar_minutes"])
    stale_after = timedelta(minutes=ctx.settings["quotes"]["stale_minutes"])
    failed = []
    for key, symbol in symbols.items():
        try:
            frame = complete_bars(fetcher.bars(symbol), ctx.check_at, ctx.settings["quotes"]["bar_minutes"])
        except Exception as exc:  # one symbol's failure never stops the check
            failed.append({"symbol": key, "yahoo": symbol, "error": str(exc)[:200]})
            ctx.quotes[key], ctx.stale[key] = None, QUALITY_NO_QUOTE
            continue
        ctx.quotes[key] = session_quote(frame, ctx.session_open, ctx.session_close)
        newest = last_bar_time(frame)
        if ctx.quotes[key] is None:
            ctx.stale[key] = QUALITY_STALE if newest is not None else QUALITY_NO_QUOTE
        elif ctx.check_at - (ctx.quotes[key].last_time + bar) > stale_after:
            ctx.stale[key] = QUALITY_STALE
    return failed


def fetch_cue(cfg: dict, fetcher, check_at: datetime, failed: list[dict]) -> dict | None:
    """The index cue's snapshot (the quotes collector's): `ret` = its change vs the previous regular-session close
    (the collector's change_pct, a fraction), kept only when its quote time is by check_at."""
    key = (cfg.get("index_cue") or {}).get("symbol")
    if not key or key not in cfg[CFG_SYMBOLS]:
        return None
    symbol = cfg[CFG_SYMBOLS][key].get(META_YAHOO, key)
    try:
        snap = fetcher.cue(symbol, check_at.isoformat())
    except Exception as exc:  # the cue is context only
        failed.append({"symbol": key, "yahoo": symbol, "error": str(exc)[:200]})
        return None
    if pd.Timestamp(snap["ts"]) > pd.Timestamp(check_at):
        return None
    return {"symbol": key, "ret": snap["change_pct"], "ts": snap["ts"]}


def load_inputs(ctx: CheckContext) -> None:
    """The stored inputs as of check_at."""
    con, day, at = ctx.con, ctx.session_date, ctx.check_at
    ctx.ranges = inputs.published_ranges(con, day, at)
    ctx.calls = inputs.open_calls(con, ctx.cfg, day, at)
    ctx.features = inputs.latest_features(con, day, at)
    ctx.prev_closes = inputs.previous_closes(con, day)
    keys = [(ticker, call["entry_date"]) for ticker, calls in ctx.calls.items() for call in calls
            if call["entry_date"] != day.isoformat()]
    ctx.entry_opens = inputs.entry_opens(con, keys)


def run_row(ctx: CheckContext, status: str, counts: dict, note: str | None = None) -> dict:
    """The run's own row."""
    return {
        "id": ctx.check_id, "check_at": ctx.check_at.isoformat(), "session_date": ctx.session_date.isoformat(),
        "status": status, "tickers": counts.get("tickers", 0), "written": counts.get("written", 0),
        "flagged": counts.get("flagged", 0), "stale": counts.get("stale", []),
        "failed": counts.get("failed", []), "note": note, "method_version": METHOD_VERSION,
        "computed_at": ctx.computed_at,
    }


def run_check(cfg: dict, settings: dict, con, fetcher, now: datetime, out_root: Path | None = None) -> dict:
    """Run one check at `now` (truncated to the minute) and return its summary."""
    market = cfg[CFG_MARKET]
    check_at = check_time(now)
    session_date = check_at.astimezone(ZoneInfo(cfg[CFG_TIMEZONE])).date()
    ident = check_id(market, check_at)
    summary = {"step": "intraday_check", "market": market, "check_id": ident, "check_at": check_at.isoformat(),
               "session_date": session_date.isoformat(), "to": str(out_root or paths.data_dir(market))}
    if ident in stored_ids(con, KIND_INTRADAY_RUNS, out_root):
        return {**summary, "status": "duplicate", "note": MSG_ALREADY_CHECKED.format(check_id=ident), "written": 0}
    trading = is_session(cfg, session_date)
    ctx = CheckContext(cfg, settings, con, ident, check_at, session_date,
                       session_open_utc(cfg, session_date) if trading else None,
                       session_close_utc(cfg, session_date) if trading else None, utc_now())
    bar = timedelta(minutes=settings["quotes"]["bar_minutes"])
    if not trading or not ctx.session_open + bar <= check_at <= ctx.session_close + bar:
        note = MSG_MARKET_CLOSED.format(check_at=check_at.isoformat(), session=session_date.isoformat())
        write_rows(market, KIND_INTRADAY_RUNS, check_at.date(), [run_row(ctx, RUN_MARKET_CLOSED, {}, note)], out_root)
        return {**summary, "status": RUN_MARKET_CLOSED, "note": note, "written": 0}
    failed = fetch_quotes(ctx, fetcher, symbols_needed(cfg))
    ctx.market_moves = {"benchmark": benchmark_key(cfg), "cue": fetch_cue(cfg, fetcher, check_at, failed)}
    load_inputs(ctx)
    if settings["attribution"].get("news_window") == NEWS_SINCE_PREV_CLOSE:
        ctx.news_since = session_close_utc(cfg, prev_session(cfg, session_date, include=False))
    rows = [ticker_row(ctx, ticker, meta) for ticker, meta in cfg[CFG_TICKERS].items()]
    stale = sorted(row["ticker"] for row in rows if row["quality"] != "ok")
    status = RUN_STALE if rows and len(stale) >= settings["quotes"]["stale_run_share"] * len(rows) else RUN_OK
    written = write_rows(market, KIND_INTRADAY_CHECKS, check_at.date(), rows, out_root)
    counts = {"tickers": len(rows), "written": written, "flagged": sum(row["flagged"] for row in rows),
              "stale": stale, "failed": failed}
    write_rows(market, KIND_INTRADAY_RUNS, check_at.date(), [run_row(ctx, status, counts)], out_root)
    flagged = {row["ticker"]: row["flags"] for row in rows if row["flagged"]}
    return {**summary, "status": status, **counts, "flagged_tickers": flagged,
            "benchmark_ret": ctx.ret(benchmark_key(cfg)), "cue": ctx.market_moves["cue"]}


def print_summary(summary: dict) -> None:
    """The run's JSON summary on stdout."""
    print(json.dumps(summary, indent=2, default=str))
