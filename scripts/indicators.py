"""PASDS indicator formulas (file 06) on daily bars (library, pure functions).

Input: a DataFrame for one ticker indexed by date (ascending) with open, high, low, close,
volume. Each indicator returns None when there are too few bars (explicit nulls, no guessing).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
EWMA_LAMBDA = 0.94  # RiskMetrics daily decay


def _f(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else x


def ret(close: pd.Series, n: int) -> float | None:
    if len(close) < n + 1 or close.iloc[-n - 1] <= 0:
        return None
    return _f(close.iloc[-1] / close.iloc[-n - 1] - 1)


def ema_ratio(close: pd.Series) -> float | None:
    if len(close) < 21:
        return None
    e9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
    e21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    return _f(e9 / e21) if e21 else None


def rsi(close: pd.Series, n: int = 14) -> float | None:
    """Wilder RSI on a 0-100 scale."""
    if len(close) < n + 1:
        return None
    diff = close.diff().dropna()
    gain = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return _f(100 - 100 / (1 + gain / loss))


def price_vs_high(df: pd.DataFrame, n: int = 20) -> float | None:
    if len(df) < n:
        return None
    hi = df["high"].iloc[-n:].max()
    return _f(df["close"].iloc[-1] / hi) if hi > 0 else None


def atr(df: pd.DataFrame, n: int = 14) -> float | None:
    """Wilder-smoothed average true range."""
    if len(df) < n + 1:
        return None
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
                   axis=1).max(axis=1).iloc[1:]
    return _f(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


def realized_vol(close: pd.Series, n: int = 10) -> float | None:
    if len(close) < n + 1:
        return None
    return _f(log_returns(close).iloc[-n:].std(ddof=1) * math.sqrt(TRADING_DAYS))


def ewma_vol(close: pd.Series, lam: float = EWMA_LAMBDA, min_bars: int = 30) -> float | None:
    """Exponentially weighted volatility, annualized; recent days count more."""
    if len(close) < min_bars + 1:
        return None
    r2 = log_returns(close) ** 2
    var = r2.ewm(alpha=1 - lam, adjust=False).mean().iloc[-1]
    return _f(math.sqrt(var * TRADING_DAYS))


def bb_width(close: pd.Series, n: int = 20) -> float | None:
    if len(close) < n:
        return None
    window = close.iloc[-n:]
    sma = window.mean()
    return _f(4 * window.std(ddof=0) / sma) if sma else None


def obv_trend(df: pd.DataFrame, n: int = 5) -> float | None:
    if len(df) < n + 1:
        return None
    sign = np.sign(df["close"].diff().fillna(0))
    obv = (sign * df["volume"]).cumsum()
    base = obv.iloc[-n - 1]
    if abs(base) < 1:
        return 0.0
    return _f(max(-2.0, min(2.0, (obv.iloc[-1] - base) / abs(base))))


def volume_ratio(df: pd.DataFrame, n: int = 20) -> float | None:
    if len(df) < n:
        return None
    avg = df["volume"].iloc[-n:].mean()
    return _f(df["volume"].iloc[-1] / avg) if avg > 0 else None


def beta(close: pd.Series, bench: pd.Series, n: int = TRADING_DAYS, min_obs: int = 60) -> float | None:
    """Beta of daily log returns vs the benchmark over the last n common days."""
    joined = pd.concat([log_returns(close), log_returns(bench)], axis=1, join="inner").dropna()
    joined = joined.iloc[-n:]
    if len(joined) < min_obs:
        return None
    var = joined.iloc[:, 1].var(ddof=1)
    return _f(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / var) if var else None


FAST_CRITICAL = ("ret_1d", "ret_5d", "ema_ratio", "rsi_14", "atr_14", "realized_vol_10d")


def compute(df: pd.DataFrame, bench: pd.Series | None = None) -> dict:
    """All per-ticker indicators for the last bar in df."""
    df = df.sort_index()
    c = df["close"]
    out = {
        "close": _f(c.iloc[-1]) if len(c) else None,
        "bars": int(len(df)),
        "ret_1d": ret(c, 1), "ret_3d": ret(c, 3), "ret_5d": ret(c, 5), "ret_20d": ret(c, 20),
        "ema_ratio": ema_ratio(c), "rsi_14": rsi(c), "roc_10": ret(c, 10),
        "price_vs_20d_high": price_vs_high(df), "atr_14": atr(df),
        "realized_vol_10d": realized_vol(c), "ewma_vol": ewma_vol(c),
        "bb_width": bb_width(c), "obv_trend": obv_trend(df), "volume_ratio_20d": volume_ratio(df),
        "beta_1y": beta(c, bench) if bench is not None else None,
    }
    out["atr_pct"] = _f(out["atr_14"] / out["close"]) if out["atr_14"] and out["close"] else None
    warnings = []
    if out["ret_1d"] is not None and abs(out["ret_1d"]) > 0.4:
        warnings.append("price jump over 40% in one day: possible unadjusted split or bad bar")
    missing = [k for k in FAST_CRITICAL if out[k] is None]
    if missing:
        warnings.append("missing: " + ", ".join(missing))
    # PASDS 9.2: more than 3 critical nulls blocks the ticker
    out["quality"] = "BLOCKED" if len(missing) > 3 else ("PARTIAL" if warnings else "OK")
    out["warnings"] = warnings
    return out
