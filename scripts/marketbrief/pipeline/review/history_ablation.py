"""Ablation (b): walk-forward on stored prices with each input switched off."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from marketbrief.analytics import indicators
from marketbrief.analytics import regime as regime_rules
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.constants.review import BASELINE, MSG_NOT_ENOUGH_BENCHMARK_BARS
from marketbrief.core import calendar
from marketbrief.core.horizons import window_sessions
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.pipeline.review.helpers import merge
from marketbrief.replay.backtest import evaluation, observations
from marketbrief.utils.event_dates import major_event_between


def history_context(cfg: dict, bars: dict, dates: list) -> tuple[list[str], list[date]]:
    """Regime per bar date rebuilt from stored bars (as features.py does live, with closes instead
    of pre-open quotes) and the sorted dates of major market events."""
    bench = bars[benchmark_key(cfg)]["close"]
    vol_key = vol_index_key(cfg)
    vol = bars[vol_key]["close"].reindex(bench.index) if vol_key in bars else pd.Series(np.nan, index=bench.index)
    first, last = dates[0].date(), dates[-1].date()
    events = calendar.market_events(cfg, first, last + timedelta(days=30))
    majors = sorted({event["date"] for event in events if event["major"]})
    regimes = []
    for position, date_index in enumerate(dates):
        tail = bench.iloc[max(0, position - 30) : position + 1]
        lvl = None if pd.isna(vol.iloc[position]) else float(vol.iloc[position])
        prev = None if position == 0 or pd.isna(vol.iloc[position - 1]) else float(vol.iloc[position - 1])
        session = (
            dates[position + 1].date()
            if position + 1 < len(dates)
            else calendar.next_session(cfg, date_index.date(), include=False)
        )
        near = calendar.major_events_near(events, session)
        regimes.append(
            regime_rules.classify(
                cfg["regime"],
                lvl,
                indicators.period_return(tail, 5),
                indicators.realized_vol(tail),
                bool(near),
                lvl / prev - 1 if lvl and prev else None,
            )[0]
        )
    return regimes, majors


def hist_summary(res: pd.DataFrame) -> dict:
    """Coverage, width and score of the walk-forward rows."""
    if res.empty:
        return {"n": 0}
    means = res.mean(numeric_only=True)
    return {
        "n": int(len(res)),
        "cover50": round(float(means["hit50"]), 4),
        "cover80": round(float(means["hit80"]), 4),
        "width80_pct": round(float(means["width80"]), 3),
        "score50_pct": round(float(means["is50"]), 3),
        "score80_pct": round(float(means["is80"]), 3),
        "naive_cover80": round(float(means["naive_hit80"]), 4),
        "naive_score80_pct": round(float(means["naive_is80"]), 3),
    }


def history_ablation(cfg: dict, ranges_config: dict, review_config: dict, bars: dict, week_end: date) -> dict:
    """Ablation (b): the walk-forward on stored prices with each variant of the config."""
    benchmark_ticker = benchmark_key(cfg)
    bars = {ticker: frame[frame.index <= pd.Timestamp(week_end)] for ticker, frame in bars.items()}
    if benchmark_ticker not in bars or len(bars[benchmark_ticker]) < ranges_config["warmup_bars"] + 30:
        return {"n": 0, "error": MSG_NOT_ENOUGH_BENCHMARK_BARS, "variants": []}
    dates = list(bars[benchmark_ticker].index)
    index_by_timestamp = {timestamp: index for index, timestamp in enumerate(dates)}
    regimes, majors = history_context(cfg, bars, dates)
    session_dates = [timestamp.date() for timestamp in dates]

    def major_in(date_position: int, horizon: int) -> bool:
        """True when a major market event falls inside the window of N+k from a date position (k + 1 sessions)."""
        end = date_position + window_sessions(horizon)
        return end < len(session_dates) and major_event_between(
            majors, session_dates[date_position], session_dates[end]
        )

    cache, variants = {}, []
    for variant in [{"name": BASELINE, "set": {}}, *review_config["history_variants"]]:
        params = merge(ranges_config, variant.get("set"))
        by_horizon, bar_count = {}, 0
        for horizon in params["horizons"]:
            key = (params["ewma_lambda"], params["warmup_bars"], horizon)
            if key not in cache:
                cache[key] = observations.observations(bars, cfg["tickers"], horizon, params, index_by_timestamp)
            session_rows = cache[key]
            if session_rows.empty:
                continue
            scale = {
                date_position: params["regime_factor"].get(regimes[date_position], 1.0)
                * (params["major_event_factor"] if major_in(date_position, horizon) else 1.0)
                for date_position in range(len(dates))
            }
            summary = hist_summary(
                evaluation.evaluate(session_rows, horizon, params, review_config["history_eval_sessions"], scale=scale)
            )
            by_horizon[f"{horizon}d"] = summary
            bar_count += summary["n"]
        variants.append(
            {"name": variant["name"], "set": variant.get("set") or {}, "n": bar_count, "by_h": by_horizon}
        )
    share = {
        regime: round(
            regimes[-review_config["history_eval_sessions"] :].count(regime)
            / min(len(regimes), review_config["history_eval_sessions"]),
            3,
        )
        for regime in REGIME_ORDER
    }
    return {
        "n": variants[0]["n"] if variants else 0,
        "sessions": review_config["history_eval_sessions"],
        "regime_share": share,
        "variants": variants,
    }
