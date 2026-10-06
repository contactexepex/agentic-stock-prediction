"""Replay inputs as known at each as-of day: earnings versions, regimes, major dates, RSI series."""

from __future__ import annotations

import bisect
from datetime import date, timedelta
import numpy as np
import pandas as pd
from marketbrief.replay.backtest import observations
from marketbrief.analytics import event_history, range_switches
from marketbrief.analytics import indicators, regime as regime_rules
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.constants.messages import MSG_NO_BENCHMARK_BARS_PERIOD
from marketbrief.analytics.features import load_bars
from marketbrief.core import calendar


def known_versions(cfg: dict, versions: dict) -> dict:
    """Shift each earnings version's start (a 10-Q/10-K acceptance date c) to the last session before
    c: ranges.py made pre-open on session S uses the reports accepted by S, so as-of d (S = the next
    session after d) sees the version once d >= that session. observations.input_columns then applies it."""
    return {
        ticker: [
            (None if start is None else calendar.prev_session(cfg, start, include=False), end)
            for start, end in version_list
        ]
        for ticker, version_list in versions.items()
    }


def next_earnings(versions: list, as_of_day: date) -> date | None:
    """The first earnings date after d in the version active pre-open the next session (the
    historical stand-in for ranges.py's upcoming `company_events` date when earnings_history is off)."""
    if not versions:
        return None
    starts = [date.min if start is None else start for start, _ in versions]
    key = bisect.bisect_right(starts, as_of_day) - 1
    if key < 0:
        return None
    dates = [earnings_day for earnings_day, _ in versions[key][1]]
    inner_index = bisect.bisect_right(dates, as_of_day)
    return dates[inner_index] if inner_index < len(dates) else None


def regimes(cfg: dict, bars: dict, days: list[date]) -> pd.DataFrame:
    """Regime per as-of day as features.py computes it (closes stand in for pre-open vol quotes)."""
    bench = bars[benchmark_key(cfg)]["close"]
    vol_key = vol_index_key(cfg)
    vol = bars[vol_key]["close"] if vol_key in bars else pd.Series(dtype=float)
    vdates = [timestamp.date() for timestamp in vol.index]
    bdates = [timestamp.date() for timestamp in bench.index]
    mev = calendar.market_events(cfg, days[0], days[-1] + timedelta(days=40)) if days else []
    rows = []
    for day in days:
        position = bisect.bisect_right(bdates, day)
        tail = bench.iloc[max(0, position - 31) : position]
        inner_index = bisect.bisect_right(vdates, day)
        lvl = float(vol.iloc[inner_index - 1]) if inner_index >= 1 else None
        prev = float(vol.iloc[inner_index - 2]) if inner_index >= 2 else None
        change = lvl / prev - 1 if lvl is not None and prev else None
        session = calendar.next_session(cfg, day, include=False)
        near = calendar.major_events_near(mev, session)
        return_5d, v10 = indicators.period_return(tail, 5), indicators.realized_vol(tail)
        label, stress, _ = regime_rules.classify(cfg["regime"], lvl, return_5d, v10, bool(near), change)
        rows.append(
            {
                "date": day,
                "regime": label,
                "stress": stress,
                "vol_level": lvl,
                "bench_ret_5d": return_5d,
                "bench_vol_10d": v10,
                "major_event": bool(near),
            }
        )
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def major_dates(cfg: dict, start: date, end: date) -> list[date]:
    """The dates of major market events in a period."""
    return sorted({event["date"] for event in calendar.market_events(cfg, start, end) if event["major"]})


def rsi_series(close: pd.Series, window: int = 14) -> pd.Series:
    """indicators.rsi at every date (the same causal Wilder smoothing, so the value at d equals
    indicators.rsi(close[:d]); tests/test_replay.py checks it)."""
    diff = close.diff()
    gain = diff.clip(lower=0).iloc[1:].ewm(alpha=1 / window, adjust=False).mean()
    loss = (-diff.clip(upper=0)).iloc[1:].ewm(alpha=1 / window, adjust=False).mean()
    out = 100 - 100 / (1 + gain / loss)
    out = out.where(loss != 0, np.where(gain > 0, 100.0, 50.0))
    out = out.reindex(close.index)
    out.iloc[:window] = np.nan
    return out


def window_days(bench: pd.DataFrame, ranges_config: dict, start: date | None, end: date | None) -> list[date]:
    """The as-of days of the replay window."""
    idx = [timestamp.date() for timestamp in bench.index]
    first = idx[min(ranges_config["warmup_bars"], len(idx) - 1)] if idx else None
    first_day = max(start, first) if start else first
    return [day for day in idx if first_day and day >= first_day and (end is None or day <= end)]


def load_inputs(cfg: dict, ranges_config: dict, con) -> tuple[dict, dict]:
    """The bars and the earnings, dividend and index-cue inputs of the replay."""
    bars = load_bars(con)
    bench = bars.get(benchmark_key(cfg))
    if bench is None or bench.empty:
        raise SystemExit(MSG_NO_BENCHMARK_BARS_PERIOD)
    evdf = event_history.load_events(con)
    extra = {
        "earnings": known_versions(cfg, event_history.earnings_versions(evdf)) if not evdf.empty else {},
        "dividends": event_history.dividend_events(evdf) if not evdf.empty else {},
        "bench": bench,
        "index_cue": observations.index_cue_series(cfg, bars, ranges_config)
        if range_switches.enabled(ranges_config, "beta_split", cfg["market"])
        else None,
    }
    return bars, extra
