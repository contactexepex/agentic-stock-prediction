"""Statistics of the replay: Wilson and binomial tests, clustered interval, coverage, baselines."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from marketbrief.analytics import scoring
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.utils.numbers import round_or_none
from marketbrief.constants.replay import LEVELS, RSI_HIGH, RSI_LOW, SIGNAL_LABELS


wilson = scoring.wilson  # Wilson score interval (scoring.py)


def binom_p_two_sided(hits: int, trials: int, probability: float = 0.5) -> float | None:
    """Exact two-sided binomial test (sum of outcomes no more likely than `hits`)."""
    if not trials:
        return None

    def log_probability(index):
        """The log of the binomial probability of `index` successes."""
        return (
            math.lgamma(trials + 1)
            - math.lgamma(index + 1)
            - math.lgamma(trials - index + 1)
            + index * math.log(probability)
            + (trials - index) * math.log(1 - probability)
        )

    ref = log_probability(hits)
    total = sum(math.exp(log_probability(index)) for index in range(trials + 1) if log_probability(index) <= ref + 1e-9)
    return min(1.0, total)


def clustered_ci(values: np.ndarray, blocks: np.ndarray, z_critical: float = 1.96) -> tuple[float | None, float | None]:
    """95% interval of a mean when rows in the same date block move together (all stocks share a
    day; 5-day outcomes overlap): ratio estimator with block-level residuals."""
    count = len(values)
    if count == 0:
        return None, None
    block_mean = float(values.mean())
    frame = pd.DataFrame({"v": values - block_mean, "b": blocks})
    block_sums = frame.groupby("b")["v"].sum().to_numpy()
    block_count = len(block_sums)
    if block_count < 2:
        return None, None
    standard_error = math.sqrt((block_sums**2).sum() * block_count / (block_count - 1)) / count
    return block_mean - z_critical * standard_error, block_mean + z_critical * standard_error


def range_summary(group: pd.DataFrame, horizon: int) -> dict:
    """Coverage, width, scores and naive baseline of the scored rows."""
    group = group[group["actual"].notna()] if "actual" in group.columns else group.iloc[0:0]
    if group.empty:
        return {"n": 0}
    blocks = (group["rank"] // max(horizon, 1)).to_numpy()
    hit80 = group["hit80"].astype(float).to_numpy()
    lower, upper = clustered_ci(hit80, blocks)
    naive_rows = group[group["naive_hit80"].notna()] if "naive_hit80" in group.columns else group.iloc[0:0]
    out = {
        "n": int(len(group)),
        "days": int(group["date"].nunique()),
        "cover50": round_or_none(group["hit50"].mean()),
        "cover80": round_or_none(group["hit80"].mean()),
        "cover80_ci": [round_or_none(lower), round_or_none(upper)],
        "width50_pct": round_or_none(group["width50"].mean(), 3),
        "width80_pct": round_or_none(group["width80"].mean(), 3),
        "score50": round_or_none(group["is50"].mean(), 3),
        "score80": round_or_none(group["is80"].mean(), 3),
        "qs_pct": round_or_none(group["qs"].mean(), 4) if "qs" in group else None,
        "abs_err_pct": round_or_none(group["abs_err"].mean(), 3),
    }
    if len(naive_rows):
        out.update(
            {
                "naive_n": int(len(naive_rows)),
                "naive_cover50": round_or_none(naive_rows["naive_hit50"].astype(float).mean()),
                "naive_cover80": round_or_none(naive_rows["naive_hit80"].astype(float).mean()),
                "naive_width80_pct": round_or_none(naive_rows["naive_width80"].mean(), 3),
                "naive_score50": round_or_none(naive_rows["naive_is50"].mean(), 3),
                "naive_score80": round_or_none(naive_rows["naive_is80"].mean(), 3),
                "score80_same_rows": round_or_none(naive_rows["is80"].mean(), 3),
            }
        )
    return out


def calibration(group: pd.DataFrame) -> list[dict]:
    """Stated against actual coverage over the levels of the calibration curve."""
    group = group[group["actual"].notna()] if "actual" in group.columns else group.iloc[0:0]
    if group.empty:
        return []
    pit = group["pit"].to_numpy()
    out = []
    for level in LEVELS:
        lower, upper = 0.5 - level / 2, 0.5 + level / 2
        out.append(
            {
                "stated": level,
                "actual": round_or_none(((pit >= lower) & (pit <= upper)).mean()),
                "published": level in (0.5, 0.8),
            }
        )
    for point in out:  # the published bands are scored on the bands themselves
        if point["stated"] == 0.5:
            point["actual"] = round_or_none(group["hit50"].mean())
        elif point["stated"] == 0.8:
            point["actual"] = round_or_none(group["hit80"].mean())
    return out


def signals(group: pd.DataFrame) -> dict[str, pd.Series]:
    """Direction per row: +1 up, -1 down, 0 abstain."""
    sgn = lambda series: np.sign(series.fillna(0.0))  # noqa: E731
    rsi = group["rsi"]
    return {
        "always_up": pd.Series(1.0, index=group.index),
        "momentum_1d": sgn(group["ret1"]),
        "momentum_5d": sgn(group["ret5"]),
        "rsi_reversion": pd.Series(
            np.where(rsi < RSI_LOW, 1.0, np.where(rsi > RSI_HIGH, -1.0, 0.0)), index=group.index
        ),
    }


def baseline_stats(group: pd.DataFrame, horizon: int) -> dict:
    """Hit rate per baseline signal (a flat close is a miss for both directions, as score_predictions.py)."""
    group = group[group["actual"].notna()] if "actual" in group.columns else group.iloc[0:0]
    if group.empty:
        return {}
    up_moves, down = group["fwd"] > 0, group["fwd"] < 0
    au_hit = up_moves.astype(float)
    blocks = (group["rank"] // max(horizon, 1)).to_numpy()
    out = {}
    for name, signal in signals(group).items():
        call = signal != 0
        hit = ((signal > 0) & up_moves) | ((signal < 0) & down)
        calls, hit_count = int(call.sum()), int(hit[call].sum())
        rate = hit_count / calls if calls else None
        lower, upper = clustered_ci(hit[call].astype(float).to_numpy(), blocks[call.to_numpy()])
        wilson_lower, wilson_upper = wilson(hit_count, calls)
        diff = (hit[call].astype(float) - au_hit[call]).to_numpy()
        dlo, dhi = clustered_ci(diff, blocks[call.to_numpy()])
        out[name] = {
            "label": SIGNAL_LABELS[name],
            "calls": calls,
            "coverage": round_or_none(calls / len(group)),
            "hits": hit_count,
            "hit_rate": round_or_none(rate),
            "ci95": [round_or_none(lower), round_or_none(upper)],
            "ci95_iid": [round_or_none(wilson_lower), round_or_none(wilson_upper)],
            "p_vs_50": None if not calls else float(f"{binom_p_two_sided(hit_count, calls):.3g}"),
            "always_up_same_rows": round_or_none(au_hit[call].mean()) if calls else None,
            "diff_vs_always_up": round_or_none(diff.mean()) if calls else None,
            "diff_ci95": [round_or_none(dlo), round_or_none(dhi)],
        }
    return out


def summarize(cfg: dict, _ranges_config: dict, res: dict[int, pd.DataFrame], reg: pd.DataFrame) -> dict:
    """The statistics of a replay: by horizon, regime, sector, ticker, month, year and baselines."""
    sector = {ticker: metadata.get("sector") or "Other" for ticker, metadata in cfg["tickers"].items()}
    out = {"horizons": {}, "baselines": {}}
    for horizon, group in res.items():
        if group.empty:
            out["horizons"][str(horizon)] = {"overall": {"n": 0}}
            continue
        group = group.assign(
            sector=group["ticker"].map(sector),
            month=group["date"].map(lambda day: day.strftime("%Y-%m")),
            year=group["date"].map(lambda day: str(day.year)),
        )
        horizon_summary = {
            "overall": range_summary(group, horizon),
            "unscored_rows": int(group["actual"].isna().sum()) if "actual" in group else len(group),
            "calibration": calibration(group),
        }
        for key, col in (
            ("by_regime", "regime"),
            ("by_sector", "sector"),
            ("by_ticker", "ticker"),
            ("by_month", "month"),
            ("by_year", "year"),
        ):
            horizon_summary[key] = {
                str(group_key): range_summary(item, horizon) for group_key, item in group.groupby(col)
            }
        horizon_summary["by_regime"] = {
            regime: horizon_summary["by_regime"][regime]
            for regime in REGIME_ORDER
            if regime in horizon_summary["by_regime"]
        }
        horizon_summary["by_earnings"] = {
            "earnings in horizon": range_summary(group[group["earn"]], horizon),
            "no earnings": range_summary(group[~group["earn"]], horizon),
        }
        horizon_summary["by_major_event"] = {
            "major event in horizon": range_summary(group[group["major"]], horizon),
            "no major event": range_summary(group[~group["major"]], horizon),
        }
        scored = group[group["actual"].notna()] if "actual" in group else group.iloc[0:0]
        horizon_summary["calendar_mismatch"] = (
            int((scored["bar_target"] != scored["target_date"]).sum()) if len(scored) else 0
        )
        horizon_summary["pool_fallback_days"] = int(group.loc[group["q_source"] == "normal", "date"].nunique())
        last = group[group["date"] == group["date"].max()]
        horizon_summary["alpha"] = {
            "mean50": round_or_none(group["alpha50"].mean()),
            "mean80": round_or_none(group["alpha80"].mean()),
            "last50": round_or_none(last["alpha50"].iloc[0]),
            "last80": round_or_none(last["alpha80"].iloc[0]),
        }
        out["horizons"][str(horizon)] = horizon_summary
        out["baselines"][str(horizon)] = baseline_stats(group, horizon)
    counts = reg["regime"].value_counts() if not reg.empty else pd.Series(dtype=int)
    out["regime_days"] = {regime: int(counts.get(regime, 0)) for regime in REGIME_ORDER}
    out["regime_timeline"] = (
        [{"date": str(day), "regime": row} for day, row in reg["regime"].items()] if not reg.empty else []
    )
    return out
