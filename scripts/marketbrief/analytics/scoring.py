"""Proper scores for the track record (library, pure functions; docs/DESIGN.md section 6).

Direction calls: a call states the probability `confidence` (0.50-0.90) that its direction is
right; the outcome is `hit` (1/0).
- Brier score  = mean((probability - outcome)^2); a coin flip (p = 0.5 always) scores 0.25. Lower is better.
- Log loss     = -mean(y ln p + (1 - y) ln(1 - p)); a coin flip scores ln 2 = 0.693.
- Reliability  = stated-confidence bins vs hit rate, with counts and Wilson 95% intervals.

Ranges: each published range stores four quantiles of the target close, lo80 = q10,
lo50 = q25, hi50 = q75, hi80 = q90.
- Interval score (Gneiting-Raftery) per band: range_math.interval_score.
- Quantile score = mean pinball loss over those four quantiles (a coarse CRPS estimate: the CRPS
  is twice the pinball loss integrated over all levels). Identity used in the tests:
  QS = (0.1 * IS80 + 0.25 * IS50) / 4.
All range scores are in % of the base close, as the rest of the scorecard."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import numpy as np
import pandas as pd

from marketbrief.analytics import range_math
from marketbrief.constants.scoring import (
    BASIS_NOTE,
    BASIS_SHORT,
    CALL_BINS,
    COIN_FLIP_BRIER,
    EPS,
    MISSING_DASH,
    RANGE_QUANTILES,
    WILSON_Z,
)
from marketbrief.utils.numbers import round_or_none


def wilson(successes: int, total: int, z_score: float = WILSON_Z) -> tuple[float | None, float | None]:
    """Wilson score interval for `successes` out of `total`."""
    if not total:
        return None, None
    share = successes / total
    den = 1 + z_score * z_score / total
    mid = (share + z_score * z_score / (2 * total)) / den
    half = z_score * math.sqrt(share * (1 - share) / total + z_score * z_score / (4 * total * total)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def finite_pairs(probabilities, outcomes) -> tuple[np.ndarray, np.ndarray]:
    """The (probability, outcome) pairs where both are finite, as float arrays."""
    probabilities = np.asarray(probabilities, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    both_finite = np.isfinite(probabilities) & np.isfinite(outcomes)
    return probabilities[both_finite], outcomes[both_finite]


def exact_mean(values) -> float | None:
    """Mean of the non-NaN values, computed exactly (rational sum, rounded once), so it does not depend
    on row order: the mean of n copies of 0.7 is 0.7. An infinite value gives the float mean."""
    array = np.asarray(values, dtype=float)
    array = array[~np.isnan(array)]
    if not len(array):
        return None
    return (
        float(sum(map(Fraction, array.tolist()), Fraction(0)) / len(array))
        if np.isfinite(array).all()
        else float(array.mean())
    )


def brier(probabilities, outcomes) -> float | None:
    """The Brier score: mean((probability - outcome)^2) over the finite pairs."""
    probabilities, outcomes = finite_pairs(probabilities, outcomes)
    return exact_mean((probabilities - outcomes) ** 2)


def log_loss(probabilities, outcomes) -> float | None:
    """The log loss: -mean(outcome ln p + (1 - outcome) ln(1 - p)) over the finite pairs.
    p is the probability, clipped away from 0 and 1."""
    probabilities, outcomes = finite_pairs(probabilities, outcomes)
    if not len(probabilities):
        return None
    probabilities = np.clip(probabilities, EPS, 1 - EPS)
    return -exact_mean(outcomes * np.log(probabilities) + (1 - outcomes) * np.log(1 - probabilities))


def reliability(probabilities, outcomes, edges=CALL_BINS) -> list[dict]:
    """One row per confidence bin [lo, hi) (the last bin closed): count, mean stated confidence,
    hit rate and its Wilson 95% interval. Empty bins are kept with n = 0."""
    probabilities, outcomes = finite_pairs(probabilities, outcomes)
    out = []
    for bin_index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:])):
        last = bin_index == len(edges) - 2
        in_bin = (probabilities >= lower) & ((probabilities <= upper) if last else (probabilities < upper))
        count, hits = int(in_bin.sum()), int(outcomes[in_bin].sum())
        wilson_lower, wilson_upper = wilson(hits, count)
        out.append(
            {
                "bin": f"{lower:.2f}-{upper:.2f}",
                "lo": lower,
                "hi": upper,
                "n": count,
                "mean_conf": exact_mean(probabilities[in_bin]) if count else None,
                "hit_rate": hits / count if count else None,
                "wilson_lo": wilson_lower,
                "wilson_hi": wilson_upper,
            }
        )
    return out


def call_scores(scored_calls: pd.DataFrame) -> dict:
    """Brier, log loss and Brier skill vs a coin flip (1 - Brier / 0.25) for scored calls
    (columns confidence, hit)."""
    if scored_calls is None or scored_calls.empty:
        return {"n": 0}
    probabilities, outcomes = scored_calls["confidence"].astype(float), scored_calls["hit"].astype(float)
    brier_score, loss = brier(probabilities, outcomes), log_loss(probabilities, outcomes)
    return {
        "n": int(len(scored_calls)),
        "brier": round_or_none(brier_score),
        "log_loss": round_or_none(loss),
        "brier_skill": round_or_none(1 - brier_score / COIN_FLIP_BRIER) if brier_score is not None else None,
    }


def pinball(q_value: float, level: float, outcome: float) -> float:
    """Pinball (quantile) loss of the `level` quantile forecast q_value for the outcome."""
    return max(level * (outcome - q_value), (level - 1) * (outcome - q_value))


def quantile_score(quantile_values: dict[float, float], outcome: float) -> float:
    """Mean pinball loss over the given {level: value} quantiles."""
    return float(np.mean([pinball(value, level, outcome) for level, value in quantile_values.items()]))


def range_scores_row(lo50, hi50, lo80, hi80, outcome, base) -> dict:
    """Interval scores (50%, 80%) and quantile score of one scored range, in % of base."""
    bounds = {"lo50": lo50, "hi50": hi50, "lo80": lo80, "hi80": hi80}
    quantile_values = {level: float(bounds[bound_name]) for bound_name, level in RANGE_QUANTILES}
    return {
        "is50_pct": 100 * range_math.interval_score(lo50, hi50, outcome, 0.5) / base,
        "is80_pct": 100 * range_math.interval_score(lo80, hi80, outcome, 0.8) / base,
        "qs_pct": 100 * quantile_score(quantile_values, outcome) / base,
    }


def range_scores(scored_ranges: pd.DataFrame) -> dict:
    """Coverage, interval scores, quantile score and width for scored ranges (columns lo50, hi50,
    lo80, hi80, actual_close, base_close, hit50, hit80)."""
    if scored_ranges is None or scored_ranges.empty:
        return {"n": 0}
    rows = [
        range_scores_row(*(float(value) for value in row))
        for row in scored_ranges[["lo50", "hi50", "lo80", "hi80", "actual_close", "base_close"]].itertuples(index=False)
    ]
    score_rows = pd.DataFrame(rows)
    base = scored_ranges["base_close"].astype(float)
    return {
        "n": int(len(scored_ranges)),
        "cover50": round_or_none(exact_mean(scored_ranges["hit50"].astype(float))),
        "cover80": round_or_none(exact_mean(scored_ranges["hit80"].astype(float))),
        "is50_pct": round_or_none(exact_mean(score_rows["is50_pct"])),
        "is80_pct": round_or_none(exact_mean(score_rows["is80_pct"])),
        "qs_pct": round_or_none(exact_mean(score_rows["qs_pct"])),
        "width50_pct": round_or_none(exact_mean(100 * (scored_ranges["hi50"] - scored_ranges["lo50"]) / base)),
        "width80_pct": round_or_none(exact_mean(100 * (scored_ranges["hi80"] - scored_ranges["lo80"]) / base)),
    }


# ---------- track-record summary (score_predictions, context pack, review, HTML) ----------


def summary(con) -> dict:
    """All-time proper scores from the scored track record: calls per scoring basis (call_basis.py; never
    pooled), per horizon and overall (Brier, log loss, reliability), and ranges per horizon (coverage,
    interval and quantile scores)."""
    calls = con.execute(
        "SELECT label_basis, horizon_days, confidence, hit FROM track_record "
        "WHERE confidence IS NOT NULL AND hit IS NOT NULL ORDER BY id, scored_at"
    ).df()
    rng = con.execute(
        "SELECT horizon_days, lo50, hi50, lo80, hi80, actual_close, base_close, hit50, hit80 "
        "FROM range_record WHERE actual_close IS NOT NULL ORDER BY id"
    ).df()
    out = {"calls": {}, "ranges": {}}
    for basis, by_basis in calls.groupby("label_basis", sort=True) if len(calls) else []:
        entry = out["calls"][basis] = {"all": call_scores(by_basis)}
        entry["all"]["reliability"] = reliability(by_basis["confidence"], by_basis["hit"])
        for horizon, group in by_basis.groupby("horizon_days"):
            entry[f"{int(horizon)}d"] = call_scores(group)
    for horizon, group in rng.groupby("horizon_days") if len(rng) else []:
        out["ranges"][f"{int(horizon)}d"] = range_scores(group)
    return out


def format_number(value, digits: int = 3) -> str:
    """A number with `digits` decimals, '–' when missing."""
    return MISSING_DASH if value is None else f"{value:.{digits}f}"


def percent(share, digits: int = 0, sign: bool = False) -> str:
    """A share (0.625) as a percent rounded half up on its decimal value ('63%', digits=1 '62.5%',
    sign=True '+63%'); '–' for a missing or non-finite value. The one convention for printed whole
    percents, also in the HTML report's JavaScript (pct0). Domain: finite values below about 1e26 in
    magnitude (shares are 0 to 1); larger ones raise decimal.InvalidOperation."""
    if share is None or not math.isfinite(float(share)):
        return MISSING_DASH
    value = Decimal(repr(float(share))).scaleb(2).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP)
    return f"{value:+}%" if sign else f"{value}%"


def format_percent(value) -> str:
    """A share as a whole percent, '–' when missing."""
    return MISSING_DASH if value is None else percent(value)


def markdown(scores: dict) -> str:
    """Compact Markdown for the context pack."""
    calls = scores["calls"]
    lines = [
        "Calls: Brier (coin flip 0.250) and log loss (coin flip 0.693), lower is better; skill = 1 - Brier/0.25. "
        + BASIS_NOTE,
        "",
        "| basis | h | n | brier | log_loss | skill |",
        "|---|---|---|---|---|---|",
    ]
    for basis, by_horizon in calls.items():
        for horizon_label, entry in by_horizon.items():
            lines.append(
                f"| {BASIS_SHORT[basis]} | {horizon_label} | {entry['n']} | {format_number(entry.get('brier'))} | "
                f"{format_number(entry.get('log_loss'))} | "
                f"{format_number(entry.get('brier_skill'))} |"
            )
    if not calls:
        lines.append("| – | all | 0 | – | – | – |")
    rel = [(basis, bin_row) for basis, by_horizon in calls.items()
           for bin_row in by_horizon["all"].get("reliability", []) if bin_row["n"]]
    if rel:
        lines += [
            "",
            "Reliability (all horizons, per basis): stated confidence vs hit rate, Wilson 95%.",
            "",
            "| basis | bin | n | mean_conf | hit_rate | 95% |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {BASIS_SHORT[basis]} | {bin_row['bin']} | {bin_row['n']} | {format_percent(bin_row['mean_conf'])} | "
            f"{format_percent(bin_row['hit_rate'])} | "
            f"{format_percent(bin_row['wilson_lo'])}-{format_percent(bin_row['wilson_hi'])} |"
            for basis, bin_row in rel
        ]
    lines += [
        "",
        "Ranges (all time; % of price, lower is better): interval scores and quantile score "
        "(mean pinball loss over q10/q25/q75/q90).",
        "",
        "| h | n | cover50 | cover80 | is50 | is80 | qs |",
        "|---|---|---|---|---|---|---|",
    ]
    for horizon_label, entry in scores["ranges"].items():
        lines.append(
            f"| {horizon_label} | {entry['n']} | {format_percent(entry.get('cover50'))} | "
            f"{format_percent(entry.get('cover80'))} | "
            f"{format_number(entry.get('is50_pct'))} | {format_number(entry.get('is80_pct'))} | "
            f"{format_number(entry.get('qs_pct'))} |"
        )
    if not scores["ranges"]:
        lines.append("| – | 0 | – | – | – | – | – |")
    return "\n".join(lines) + "\n"
