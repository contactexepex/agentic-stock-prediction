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
    return {t: [(None if s is None else calendar.prev_session(cfg, s, include=False), e) for s, e in vs]
            for t, vs in versions.items()}


def next_earnings(versions: list, d: date) -> date | None:
    """The first earnings date after d in the version active pre-open the next session (the
    historical stand-in for ranges.py's upcoming `company_events` date when earnings_history is off)."""
    if not versions:
        return None
    starts = [date.min if s is None else s for s, _ in versions]
    k = bisect.bisect_right(starts, d) - 1
    if k < 0:
        return None
    dates = [x for x, _ in versions[k][1]]
    j = bisect.bisect_right(dates, d)
    return dates[j] if j < len(dates) else None


def regimes(cfg: dict, bars: dict, days: list[date]) -> pd.DataFrame:
    """Regime per as-of day as features.py computes it (closes stand in for pre-open vol quotes)."""
    bench = bars[benchmark_key(cfg)]["close"]
    vk = vol_index_key(cfg)
    vol = bars[vk]["close"] if vk in bars else pd.Series(dtype=float)
    vdates = [x.date() for x in vol.index]
    bdates = [x.date() for x in bench.index]
    mev = calendar.market_events(cfg, days[0], days[-1] + timedelta(days=40)) if days else []
    rows = []
    for d in days:
        i = bisect.bisect_right(bdates, d)
        tail = bench.iloc[max(0, i - 31):i]
        j = bisect.bisect_right(vdates, d)
        lvl = float(vol.iloc[j - 1]) if j >= 1 else None
        prev = float(vol.iloc[j - 2]) if j >= 2 else None
        change = lvl / prev - 1 if lvl is not None and prev else None
        session = calendar.next_session(cfg, d, include=False)
        near = calendar.major_events_near(mev, session)
        r5, v10 = indicators.period_return(tail, 5), indicators.realized_vol(tail)
        label, stress, _ = regime_rules.classify(cfg["regime"], lvl, r5, v10, bool(near), change)
        rows.append({"date": d, "regime": label, "stress": stress, "vol_level": lvl, "bench_ret_5d": r5,
                     "bench_vol_10d": v10, "major_event": bool(near)})
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def major_dates(cfg: dict, start: date, end: date) -> list[date]:
    return sorted({e["date"] for e in calendar.market_events(cfg, start, end) if e["major"]})


def rsi_series(close: pd.Series, n: int = 14) -> pd.Series:
    """indicators.rsi at every date (the same causal Wilder smoothing, so the value at d equals
    indicators.rsi(close[:d]); tests/test_replay.py checks it)."""
    diff = close.diff()
    gain = diff.clip(lower=0).iloc[1:].ewm(alpha=1 / n, adjust=False).mean()
    loss = (-diff.clip(upper=0)).iloc[1:].ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + gain / loss)
    out = out.where(loss != 0, np.where(gain > 0, 100.0, 50.0))
    out = out.reindex(close.index)
    out.iloc[:n] = np.nan
    return out


def window_days(bench: pd.DataFrame, rc: dict, start: date | None, end: date | None) -> list[date]:
    idx = [x.date() for x in bench.index]
    first = idx[min(rc["warmup_bars"], len(idx) - 1)] if idx else None
    lo = max(start, first) if start else first
    return [d for d in idx if lo and d >= lo and (end is None or d <= end)]


def load_inputs(cfg: dict, rc: dict, con) -> tuple[dict, dict]:
    bars = load_bars(con)
    bench = bars.get(benchmark_key(cfg))
    if bench is None or bench.empty:
        raise SystemExit(MSG_NO_BENCHMARK_BARS_PERIOD)
    evdf = event_history.load_events(con)
    extra = {"earnings": known_versions(cfg, event_history.earnings_versions(evdf)) if not evdf.empty else {},
             "dividends": event_history.dividend_events(evdf) if not evdf.empty else {}, "bench": bench,
             "index_cue": observations.index_cue_series(cfg, bars, rc) if range_switches.enabled(rc, "beta_split", cfg["market"]) else None}
    return bars, extra
