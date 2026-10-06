"""Ablation (b): walk-forward on stored prices with each input switched off."""
from __future__ import annotations

from datetime import date, timedelta
import numpy as np
import pandas as pd
from marketbrief.replay.backtest import evaluation
from marketbrief.replay.backtest import observations
from marketbrief.core import calendar
from marketbrief.analytics import indicators
from marketbrief.analytics import regime as regime_rules
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.utils.event_dates import major_event_between
from marketbrief.constants.review import BASELINE
from marketbrief.pipeline.review.helpers import merge


def history_context(cfg: dict, bars: dict, dates: list) -> tuple[list[str], list[date]]:
    """Regime per bar date rebuilt from stored bars (as features.py does live, with closes instead
    of pre-open quotes) and the sorted dates of major market events."""
    bench = bars[benchmark_key(cfg)]["close"]
    vk = vol_index_key(cfg)
    vol = bars[vk]["close"].reindex(bench.index) if vk in bars else pd.Series(np.nan, index=bench.index)
    first, last = dates[0].date(), dates[-1].date()
    events = calendar.market_events(cfg, first, last + timedelta(days=30))
    majors = sorted({e["date"] for e in events if e["major"]})
    regimes = []
    for i, d in enumerate(dates):
        tail = bench.iloc[max(0, i - 30): i + 1]
        lvl = None if pd.isna(vol.iloc[i]) else float(vol.iloc[i])
        prev = None if i == 0 or pd.isna(vol.iloc[i - 1]) else float(vol.iloc[i - 1])
        session = dates[i + 1].date() if i + 1 < len(dates) else calendar.next_session(cfg, d.date(), include=False)
        near = calendar.major_events_near(events, session)
        regimes.append(regime_rules.classify(cfg["regime"], lvl, indicators.period_return(tail, 5), indicators.realized_vol(tail), bool(near),
                                   lvl / prev - 1 if lvl and prev else None)[0])
    return regimes, majors


def hist_summary(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    m = res.mean(numeric_only=True)
    return {"n": int(len(res)), "cover50": round(float(m["hit50"]), 4), "cover80": round(float(m["hit80"]), 4),
            "width80_pct": round(float(m["width80"]), 3), "score50_pct": round(float(m["is50"]), 3),
            "score80_pct": round(float(m["is80"]), 3), "naive_cover80": round(float(m["naive_hit80"]), 4),
            "naive_score80_pct": round(float(m["naive_is80"]), 3)}


def history_ablation(cfg: dict, rc: dict, rv: dict, bars: dict, week_end: date) -> dict:
    bkey = benchmark_key(cfg)
    bars = {t: df[df.index <= pd.Timestamp(week_end)] for t, df in bars.items()}
    if bkey not in bars or len(bars[bkey]) < rc["warmup_bars"] + 30:
        return {"n": 0, "error": "not enough benchmark bars", "variants": []}
    dates = list(bars[bkey].index)
    rank = {d: i for i, d in enumerate(dates)}
    regimes, majors = history_context(cfg, bars, dates)
    day = [d.date() for d in dates]

    def major_in(i: int, h: int) -> bool:
        return i + h < len(day) and major_event_between(majors, day[i], day[i + h])

    cache, variants = {}, []
    for v in [{"name": BASELINE, "set": {}}, *rv["history_variants"]]:
        p = merge(rc, v.get("set"))
        by_h, n = {}, 0
        for h in p["horizons"]:
            key = (p["ewma_lambda"], p["warmup_bars"], h)
            if key not in cache:
                cache[key] = observations.observations(bars, cfg["tickers"], h, p, rank)
            obs = cache[key]
            if obs.empty:
                continue
            scale = {i: p["regime_factor"].get(regimes[i], 1.0) * (p["major_event_factor"] if major_in(i, h) else 1.0)
                     for i in range(len(dates))}
            s = hist_summary(evaluation.evaluate(obs, h, p, rv["history_eval_sessions"], scale=scale))
            by_h[f"{h}d"] = s
            n += s["n"]
        variants.append({"name": v["name"], "set": v.get("set") or {}, "n": n, "by_h": by_h})
    share = {k: round(regimes[-rv["history_eval_sessions"]:].count(k) / min(len(regimes), rv["history_eval_sessions"]), 3)
             for k in REGIME_ORDER}
    return {"n": variants[0]["n"] if variants else 0, "sessions": rv["history_eval_sessions"],
            "regime_share": share, "variants": variants}
