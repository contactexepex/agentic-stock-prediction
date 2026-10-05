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

TRADING_DAYS = 252


def ewma_sigma(close: pd.Series, lam: float = 0.94) -> pd.Series:
    """Daily volatility estimate known at each close (uses returns up to and including t)."""
    r = np.log(close / close.shift(1))
    return np.sqrt((r ** 2).ewm(alpha=1 - lam, adjust=False).mean())


def standardized(close: pd.Series, h: int, lam: float = 0.94, warmup: int = 60) -> pd.DataFrame:
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
    tail = (1 - band) / 2
    return tail, 1 - tail


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), cum, v))


def normal_quantiles(band: float) -> tuple[float, float]:
    lo, hi = band_quantiles(band)
    nd = NormalDist()
    return nd.inv_cdf(lo), nd.inv_cdf(hi)


def pool_quantiles(z: np.ndarray, weights: np.ndarray, band: float) -> tuple[float, float]:
    lo, hi = band_quantiles(band)
    return weighted_quantile(z, weights, lo), weighted_quantile(z, weights, hi)


def recency_weights(ages: np.ndarray, half_life: float) -> np.ndarray:
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
    r = np.log(close / close.shift(1)).dropna().iloc[-n:]
    return float(r.std(ddof=1)) if len(r) >= n else None


def horizon_sigma(sigma_daily: float, h: int, earnings_in_horizon: bool, cfg: dict,
                  regime: str, major_event: bool) -> tuple[float, list[str]]:
    """Horizon volatility with event and regime widening. Returns (sigma_h, notes)."""
    notes = []
    var = sigma_daily ** 2 * h
    if earnings_in_horizon:
        m = cfg["earnings_vol_multiple"]
        var += (m ** 2 - 1) * sigma_daily ** 2
        notes.append(f"earnings in horizon (x{m} day)")
    s = math.sqrt(var)
    rf = cfg["regime_factor"].get(regime, 1.0)
    if rf != 1.0:
        s *= rf
        notes.append(f"regime {regime} x{rf}")
    if major_event:
        s *= cfg["major_event_factor"]
        notes.append(f"major event x{cfg['major_event_factor']}")
    return s, notes
