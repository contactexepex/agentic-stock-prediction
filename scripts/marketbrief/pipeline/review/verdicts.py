"""Verdicts of the ablations, the proposed config changes and the confidence advice."""

from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.analytics import scoring
from marketbrief.constants.config_keys import BY_MARKET_SUFFIX
from marketbrief.constants.review import BASELINE, TARGETS
from marketbrief.pipeline.review.summaries import by_horizon


def compare(base: dict, var: dict) -> dict | None:
    """rel_score: mean relative change of the 80% interval score (negative = better).
    coverage_shortfall: largest extra drop BELOW target of 50%/80% coverage (over-coverage is
    left to the interval score and the daily self-calibration). coverage_gain: mean move of
    80% coverage towards its target."""
    horizons = [
        horizon
        for horizon, base_summary in base.items()
        if base_summary.get("n") and var.get(horizon, {}).get("n") and base_summary.get("score80_pct")
    ]
    if not horizons:
        return None
    rel = float(np.mean([var[horizon]["score80_pct"] / base[horizon]["score80_pct"] - 1 for horizon in horizons]))
    short = max(
        max(0.0, target - var[horizon][f"cover{base_summary}"])
        - max(0.0, target - base[horizon][f"cover{base_summary}"])
        for horizon in horizons
        for base_summary, target in TARGETS.items()
    )
    gain = float(
        np.mean([abs(base[horizon]["cover80"] - 0.8) - abs(var[horizon]["cover80"] - 0.8) for horizon in horizons])
    )
    return {"rel_score": round(rel, 4), "coverage_shortfall": round(float(short), 4), "coverage_gain": round(gain, 4)}


def verdict(comparison: dict | None, count: int, review_config: dict) -> str:
    """The verdict of a variant: no data, low n, improves score or coverage, worse, under-covers."""
    if comparison is None or count < review_config["min_n_recommend"]:
        return "no data" if comparison is None else "low n"
    if (
        comparison["rel_score"] <= -review_config["min_improvement"]
        and comparison["coverage_shortfall"] <= review_config["coverage_tolerance"]
    ):
        return "improves score"
    if comparison["coverage_gain"] >= review_config["min_coverage_gain"] and comparison["rel_score"] <= 0:
        return "improves coverage"
    if comparison["rel_score"] >= review_config["min_improvement"]:
        return "worse score"
    if comparison["coverage_shortfall"] > review_config["coverage_tolerance"]:
        return "under-covers"
    return "no material change"


def judge(ablation: dict, review_config: dict) -> None:
    """Annotate each variant with its comparison to the current config and a verdict."""
    variants = ablation.get("variants") or []
    base = next((variant for variant in variants if variant["name"] == BASELINE), None)
    for variant in variants:
        if variant is base:
            variant["verdict"] = "baseline" if variant["n"] else "no data"
            continue
        variant["vs_current"] = compare(base["by_h"], variant["by_h"]) if base else None
        variant["verdict"] = verdict(variant["vs_current"], variant["n"], review_config)


def config_key(ranges_config: dict, param: str, market: str | None) -> str:
    """The config/ranges.yaml key a human edits for `param`: `<param>_by_market.<market>` when that per-market
    override sets it for this market (issue #16), else `param`."""
    if market and market in (ranges_config.get(f"{param}{BY_MARKET_SUFFIX}") or {}):
        return f"{param}{BY_MARKET_SUFFIX}.{market}"
    return param


def proposals(ranges_config: dict, live: dict, hist: dict, market: str | None = None) -> list[dict]:
    """Best qualifying variant per parameter set; live evidence wins over price history, and
    price history is not proposed against live evidence (n >= min) that the change is worse.
    Each change names the key to edit (config_key: a per-market override where one applies)."""
    best: dict[tuple, dict] = {}
    live_worse = {
        tuple(sorted(variant["set"]))
        for variant in live.get("variants") or []
        if variant.get("verdict") in ("worse score", "under-covers")
    }
    for source, ablation in (("history walk-forward", hist), ("live replay", live)):
        for variant in ablation.get("variants") or []:
            if variant.get("verdict") not in ("improves score", "improves coverage"):
                continue
            key = tuple(sorted(variant["set"]))
            if source != "live replay" and key in live_worse:
                continue
            current_best = best.get(key)
            if (
                current_best is None
                or source == "live replay"
                and current_best["source"] != "live replay"
                or current_best["source"] == source
                and variant["vs_current"]["rel_score"] < current_best["rel_score"]
            ):
                base = next(variant_row for variant_row in ablation["variants"] if variant_row["name"] == BASELINE)
                best[key] = {
                    "variant": variant["name"],
                    "source": source,
                    "n": variant["n"],
                    "verdict": variant["verdict"],
                    "changes": [
                        {"param": config_key(ranges_config, param, market), "current": ranges_config.get(param),
                         "proposed": value}
                        for param, value in variant["set"].items()
                    ],
                    "drop": variant["name"].lower().startswith("drop"),
                    "rel_score": variant["vs_current"]["rel_score"],
                    "cover80_before": {
                        horizon: variant_row.get("cover80") for horizon, variant_row in base["by_h"].items()
                    },
                    "cover80_after": {
                        horizon: variant_row.get("cover80") for horizon, variant_row in variant["by_h"].items()
                    },
                }
    return sorted(best.values(), key=lambda params: params["rel_score"])


def proper_scores(ranges: pd.DataFrame, calls: pd.DataFrame) -> dict:
    """Brier, log loss and reliability for calls; interval and quantile scores for ranges (scoring.py)."""
    scored_calls = calls[calls["confidence"].notna() & calls["hit"].notna()] if not calls.empty else calls
    out = {
        "calls": by_horizon(scored_calls, scoring.call_scores) if not scored_calls.empty else {"all": {"n": 0}},
        "reliability": scoring.reliability(scored_calls["confidence"], scored_calls["hit"])
        if not scored_calls.empty
        else [],
        "ranges": by_horizon(ranges, scoring.range_scores) if not ranges.empty else {"all": {"n": 0}},
    }
    return out


def confidence_advice(bands: dict, calls: dict, review_config: dict) -> list[str]:
    """Advice lines for confidence bands that miss their stated confidence."""
    out = []
    for band, band_stats in bands.items():
        if (
            band_stats.get("n", 0) >= review_config["min_n_calls"]
            and band_stats["gap"] < -review_config["calibration_tolerance"]
        ):
            out.append(
                f"Calls at {band} confidence hit {scoring.percent(band_stats['hit_rate'])} (mean stated "
                f"{scoring.percent(band_stats['mean_confidence'])}, "
                f"n={band_stats['n']}): use lower confidence or abstain in this band."
            )
    all_calls = calls.get("all", {})
    if (
        all_calls.get("n", 0) >= review_config["min_n_calls"]
        and all_calls["edge"] is not None
        and all_calls["edge"] <= 0
    ):
        out.append(
            f"Calls hit {scoring.percent(all_calls['hit_rate'])} vs always-up "
            f"{scoring.percent(all_calls['always_up'])} (n={all_calls['n']}): no edge over the "
            "baseline; abstain more."
        )
    return out
