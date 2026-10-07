"""The luck test of the scoreboard (F7.1): a percentile bootstrap interval of the mean net return per trade (%),
and the same interval corrected for multiple testing across the m rows compared with one another (same scope,
market, view, basis, company, regime and horizon; Bonferroni: level 1 - alpha / m). Only a corrected interval
that excludes zero counts as an edge. Deterministic: the resampling seed is derived from the slice key."""
from __future__ import annotations

import hashlib

import numpy as np

from marketbrief.lab.constants import BOOTSTRAP_ALPHA, BOOTSTRAP_SAMPLES, PCT_DIGITS

METHOD = ("percentile bootstrap of the mean net return per trade (%), {n} resamples; corrected: Bonferroni over "
          "the m rows compared in the same scope, market, view, basis, company, regime and horizon "
          "(scoreboard.peer_key)")


def seed_of(key: str) -> int:
    """A stable 32-bit seed from a text key."""
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


def bootstrap_means(returns: list[float], key: str, samples: int = BOOTSTRAP_SAMPLES) -> np.ndarray:
    """Sorted means of `samples` resamples with replacement."""
    values = np.asarray(returns, dtype=float)
    rng = np.random.default_rng(seed_of(key))
    picks = rng.integers(0, len(values), size=(samples, len(values)))
    return np.sort(values[picks].mean(axis=1))


def interval(means: np.ndarray, alpha: float) -> tuple[float, float]:
    """The central (1 - alpha) percentile interval of the bootstrap means."""
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def luck_test(returns: list[float], key: str, m: int) -> dict:
    """{method, n, low_pct, high_pct, excludes_zero, m, corrected_low_pct, corrected_high_pct, corrected}; with
    fewer than 2 trades no interval is computed (all null, corrected false)."""
    out = {"method": METHOD.format(n=BOOTSTRAP_SAMPLES), "n": len(returns), "m": m}
    if len(returns) < 2:
        return {**out, "low_pct": None, "high_pct": None, "excludes_zero": False, "corrected_low_pct": None,
                "corrected_high_pct": None, "corrected": False}
    means = bootstrap_means(returns, key)
    low, high = interval(means, BOOTSTRAP_ALPHA)
    corrected_low, corrected_high = interval(means, BOOTSTRAP_ALPHA / max(m, 1))
    return {**out, "low_pct": round(low, PCT_DIGITS), "high_pct": round(high, PCT_DIGITS),
            "excludes_zero": bool(low > 0 or high < 0), "corrected_low_pct": round(corrected_low, PCT_DIGITS),
            "corrected_high_pct": round(corrected_high, PCT_DIGITS),
            "corrected": bool(corrected_low > 0 or corrected_high < 0)}
