"""Snapshot the latest price of overnight / pre-open cues into
data/<market>/quotes/YYYY/MM/<today>.jsonl: benchmark, vol index, cue and factor symbols,
the ADRs of watchlist tickers, and (if `premarket_quotes: true`) every watchlist ticker's
pre-market price. change_pct = latest price vs the previous regular-session close.
A symbol goes to `failed` (and is not written) when Yahoo returns no priced bar or its latest
quote is more than STALE_DAYS old: a stale cue would pose as today's."""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from marketbrief.constants.collection import STALE_DAYS
from marketbrief.constants.columns import COL_SYMBOL
from marketbrief.constants.config_keys import (CFG_MARKET, CFG_PREMARKET_QUOTES, CFG_SYMBOLS, CFG_TICKERS, META_ADR,
                                               META_ROLE, META_YAHOO)
from marketbrief.constants.kinds import KIND_QUOTES
from marketbrief.constants.quotes import (ADR_KEY_SUFFIX, COLLECTOR_QUOTES, DAILY_PERIOD, INTRADAY_INTERVAL,
                                          INTRADAY_PERIOD, MSG_NO_DATA, MSG_NO_PREVIOUS_CLOSE, MSG_STALE_QUOTE,
                                          QUOTE_ROLES, QUOTE_TEXT_LIMIT, YAHOO_CLOSE_COLUMN)
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_FAILED, SUMMARY_MARKET
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file


def quote_targets(cfg: dict) -> dict[str, str]:
    """{key: Yahoo symbol} of the symbols to snapshot: market-level roles, ADRs, pre-market tickers."""
    targets = {key: meta[META_YAHOO] for key, meta in cfg[CFG_SYMBOLS].items() if meta.get(META_ROLE) in QUOTE_ROLES}
    for key, meta in cfg[CFG_TICKERS].items():
        if meta.get(META_ADR):
            targets[f"{key}{ADR_KEY_SUFFIX}"] = meta[META_ADR]
        if cfg.get(CFG_PREMARKET_QUOTES):
            targets[key] = meta[META_YAHOO]
    return targets


def priced(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows with a close (Yahoo pads some series with empty bars)."""
    if frame is not None and YAHOO_CLOSE_COLUMN in frame.columns:
        return frame.dropna(subset=[YAHOO_CLOSE_COLUMN])
    return pd.DataFrame()


def snapshot(yf, symbol: str, now: str | None = None) -> dict:
    """The latest intraday price of a symbol against the previous regular-session close."""
    ticker = yf.Ticker(symbol)
    intraday = priced(ticker.history(period=INTRADAY_PERIOD, interval=INTRADAY_INTERVAL, prepost=True))
    daily = priced(ticker.history(period=DAILY_PERIOD, interval="1d"))
    if intraday.empty or daily.empty:
        raise ValueError(MSG_NO_DATA)
    last_ts = intraday.index[-1]
    if pd.Timestamp(now or utc_now()) - last_ts > timedelta(days=STALE_DAYS):
        raise ValueError(MSG_STALE_QUOTE.format(last=last_ts.tz_convert("UTC").isoformat()))
    session_day = last_ts.tz_convert(daily.index.tz).date() if daily.index.tz else last_ts.date()
    prior = daily[[stamp.date() < session_day for stamp in daily.index]]
    if prior.empty:
        raise ValueError(MSG_NO_PREVIOUS_CLOSE)
    price, previous = float(intraday[YAHOO_CLOSE_COLUMN].iloc[-1]), float(prior[YAHOO_CLOSE_COLUMN].iloc[-1])
    return {"ts": last_ts.tz_convert("UTC").isoformat(), "price": round(price, 4),
            "prev_close": round(previous, 4), "change_pct": round(price / previous - 1, 6)}


def main() -> int:
    """Entry point of scripts/collect_quotes.py."""
    args = market_arg(__doc__).parse_args()
    cfg = require_market(args)
    import yfinance as yf

    now, rows, failed = utc_now(), [], []
    targets = quote_targets(cfg)
    for key, symbol in targets.items():
        try:
            rows.append({COL_SYMBOL: key, "yahoo": symbol, **snapshot(yf, symbol, now), "collected_at": now})
        except Exception as exc:
            failed.append({COL_SYMBOL: key, "yahoo": symbol, "error": str(exc)[:QUOTE_TEXT_LIMIT]})
    written = append_jsonl(day_file(cfg[CFG_MARKET], KIND_QUOTES, utc_today()), rows)
    print(json.dumps({SUMMARY_COLLECTOR: COLLECTOR_QUOTES, SUMMARY_MARKET: cfg[CFG_MARKET],
                      "symbols": len(targets), "written": written, SUMMARY_FAILED: failed}, indent=2))
    return 1 if targets and not rows else 0
