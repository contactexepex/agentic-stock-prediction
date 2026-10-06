"""Scoring of the walk-forward ranges and the off/on comparison of each range input."""

from __future__ import annotations

import math
import pandas as pd
from marketbrief.analytics import range_math
from marketbrief.constants.backtest import INPUT_ARMS


def score(base: float, actual_close: float, center: float, horizon_sigma: float, quantiles: tuple) -> dict:
    """Interval scores and coverage of one range against its outcome."""
    q10, q25, q75, q90 = quantiles
    lo50, hi50 = base * math.exp(center + q25 * horizon_sigma), base * math.exp(center + q75 * horizon_sigma)
    lo80, hi80 = base * math.exp(center + q10 * horizon_sigma), base * math.exp(center + q90 * horizon_sigma)
    return {
        "hit50": lo50 <= actual_close <= hi50,
        "hit80": lo80 <= actual_close <= hi80,
        "width80": 100 * (hi80 - lo80) / base,
        "is80": 100 * range_math.interval_score(lo80, hi80, actual_close, 0.8) / base,
    }


def arm_params(observation, horizon: int, ranges_config: dict, use: dict) -> dict[str, tuple[float, float]]:
    """(centre, horizon sigma) per arm for one observation. `configured` = the inputs switched on
    in config/ranges.yaml for this market; `current` = the formula before these inputs."""
    daily_sigma = observation.sigma
    var = daily_sigma * daily_sigma * horizon
    fixed = ranges_config["earnings_vol_multiple"]
    earn = bool(getattr(observation, "earn", False))
    m_hist = observation.m_hist if earn and observation.m_hist == observation.m_hist else fixed
    horizon_sigma = {
        "core": math.sqrt(var),
        "fixed": math.sqrt(var + (fixed**2 - 1) * daily_sigma * daily_sigma) if earn else math.sqrt(var),
        "hist": math.sqrt(var + (m_hist**2 - 1) * daily_sigma * daily_sigma) if earn else math.sqrt(var),
    }
    own = observation.own if observation.own == observation.own else None
    idx_cue = observation.idx_cue if observation.idx_cue == observation.idx_cue else None
    beta = observation.beta if observation.beta == observation.beta else None
    direct = ranges_config["cue_weight"] * own if own is not None else 0.0
    beta_split = ranges_config["beta_split"]
    split = range_math.beta_split_center(
        beta, idx_cue, own, beta_split["index_weight"], beta_split["own_weight"], ranges_config["cue_weight"]
    )

    def capped_shift(extra, switches):
        """A centre shift limited to the maximum number of sigmas."""
        limit = ranges_config["max_center_shift_sigma"] * switches
        return max(-limit, min(limit, extra))

    div = observation.div_shift
    s_cfg = horizon_sigma["hist"] if use.get("earnings_history") else horizon_sigma["fixed"]
    return {
        "core": (0.0, horizon_sigma["core"]),
        "earn_fixed": (0.0, horizon_sigma["fixed"]),
        "earn_hist": (0.0, horizon_sigma["hist"]),
        "exdiv": (div, horizon_sigma["core"]),
        "cue_direct": (capped_shift(direct, horizon_sigma["core"]), horizon_sigma["core"]),
        "cue_beta": (capped_shift(split, horizon_sigma["core"]), horizon_sigma["core"]),
        "current": (capped_shift(direct, horizon_sigma["fixed"]), horizon_sigma["fixed"]),
        "configured": (
            capped_shift(split if use.get("beta_split") else direct, s_cfg) + (div if use.get("ex_dividend") else 0.0),
            s_cfg,
        ),
    }


