"""The overnight index cue of the range centre (beta split): the beta of the benchmark's daily move on the cue's
previous-session move, fitted from stored bars or set in the market config (`index_cue`)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.constants.range_inputs import BETA_FIT, DEFAULT_BETA, MIN_CUE_OBSERVATIONS
from marketbrief.core.market_config import benchmark_key


def log_returns(close: pd.Series) -> pd.Series:
    """Daily log returns (the first one is NaN)."""
    return np.log(close / close.shift(1))


def fit_cue_beta(bench: pd.Series, cue: pd.Series, upto: pd.Timestamp | None, sessions: int,
                 min_obs: int = MIN_CUE_OBSERVATIONS) -> float | None:
    """Slope of the benchmark's daily log return on the cue's previous-session log return (the
    last cue session strictly before the benchmark date), over the last `sessions` benchmark sessions."""
    bench_returns = log_returns(bench).dropna()
    cue_returns = log_returns(cue).dropna()
    if upto is not None:
        bench_returns = bench_returns[bench_returns.index <= upto]
    bench_returns = bench_returns.iloc[-sessions:]
    if len(bench_returns) < min_obs or cue_returns.empty:
        return None
    left = pd.DataFrame({"date": bench_returns.index, "rb": bench_returns.to_numpy()})
    right = pd.DataFrame({"date": cue_returns.index, "rc": cue_returns.to_numpy()})
    joined = pd.merge_asof(left, right, on="date", allow_exact_matches=False).dropna()
    if len(joined) < min_obs or joined["rc"].var() == 0:
        return None
    return float(joined["rb"].cov(joined["rc"]) / joined["rc"].var())


def index_cue_beta(cfg: dict, bars: dict, range_config: dict, upto: pd.Timestamp | None = None) -> float | None:
    """The beta of the market's index cue: the configured number, or the fit from stored bars."""
    cue_config = cfg.get("index_cue") or {}
    if not cue_config.get("symbol"):
        return None
    beta = cue_config.get("beta", DEFAULT_BETA)
    if beta != BETA_FIT:
        return float(beta)
    bench, cue = bars.get(benchmark_key(cfg)), bars.get(cue_config["symbol"])
    if bench is None or cue is None:
        return None
    return fit_cue_beta(bench["close"], cue["close"], upto, int(range_config["beta_split"]["fit_sessions"]))


def clip_beta(beta, range_config: dict) -> float | None:
    """The beta limited to the configured `beta_clip` range (None stays None)."""
    if beta is None or pd.isna(beta):
        return None
    low, high = range_config["beta_split"]["beta_clip"]
    return min(max(float(beta), low), high)
