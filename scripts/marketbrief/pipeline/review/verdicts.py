"""Verdicts of the ablations, the proposed config changes and the confidence advice."""
from __future__ import annotations

import numpy as np
import pandas as pd
from marketbrief.analytics import scoring
from marketbrief.constants.review import BASELINE, TARGETS
from marketbrief.pipeline.review.summaries import by_horizon


def compare(base: dict, var: dict) -> dict | None:
    """rel_score: mean relative change of the 80% interval score (negative = better).
    coverage_shortfall: largest extra drop BELOW target of 50%/80% coverage (over-coverage is
    left to the interval score and the daily self-calibration). coverage_gain: mean move of
    80% coverage towards its target."""
    hs = [h for h, b in base.items() if b.get("n") and var.get(h, {}).get("n") and b.get("score80_pct")]
    if not hs:
        return None
    rel = float(np.mean([var[h]["score80_pct"] / base[h]["score80_pct"] - 1 for h in hs]))
    short = max(max(0.0, t - var[h][f"cover{b}"]) - max(0.0, t - base[h][f"cover{b}"])
                for h in hs for b, t in TARGETS.items())
    gain = float(np.mean([abs(base[h]["cover80"] - 0.8) - abs(var[h]["cover80"] - 0.8) for h in hs]))
    return {"rel_score": round(rel, 4), "coverage_shortfall": round(float(short), 4), "coverage_gain": round(gain, 4)}


def verdict(cmp: dict | None, n: int, rv: dict) -> str:
    if cmp is None:
        return "no data"
    if n < rv["min_n_recommend"]:
        return "low n"
    if cmp["rel_score"] <= -rv["min_improvement"] and cmp["coverage_shortfall"] <= rv["coverage_tolerance"]:
        return "improves score"
    if cmp["coverage_gain"] >= rv["min_coverage_gain"] and cmp["rel_score"] <= 0:
        return "improves coverage"
    if cmp["rel_score"] >= rv["min_improvement"]:
        return "worse score"
    if cmp["coverage_shortfall"] > rv["coverage_tolerance"]:
        return "under-covers"
    return "no material change"


def judge(ablation: dict, rv: dict) -> None:
    """Annotate each variant with its comparison to the current config and a verdict."""
    vs = ablation.get("variants") or []
    base = next((v for v in vs if v["name"] == BASELINE), None)
    for v in vs:
        if v is base:
            v["verdict"] = "baseline" if v["n"] else "no data"
            continue
        v["vs_current"] = compare(base["by_h"], v["by_h"]) if base else None
        v["verdict"] = verdict(v["vs_current"], v["n"], rv)


def proposals(rc: dict, live: dict, hist: dict) -> list[dict]:
    """Best qualifying variant per parameter set; live evidence wins over price history, and
    price history is not proposed against live evidence (n >= min) that the change is worse."""
    best: dict[tuple, dict] = {}
    live_worse = {tuple(sorted(v["set"])) for v in live.get("variants") or []
                  if v.get("verdict") in ("worse score", "under-covers")}
    for source, ab in (("history walk-forward", hist), ("live replay", live)):
        for v in ab.get("variants") or []:
            if v.get("verdict") not in ("improves score", "improves coverage"):
                continue
            key = tuple(sorted(v["set"]))
            if source != "live replay" and key in live_worse:
                continue
            cur = best.get(key)
            if cur is None or source == "live replay" and cur["source"] != "live replay" or \
                    cur["source"] == source and v["vs_current"]["rel_score"] < cur["rel_score"]:
                base = next(x for x in ab["variants"] if x["name"] == BASELINE)
                best[key] = {"variant": v["name"], "source": source, "n": v["n"], "verdict": v["verdict"],
                             "changes": [{"param": k, "current": rc.get(k), "proposed": val} for k, val in v["set"].items()],
                             "drop": v["name"].lower().startswith("drop"),
                             "rel_score": v["vs_current"]["rel_score"],
                             "cover80_before": {h: x.get("cover80") for h, x in base["by_h"].items()},
                             "cover80_after": {h: x.get("cover80") for h, x in v["by_h"].items()}}
    return sorted(best.values(), key=lambda p: p["rel_score"])


def proper_scores(ranges: pd.DataFrame, calls: pd.DataFrame) -> dict:
    """Brier, log loss and reliability for calls; interval and quantile scores for ranges (scoring.py)."""
    c = calls[calls["confidence"].notna() & calls["hit"].notna()] if not calls.empty else calls
    out = {"calls": by_horizon(c, scoring.call_scores) if not c.empty else {"all": {"n": 0}},
           "reliability": scoring.reliability(c["confidence"], c["hit"]) if not c.empty else [],
           "ranges": by_horizon(ranges, scoring.range_scores) if not ranges.empty else {"all": {"n": 0}}}
    return out


def confidence_advice(bands: dict, calls: dict, rv: dict) -> list[str]:
    out = []
    for band, s in bands.items():
        if s.get("n", 0) >= rv["min_n_calls"] and s["gap"] < -rv["calibration_tolerance"]:
            out.append(f"Calls at {band} confidence hit {scoring.percent(s['hit_rate'])} (mean stated {scoring.percent(s['mean_confidence'])}, "
                       f"n={s['n']}): use lower confidence or abstain in this band.")
    a = calls.get("all", {})
    if a.get("n", 0) >= rv["min_n_calls"] and a["edge"] is not None and a["edge"] <= 0:
        out.append(f"Calls hit {scoring.percent(a['hit_rate'])} vs always-up {scoring.percent(a['always_up'])} (n={a['n']}): no edge over the "
                   "baseline; abstain more.")
    return out
