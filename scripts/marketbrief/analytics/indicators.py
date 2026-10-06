"""PASDS indicator formulas (file 06) on daily bars (library, pure functions).

Input: a DataFrame for one ticker indexed by date (ascending) with open, high, low, close,
volume. Each indicator returns None when there are too few bars (explicit nulls, no guessing).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from marketbrief.constants.indicators import (
    BLOCKED_MISSING,
    EWMA_LAMBDA,
    FAST_CRITICAL,
    JUMP_WARNING_RETURN,
    MSG_JUMP,
    MSG_MISSING,
    QUALITY_BLOCKED,
    QUALITY_OK,
    QUALITY_PARTIAL,
    TRADING_DAYS,
)


def finite_or_none(value) -> float | None:
    """`x` as a float, None for None, NaN and infinities."""
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) or math.isinf(value) else value


def period_return(close: pd.Series, bars_back: int) -> float | None:
    """The return over the last `bars_back` bars (None with too few bars)."""
    if len(close) < bars_back + 1 or close.iloc[-bars_back - 1] <= 0:
        return None
    return finite_or_none(close.iloc[-1] / close.iloc[-bars_back - 1] - 1)


def ema_ratio(close: pd.Series) -> float | None:
    """The 9-bar over the 21-bar exponential moving average."""
    if len(close) < 21:
        return None
    ema_9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
    ema_21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    return finite_or_none(ema_9 / ema_21) if ema_21 else None


def rsi(close: pd.Series, window: int = 14) -> float | None:
    """Wilder RSI on a 0-100 scale."""
    if len(close) < window + 1:
        return None
    diff = close.diff().dropna()
    gain = diff.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean().iloc[-1]
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return finite_or_none(100 - 100 / (1 + gain / loss))


def price_vs_high(bars: pd.DataFrame, window: int = 20) -> float | None:
    """The last close over the highest high of the last `window` bars."""
    if len(bars) < window:
        return None
    highest_high = bars["high"].iloc[-window:].max()
    return finite_or_none(bars["close"].iloc[-1] / highest_high) if highest_high > 0 else None


def atr(bars: pd.DataFrame, window: int = 14) -> float | None:
    """Wilder-smoothed average true range."""
    if len(bars) < window + 1:
        return None
    prev = bars["close"].shift(1)
    true_range = (
        pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()], axis=1)
        .max(axis=1)
        .iloc[1:]
    )
    return finite_or_none(true_range.ewm(alpha=1 / window, adjust=False).mean().iloc[-1])


def log_returns(close: pd.Series) -> pd.Series:
    """Daily log returns without the first (empty) one."""
    return np.log(close / close.shift(1)).dropna()


def realized_vol(close: pd.Series, window: int = 10) -> float | None:
    """Annualized standard deviation of the last `window` daily log returns."""
    if len(close) < window + 1:
        return None
    return finite_or_none(log_returns(close).iloc[-window:].std(ddof=1) * math.sqrt(TRADING_DAYS))


def ewma_vol(close: pd.Series, lam: float = EWMA_LAMBDA, min_bars: int = 30) -> float | None:
    """Exponentially weighted volatility, annualized; recent days count more."""
    if len(close) < min_bars + 1:
        return None
    squared_returns = log_returns(close) ** 2
    var = squared_returns.ewm(alpha=1 - lam, adjust=False).mean().iloc[-1]
    return finite_or_none(math.sqrt(var * TRADING_DAYS))


def bb_width(close: pd.Series, length: int = 20) -> float | None:
    """Bollinger band width (4 standard deviations) over the n-bar mean."""
    if len(close) < length:
        return None
    window = close.iloc[-length:]
    sma = window.mean()
    return finite_or_none(4 * window.std(ddof=0) / sma) if sma else None


def obv_trend(bars: pd.DataFrame, window: int = 5) -> float | None:
    """Change of on-balance volume over `window` bars relative to its starting size, limited to -2..2."""
    if len(bars) < window + 1:
        return None
    sign = np.sign(bars["close"].diff().fillna(0))
    obv = (sign * bars["volume"]).cumsum()
    base = obv.iloc[-window - 1]
    if abs(base) < 1:
        return 0.0
    return finite_or_none(max(-2.0, min(2.0, (obv.iloc[-1] - base) / abs(base))))


def volume_ratio(bars: pd.DataFrame, window: int = 20) -> float | None:
    """The last volume over the mean of the last `window` bars."""
    if len(bars) < window:
        return None
    average_volume = bars["volume"].iloc[-window:].mean()
    return finite_or_none(bars["volume"].iloc[-1] / average_volume) if average_volume > 0 else None


def beta(close: pd.Series, bench: pd.Series, window: int = TRADING_DAYS, min_obs: int = 60) -> float | None:
    """Beta of daily log returns vs the benchmark over the last `window` common days."""
    joined = pd.concat([log_returns(close), log_returns(bench)], axis=1, join="inner").dropna()
    joined = joined.iloc[-window:]
    if len(joined) < min_obs:
        return None
    var = joined.iloc[:, 1].var(ddof=1)
    return finite_or_none(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / var) if var else None


def compute(bars: pd.DataFrame, bench: pd.Series | None = None) -> dict:
    """All per-ticker indicators for the last bar in df."""
    bars = bars.sort_index()
    close = bars["close"]
    out = {
        "close": finite_or_none(close.iloc[-1]) if len(close) else None,
        "bars": int(len(bars)),
        "ret_1d": period_return(close, 1),
        "ret_3d": period_return(close, 3),
        "ret_5d": period_return(close, 5),
        "ret_20d": period_return(close, 20),
        "ema_ratio": ema_ratio(close),
        "rsi_14": rsi(close),
        "roc_10": period_return(close, 10),
        "price_vs_20d_high": price_vs_high(bars),
        "atr_14": atr(bars),
        "realized_vol_10d": realized_vol(close),
        "ewma_vol": ewma_vol(close),
        "bb_width": bb_width(close),
        "obv_trend": obv_trend(bars),
        "volume_ratio_20d": volume_ratio(bars),
        "beta_1y": beta(close, bench) if bench is not None else None,
    }
    out["atr_pct"] = finite_or_none(out["atr_14"] / out["close"]) if out["atr_14"] and out["close"] else None
    warnings = []
    if out["ret_1d"] is not None and abs(out["ret_1d"]) > JUMP_WARNING_RETURN:
        warnings.append(MSG_JUMP)
    missing = [indicator_name for indicator_name in FAST_CRITICAL if out[indicator_name] is None]
    if missing:
        warnings.append(MSG_MISSING + ", ".join(missing))
    # PASDS 9.2: more than 3 critical nulls blocks the ticker
    too_many_missing = len(missing) > BLOCKED_MISSING
    out["quality"] = QUALITY_BLOCKED if too_many_missing else (QUALITY_PARTIAL if warnings else QUALITY_OK)
    out["warnings"] = warnings
    return out
