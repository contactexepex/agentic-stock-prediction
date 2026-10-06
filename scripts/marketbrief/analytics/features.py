"""Compute the daily indicator snapshot and market regime for one market.

Reads stored bars, quotes and events (never live APIs), then appends:
- data/<market>/features/YYYY/MM/<as_of_date>.jsonl: one row per watchlist ticker
- data/<market>/regime/YYYY/MM/<as_of_date>.jsonl: one row for the market
and prints a JSON summary. as_of_date = latest benchmark bar; session_date = the trading day
being predicted (today in the exchange's timezone if it is a session, else the next one)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from marketbrief.analytics import indicators
from marketbrief.analytics import regime as regime_rules
from marketbrief.constants.config_keys import CFG_MARKET, CFG_SECTORS, CFG_TICKERS, CFG_TIMEZONE
from marketbrief.constants.features import (
    EX_DIVIDEND_WINDOW_DAYS,
    MSG_CALENDAR_NOT_COVERED,
    MSG_NO_BENCHMARK,
    MSG_NO_PRICE_DATA,
    MSG_STALE_BAR,
    QUALITY_ORDER,
    SECTOR_PEER_RETURN,
    STEP_FEATURES,
    UPCOMING_EVENT_DAYS,
    VOL_CHANGE_DECIMALS,
    VOL_DECIMALS,
)
from marketbrief.constants.indicators import QUALITY_BLOCKED, QUALITY_OK, QUALITY_PARTIAL
from marketbrief.core.calendar import calendar_covers, major_events_near, market_events, next_session
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.core.schemas import FEATURE_COLS
from marketbrief.core.storage import append_jsonl, day_file


def local_today(cfg: dict) -> date:
    """Today in the market's timezone (the clock's, so MB_NOW applies)."""
    return clock().astimezone(ZoneInfo(cfg[CFG_TIMEZONE])).date()


def load_bars(con) -> dict[str, pd.DataFrame]:
    """The adjusted daily bars of every ticker and symbol, indexed by date."""
    bars = con.execute("SELECT ticker, date, open, high, low, close, volume FROM ohlc ORDER BY ticker, date").df()
    if bars.empty:
        return {}
    bars["date"] = pd.to_datetime(bars["date"])
    return {ticker: group.set_index("date").drop(columns="ticker") for ticker, group in bars.groupby("ticker")}


def quotes_today(con, day: date) -> dict[str, dict]:
    """The latest quote of each symbol collected on `day`."""
    rows = con.execute(
        "SELECT symbol, price, prev_close, change_pct, ts FROM quotes_latest WHERE day = ?", [day]
    ).fetchall()
    return {
        quote_row[0]: {
            "price": quote_row[1],
            "prev_close": quote_row[2],
            "change_pct": quote_row[3],
            "ts": quote_row[4],
        }
        for quote_row in rows
    }


def company_events(con, start: date) -> dict[tuple[str, str], date]:
    """{(ticker, type): date} of the company events from `start` on."""
    rows = con.execute("SELECT ticker, type, date FROM company_events WHERE date >= ?", [start]).fetchall()
    return {(ticker, kind): day for ticker, kind, day in rows}


def ticker_values(key: str, bars: dict[str, pd.DataFrame], bench: pd.DataFrame, as_of: date) -> dict:
    """The indicators of one ticker as of the benchmark's latest bar (blocked when it has no bars)."""
    frame = bars.get(key)
    frame = frame[frame.index <= pd.Timestamp(as_of)] if frame is not None else None
    if frame is None or frame.empty:
        return {"bars": 0, "quality": QUALITY_BLOCKED, "warnings": [MSG_NO_PRICE_DATA]}
    values = indicators.compute(frame, bench["close"])
    if frame.index[-1].date() < as_of:
        values["warnings"].append(MSG_STALE_BAR.format(day=frame.index[-1].date()))
        values["quality"] = QUALITY_PARTIAL if values["quality"] == QUALITY_OK else values["quality"]
    return values


def add_event_values(values: dict, key: str, quote: dict | None, company: dict, session: date) -> None:
    """The overnight cue, the days to earnings and the ex-dividend date of a ticker."""
    values["cue_change_pct"] = quote["change_pct"] if quote else None
    earnings = company.get((key, "earnings"))
    values["days_to_earnings"] = (earnings - session).days if earnings else None
    ex_dividend = company.get((key, "ex_dividend"))
    in_window = ex_dividend and (ex_dividend - session).days <= EX_DIVIDEND_WINDOW_DAYS
    values["ex_dividend_date"] = ex_dividend.isoformat() if in_window else None


def add_sector_strength(cfg: dict, rows: dict[str, dict]) -> None:
    """Relative strength vs sector peers (5-day return minus peers' average)."""
    for members in cfg.get(CFG_SECTORS, {}).values():
        for key in members:
            peers = [
                rows[peer][SECTOR_PEER_RETURN]
                for peer in members
                if peer != key and rows.get(peer, {}).get(SECTOR_PEER_RETURN) is not None
            ]
            own = rows.get(key, {}).get(SECTOR_PEER_RETURN)
            rows[key]["rel_sector_5d"] = own - sum(peers) / len(peers) if own is not None and peers else None


