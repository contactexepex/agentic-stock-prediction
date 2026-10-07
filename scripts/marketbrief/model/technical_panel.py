"""The PASDS indicators of one ticker at every date, causally (library, pure functions).

The value at date d uses only bars up to d and equals marketbrief.analytics.indicators.compute on the
frame cut at d (tests/test_signal_model.py checks it): every rolling window ends at d and every
exponential smoothing starts at the first bar, as indicators.py does on a cut frame."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from marketbrief.constants.indicators import EWMA_LAMBDA, TRADING_DAYS

RSI_BARS, EMA_FAST, EMA_SLOW, HIGH_BARS, ATR_BARS = 14, 9, 21, 20, 14
VOL_BARS, EWMA_MIN_BARS, BB_BARS, OBV_BARS, VOLUME_BARS = 10, 30, 20, 5, 20
BETA_BARS, BETA_MIN_OBS, OBV_LIMIT = TRADING_DAYS, 60, 2.0


def period_returns(close: pd.Series, bars: int) -> pd.Series:
    """close / close `bars` rows earlier - 1 (NaN where that close is missing or not positive)."""
    base = close.shift(bars)
    return (close / base - 1).where(base > 0)


def rsi_series(close: pd.Series, bars: int = RSI_BARS) -> pd.Series:
    """Wilder RSI at every row (indicators.rsi on the frame cut there)."""
    diff = close.diff()
    gain = diff.clip(lower=0).iloc[1:].ewm(alpha=1 / bars, adjust=False).mean()
    loss = (-diff.clip(upper=0)).iloc[1:].ewm(alpha=1 / bars, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + gain / loss)
    out = out.where(loss != 0, np.where(gain > 0, 100.0, 50.0)).reindex(close.index)
    out.iloc[:bars] = np.nan
    return out


def ema_ratio_series(close: pd.Series) -> pd.Series:
    """EMA(9) / EMA(21), from the 21st bar on."""
    out = close.ewm(span=EMA_FAST, adjust=False).mean() / close.ewm(span=EMA_SLOW, adjust=False).mean()
    out.iloc[:EMA_SLOW - 1] = np.nan
    return out


def atr_series(frame: pd.DataFrame) -> pd.Series:
    """Wilder ATR(14), from the 15th bar on."""
    prev = frame["close"].shift(1)
    true_range = pd.concat([frame["high"] - frame["low"], (frame["high"] - prev).abs(), (frame["low"] - prev).abs()],
                           axis=1).max(axis=1).iloc[1:]
    out = true_range.ewm(alpha=1 / ATR_BARS, adjust=False).mean().reindex(frame.index)
    out.iloc[:ATR_BARS] = np.nan
    return out


def log_returns(close: pd.Series) -> pd.Series:
    """Daily log returns (the first row NaN)."""
    return np.log(close / close.shift(1))


def realized_vol_series(close: pd.Series, bars: int = VOL_BARS) -> pd.Series:
    """Annualised standard deviation of the last `bars` log returns."""
    return log_returns(close).rolling(bars).std(ddof=1) * math.sqrt(TRADING_DAYS)


def ewma_vol_series(close: pd.Series) -> pd.Series:
    """Exponentially weighted volatility (lambda EWMA_LAMBDA), annualised, from bar 31 on."""
    squared = (log_returns(close) ** 2).iloc[1:]
    out = np.sqrt(squared.ewm(alpha=1 - EWMA_LAMBDA, adjust=False).mean() * TRADING_DAYS).reindex(close.index)
    out.iloc[:EWMA_MIN_BARS] = np.nan
    return out


def bb_width_series(close: pd.Series) -> pd.Series:
    """Bollinger width: 4 population standard deviations over the 20-bar mean."""
    mean = close.rolling(BB_BARS).mean()
    return (4 * close.rolling(BB_BARS).std(ddof=0) / mean).where(mean != 0)


def obv_trend_series(frame: pd.DataFrame) -> pd.Series:
    """5-bar change of on-balance volume relative to its start, limited to -2..2 (0 when the start is ~0)."""
    obv = (np.sign(frame["close"].diff().fillna(0)) * frame["volume"]).cumsum()
    base = obv.shift(OBV_BARS)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = ((obv - base) / base.abs()).clip(-OBV_LIMIT, OBV_LIMIT)
    return out.where(base.abs() >= 1, 0.0).where(base.notna())


def volume_ratio_series(frame: pd.DataFrame) -> pd.Series:
    """The last volume over the mean of the last 20."""
    mean = frame["volume"].rolling(VOLUME_BARS).mean()
    return (frame["volume"] / mean).where(mean > 0)


def beta_series(close: pd.Series, bench_close: pd.Series) -> pd.Series:
    """Beta of daily log returns vs the benchmark over the last 252 common days (at least 60)."""
    joined = pd.concat([log_returns(close), log_returns(bench_close)], axis=1, join="inner").dropna()
    joined.columns = ["own", "bench"]
    cov = joined["own"].rolling(BETA_BARS, min_periods=BETA_MIN_OBS).cov(joined["bench"])
    var = joined["bench"].rolling(BETA_BARS, min_periods=BETA_MIN_OBS).var(ddof=1)
    return (cov / var).where(var != 0).reindex(close.index)


def ticker_indicators(frame: pd.DataFrame, bench_close: pd.Series | None) -> pd.DataFrame:
    """Every model indicator of one ticker at every date of its frame, plus `bars` (rows so far)."""
    frame = frame.sort_index()
    close = frame["close"]
    out = pd.DataFrame(index=frame.index)
    out["close"], out["open"] = close, frame["open"]
    out["bars"] = np.arange(1, len(frame) + 1)
    for bars, name in ((1, "ret_1d"), (3, "ret_3d"), (5, "ret_5d"), (20, "ret_20d"), (10, "roc_10")):
        out[name] = period_returns(close, bars)
    out["ema_ratio"] = ema_ratio_series(close)
    out["rsi_14"] = rsi_series(close)
    high = frame["high"].rolling(HIGH_BARS).max()
    out["price_vs_20d_high"] = (close / high).where(high > 0)
    out["atr_pct"] = atr_series(frame) / close
    out["realized_vol_10d"] = realized_vol_series(close)
    out["ewma_vol"] = ewma_vol_series(close)
    out["bb_width"] = bb_width_series(close)
    out["obv_trend"] = obv_trend_series(frame)
    out["volume_ratio_20d"] = volume_ratio_series(frame)
    out["beta_1y"] = beta_series(close, bench_close) if bench_close is not None else np.nan
    return out.replace([np.inf, -np.inf], np.nan)