def evaluate(
    obs: pd.DataFrame,
    horizon: int,
    ranges_config: dict,
    eval_sessions: int,
    use: dict | None = None,
    *,
    scale: dict[int, float] | None = None,
) -> pd.DataFrame:
    """`use`: the range inputs switched on (config/ranges.yaml) for the per-input arms.
    `scale` (keyword only) widens sigma per start rank (regime/event factors replayed by review.py)."""
    last = int(obs["rank"].max())
    start = last - eval_sessions + 1
    z_all, r_all = obs["z"].to_numpy(), obs["rank"].to_numpy()
    with_inputs = "earn" in obs.columns
    rows = []
    for position in range(start, last + 1):
        known = (r_all + horizon <= position) & (r_all > position - ranges_config["history_sessions"])
        if known.sum() < ranges_config["min_pool"]:
            continue
        weights = range_math.recency_weights(
            (position - r_all[known]).astype(float), ranges_config["half_life_sessions"]
        )
        z_pool = z_all[known]
        quantiles = tuple(range_math.weighted_quantile(z_pool, weights, level) for level in (0.10, 0.25, 0.75, 0.90))
        today = obs[obs["rank"] == position]
        for observation in today.itertuples():
            base, horizon_sigma = (
                observation.close,
                observation.sigma * math.sqrt(horizon) * (scale.get(position, 1.0) if scale else 1.0),
            )
            actual_close = base * math.exp(observation.fwd)
            core = score(base, actual_close, 0.0, horizon_sigma, quantiles)
            lo50, hi50 = base * math.exp(quantiles[1] * horizon_sigma), base * math.exp(quantiles[2] * horizon_sigma)
            n50, n80 = (
                range_math.naive_range(base, observation.s20, horizon, 0.5),
                range_math.naive_range(base, observation.s20, horizon, 0.8),
            )
            row = {
                "rank": position,
                "ticker": observation.ticker,
                "hit50": core["hit50"],
                "hit80": core["hit80"],
                "naive_hit50": n50[0] <= actual_close <= n50[1],
                "naive_hit80": n80[0] <= actual_close <= n80[1],
                "width80": core["width80"],
                "naive_width80": 100 * (n80[1] - n80[0]) / base,
                "is80": core["is80"],
                "naive_is80": 100 * range_math.interval_score(n80[0], n80[1], actual_close, 0.8) / base,
                "is50": 100 * range_math.interval_score(lo50, hi50, actual_close, 0.5) / base,
                "naive_is50": 100 * range_math.interval_score(n50[0], n50[1], actual_close, 0.5) / base,
            }
            if with_inputs:
                row.update(
                    {
                        "earn": bool(observation.earn),
                        "has_div": bool(observation.has_div),
                        "has_cue": bool(observation.has_cue),
                    }
                )
                for arm, (center, sigma_h) in arm_params(observation, horizon, ranges_config, use or {}).items():
                    for key, value in score(base, actual_close, center, sigma_h, quantiles).items():
                        row[f"{arm}_{key}"] = value
            rows.append(row)
    return pd.DataFrame(rows)


def summarize(res: pd.DataFrame) -> dict:
    """Coverage, width and score of a set of backtest rows against the naive baseline."""
    if res.empty:
        return {"n": 0}
    means = res.mean(numeric_only=True)
    return {
        "n": int(len(res)),
        "days": int(res["rank"].nunique()),
        "cover50": round(float(means["hit50"]), 3),
        "cover80": round(float(means["hit80"]), 3),
        "naive_cover50": round(float(means["naive_hit50"]), 3),
        "naive_cover80": round(float(means["naive_hit80"]), 3),
        "width80_pct": round(float(means["width80"]), 2),
        "naive_width80_pct": round(float(means["naive_width80"]), 2),
        "score80": round(float(means["is80"]), 3),
        "naive_score80": round(float(means["naive_is80"]), 3),
    }


def arm_summary(res: pd.DataFrame, arm: str) -> dict:
    """The summary of one arm (a variant of an input) of the backtest."""
    if res.empty:
        return {"n": 0}
    return {
        "n": int(len(res)),
        "cover50": round(float(res[f"{arm}_hit50"].mean()), 3),
        "cover80": round(float(res[f"{arm}_hit80"].mean()), 3),
        "width80_pct": round(float(res[f"{arm}_width80"].mean()), 3),
        "score80": round(float(res[f"{arm}_is80"].mean()), 4),
    }


def verdict(off: dict, on_summary: dict, min_gain: float) -> str:
    """DESIGN section 7 rule: improves only if the interval score drops by more than min_gain
    (relative); a change within it is noise."""
    if not off.get("n"):
        return "no data"
    off_score, on_score = off["score80"], on_summary["score80"]
    if off_score == on_score:
        return "same"
    gain = (off_score - on_score) / off_score
    return "improves" if gain > min_gain else ("worse" if gain < -min_gain else "noise")


def compare_inputs(res: pd.DataFrame, min_gain: float = 0.005) -> dict:
    """Off against on for each range input, scored where the input applies."""
    out = {}
    for name, (off, on_arm, col) in INPUT_ARMS.items():
        sub = res[res[col]] if col in res.columns else res.iloc[0:0]
        off_summary, on_summary = arm_summary(sub, off), arm_summary(sub, on_arm)
        out[name] = {
            "applies": off_summary["n"],
            "off": off_summary,
            "on": on_summary,
            "verdict": verdict(off_summary, on_summary, min_gain),
        }
    if len(res):
        off_summary, on_summary = arm_summary(res, "current"), arm_summary(res, "configured")
        out["all_inputs"] = {
            "applies": int(len(res)),
            "off": off_summary,
            "on": on_summary,
            "verdict": verdict(off_summary, on_summary, min_gain),
        }
    out["implied_vol"] = {"verdict": "live only (no stored option history)"}
    return out
