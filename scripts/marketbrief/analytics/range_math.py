"""Range engine math (library, pure functions).

A range for horizon h is  base * exp(center + q * sigma_h)  where
- sigma_h = daily EWMA volatility * sqrt(h), widened for events and regime,
- q = empirical quantiles of standardized returns z = log(C[t+h]/C[t]) / (sigma_t * sqrt(h)),
  pooled across the market's tickers and weighted by recency (fat tails come for free),
- center = small capped drift from overnight cues and the AI's call.
Self-calibration = recomputing the quantiles daily with live scored ranges added to the pool.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from marketbrief.constants.range_math import (DAYS_PER_YEAR, EWMA_LAMBDA, MSG_EARNINGS_IN_HORIZON, MSG_MAJOR_EVENT,
                                              MSG_REGIME, MIN_EXPIRY_DAYS, WARMUP_SESSIONS)



def ewma_sigma(close: pd.Series, lam: float = EWMA_LAMBDA) -> pd.Series:
    """Daily volatility estimate known at each close (uses returns up to and including t)."""
    r = np.log(close / close.shift(1))
    return np.sqrt((r ** 2).ewm(alpha=1 - lam, adjust=False).mean())


def standardized(close: pd.Series, h: int, lam: float = EWMA_LAMBDA, warmup: int = WARMUP_SESSIONS) -> pd.DataFrame:
    """Per start date t: z = log(C[t+h]/C[t]) / (sigma_t sqrt(h)). Only dates with a known outcome."""
    close = close.sort_index()
    sig = ewma_sigma(close, lam)
    fwd = np.log(close.shift(-h) / close)
    df = pd.DataFrame({"sigma": sig, "fwd": fwd})
    df = df.iloc[warmup:]
    df = df[(df["sigma"] > 0) & df["fwd"].notna()]
    df["z"] = df["fwd"] / (df["sigma"] * math.sqrt(h))
    return df


def band_quantiles(band: float) -> tuple[float, float]:
    """The lower and upper tail probabilities of a central band (0.8 -> 0.1, 0.9)."""
    tail = (1 - band) / 2
    return tail, 1 - tail


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """The q-quantile of weighted values (linear interpolation between the cumulative weights)."""
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), cum, v))


def normal_quantiles(band: float) -> tuple[float, float]:
    """The standard normal quantiles of a central band's tails."""
    lo, hi = band_quantiles(band)
    nd = NormalDist()
    return nd.inv_cdf(lo), nd.inv_cdf(hi)


def pool_quantiles(z: np.ndarray, weights: np.ndarray, band: float) -> tuple[float, float]:
    """The weighted quantiles of the pooled standardized returns for a central band."""
    lo, hi = band_quantiles(band)
    return weighted_quantile(z, weights, lo), weighted_quantile(z, weights, hi)


def recency_weights(ages: np.ndarray, half_life: float) -> np.ndarray:
    """Weights that halve every `half_life` age units."""
    return np.power(0.5, ages / half_life)


def interval_score(lo: float, hi: float, y: float, band: float) -> float:
    """Gneiting-Raftery interval score: width plus a penalty for misses. Lower is better."""
    alpha = 1 - band
    return (hi - lo) + (2 / alpha) * max(0.0, lo - y) + (2 / alpha) * max(0.0, y - hi)


def naive_range(base: float, sigma20_daily: float, h: int, band: float) -> tuple[float, float]:
    """Baseline: last close +/- the recent typical move (20-day vol, normal quantiles)."""
    zlo, zhi = normal_quantiles(band)
    s = sigma20_daily * math.sqrt(h)
    return base * math.exp(zlo * s), base * math.exp(zhi * s)


def realized_sigma(close: pd.Series, n: int = 20) -> float | None:
    """The standard deviation of the last n daily log returns (None with too few)."""
    r = np.log(close / close.shift(1)).dropna().iloc[-n:]
    return float(r.std(ddof=1)) if len(r) >= n else None