def vol_inputs(
    bars: dict[str, pd.DataFrame], vol_key: str, quotes: dict[str, dict]
) -> tuple[float | None, float | None]:
    """(vol index level, its one-day change): the latest bar, or the quote when there is one."""
    vol = bars.get(vol_key)
    if vol is None or vol.empty:
        return None, None
    vol_level = float(vol["close"].iloc[-1])
    previous = float(vol["close"].iloc[-2]) if len(vol) > 1 else None
    quote = quotes.get(vol_key)
    if quote and quote.get("price"):
        vol_level, previous = quote["price"], quote["prev_close"] or previous
    return vol_level, (vol_level / previous - 1 if previous else None)


def regime_row(
    cfg: dict, bench: pd.DataFrame, as_of: date, session: date, inputs: tuple, now: str
) -> tuple[dict, list]:
    """(the regime row, the upcoming market events) for the day; `inputs` = (vol level, vol change, today)."""
    vol_level, vol_change, today_local = inputs
    bench_ret_5d = indicators.period_return(bench["close"], 5)
    bench_vol_10d = indicators.realized_vol(bench["close"])
    upcoming = market_events(cfg, today_local, session + timedelta(days=UPCOMING_EVENT_DAYS))
    near = major_events_near(upcoming, session)
    regime, stress, notes = regime_rules.classify(
        cfg["regime"], vol_level, bench_ret_5d, bench_vol_10d, bool(near), vol_change
    )
    if not calendar_covers(cfg, session):
        notes.append(MSG_CALENDAR_NOT_COVERED.format(session=session))
    row = {
        "id": str(as_of),
        "as_of_date": as_of.isoformat(),
        "session_date": session.isoformat(),
        "computed_at": now,
        "regime": regime,
        "vol_level": round(vol_level, VOL_DECIMALS) if vol_level is not None else None,
        "vol_change_1d": round(vol_change, VOL_CHANGE_DECIMALS) if vol_change is not None else None,
        "bench_ret_5d": bench_ret_5d,
        "bench_vol_10d": bench_vol_10d,
        "major_event": bool(near),
        "major_event_names": [event["name"] for event in near],
        "stress": stress,
        "notes": notes,
    }
    return row, upcoming


def run(cfg: dict, today_local: date | None = None, utc_day: date | None = None) -> dict:
    """Compute and store the features and the regime row; returns the JSON summary."""
    market = cfg[CFG_MARKET]
    con = connect(market)
    bars = load_bars(con)
    today_local = today_local or local_today(cfg)
    session = next_session(cfg, today_local)
    bench_key, vol_key = benchmark_key(cfg), vol_index_key(cfg)
    bench = bars.get(bench_key)
    if bench is None or bench.empty:
        raise SystemExit(MSG_NO_BENCHMARK.format(key=bench_key))
    as_of = bench.index[-1].date()
    quotes = quotes_today(con, utc_day or utc_today())
    company = company_events(con, session)
    now = utc_now()

    rows = {}
    for key in cfg[CFG_TICKERS]:
        values = ticker_values(key, bars, bench, as_of)
        add_event_values(values, key, quotes.get(f"{key}:ADR") or quotes.get(key), company, session)
        rows[key] = values
    add_sector_strength(cfg, rows)
    feature_rows = [
        {
            "id": f"{as_of}-{ticker_key}",
            "as_of_date": as_of.isoformat(),
            "ticker": ticker_key,
            "computed_at": now,
            **{column: feature_values.get(column) for column in FEATURE_COLS},
        }
        for ticker_key, feature_values in rows.items()
    ]

    vol_level, vol_change = vol_inputs(bars, vol_key, quotes)
    regime_data, upcoming = regime_row(cfg, bench, as_of, session, (vol_level, vol_change, today_local), now)

    append_jsonl(day_file(market, "features", as_of), feature_rows)
    append_jsonl(day_file(market, "regime", as_of), [regime_data])
    quality = {
        quality_level: sorted(
            ticker_key for ticker_key, feature_values in rows.items() if feature_values["quality"] == quality_level
        )
        for quality_level in QUALITY_ORDER
    }
    return {
        "step": STEP_FEATURES,
        "market": market,
        "as_of_date": str(as_of),
        "session_date": str(session),
        "regime": regime_data["regime"],
        "stress": regime_data["stress"],
        "notes": regime_data["notes"],
        "tickers": {quality_level: len(feature_values) for quality_level, feature_values in quality.items()},
        "partial": quality[QUALITY_PARTIAL],
        "blocked": quality[QUALITY_BLOCKED],
        "upcoming_events": [f"{event['date']} {event['name']}" for event in upcoming],
    }


def main() -> int:
    """Entry point of scripts/features.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    print(json.dumps(run(cfg), indent=2, default=str))
    return 0