def horizon_sigma(sigma_daily: float, h: int, earnings_in_horizon: bool, cfg: dict,  # noqa: PLR0913
                  regime: str, major_event: bool, earnings_multiple: float | None = None,
                  earnings_note: str = "") -> tuple[float, list[str]]:
    """Horizon volatility with event and regime widening. Returns (sigma_h, notes).
    earnings_multiple overrides the fixed `earnings_vol_multiple` (past moves or options)."""
    notes = []
    var = sigma_daily ** 2 * h
    if earnings_in_horizon:
        m = earnings_multiple if earnings_multiple is not None else cfg["earnings_vol_multiple"]
        var += (m ** 2 - 1) * sigma_daily ** 2
        notes.append(MSG_EARNINGS_IN_HORIZON.format(multiple=m if earnings_multiple is None else round(m, 2),
                                                      note=earnings_note))
    s = math.sqrt(var)
    rf = cfg["regime_factor"].get(regime, 1.0)
    if rf != 1.0:
        s *= rf
        notes.append(MSG_REGIME.format(regime=regime, factor=rf))
    if major_event:
        s *= cfg["major_event_factor"]
        notes.append(MSG_MAJOR_EVENT.format(factor=cfg["major_event_factor"]))
    return s, notes


# ---------- range inputs (docs/DESIGN.md section 4; switches in config/ranges.yaml) ----------

def earnings_multiple(moves: list[tuple[float, float, int]], fixed: float, min_events: int,
                      prior_events: float, max_multiple: float) -> tuple[float, int]:
    """How many normal days an earnings day moves like, from past earnings reactions.

    moves: (log move over the reaction window, daily sigma before it, sessions in the window).
    A window of k sessions holds the earnings day plus k-1 normal days, so each event gives
    x = (move / sigma)^2 - (k - 1), an estimate of the earnings day's variance in normal-day
    units. The mean is shrunk towards `fixed`^2 as if the fixed multiple were `prior_events`
    events, and too few events fall back to `fixed`. Returns (multiple, events used)."""
    xs = [r * r / (s * s) - (k - 1) for r, s, k in moves if s and s > 0 and math.isfinite(r)]
    n = len(xs)
    if n < min_events:
        return fixed, n
    m2 = max(1.0, float(np.mean(xs)))
    m2 = (n * m2 + prior_events * fixed ** 2) / (n + prior_events)
    return min(math.sqrt(m2), max_multiple), n


def implied_variance(iv: float, calendar_days: float) -> float:
    """Total log-return variance to expiry implied by an annualized (365-day) implied vol."""
    return iv * iv * max(calendar_days, MIN_EXPIRY_DAYS) / DAYS_PER_YEAR


def implied_earnings_multiple(total_var: float, sessions: int, sigma_daily: float,
                              max_multiple: float) -> float:
    """Options-implied earnings day: implied variance to expiry minus the other sessions at the
    normal daily variance, in normal-day units (at least 1)."""
    if sigma_daily <= 0:
        return 1.0
    e = total_var - max(sessions - 1, 0) * sigma_daily ** 2
    return min(math.sqrt(max(1.0, e / sigma_daily ** 2)), max_multiple)


def blend_sigma(sigma_daily: float, implied_daily_var: float, weight: float) -> float:
    """Variance blend of the realized (EWMA) and implied daily volatility."""
    return math.sqrt((1 - weight) * sigma_daily ** 2 + weight * implied_daily_var)


def ex_dividend_shift(base: float, amounts: list[float]) -> float:
    """Log shift of the centre for dividends going ex inside the horizon (price drops by them)."""
    shift = 0.0
    for a in amounts:
        if a and a > 0 and a < 0.5 * base:
            shift += math.log(1 - a / base)
    return shift


def beta_split_center(beta: float | None, index_cue: float | None, own_cue: float | None,
                      index_weight: float, own_weight: float, cue_weight: float) -> float:
    """Centre from overnight cues (log moves): beta x expected index move plus the stock's own
    cue net of that. Falls back to the direct own cue when there is no index cue or beta."""
    if index_cue is None or beta is None:
        return cue_weight * own_cue if own_cue is not None else 0.0
    market = beta * index_cue
    out = index_weight * market
    if own_cue is not None:
        out += own_weight * (own_cue - market)
    return out
