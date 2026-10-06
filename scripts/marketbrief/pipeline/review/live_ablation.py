"""Ablation (a): replay of the stored live ranges with each input switched off."""

from __future__ import annotations

import math
import pandas as pd
from marketbrief.analytics import range_math
from marketbrief.constants.review import BASELINE, NOTE_PATTERNS
from marketbrief.pipeline.review.helpers import merge, notes_list


def decompose(row, ranges_config: dict) -> dict | None:
    """Split a published range into its inputs (from its notes and stored numbers). Parts the
    replay cannot attribute (new inputs, changed settings) are kept fixed in `residual`/`sd`."""
    horizon, base, horizon_sigma, center = (
        int(row["horizon_days"]),
        float(row["base_close"]),
        row["sigma_h"],
        row["center"],
    )
    if horizon_sigma is None or pd.isna(horizon_sigma) or horizon_sigma <= 0 or base <= 0 or pd.isna(center):
        return None
    horizon_sigma, center = float(horizon_sigma), float(center)
    z_quantiles = {
        key: (math.log(float(row[col]) / base) - center) / horizon_sigma
        for key, col in (("q10", "lo80"), ("q25", "lo50"), ("q75", "hi50"), ("q90", "hi80"))
    }
    earnings_multiple = regime_factor = event_factor = None
    widen, cue, cue_w = 0.0, 0.0, 0.0
    for note in notes_list(row["notes"]):
        if pattern_match := NOTE_PATTERNS["earnings"].match(note):
            earnings_multiple = float(pattern_match.group(1))
        elif pattern_match := NOTE_PATTERNS["regime"].match(note):
            regime_factor = float(pattern_match.group(2))
        elif pattern_match := NOTE_PATTERNS["event"].match(note):
            event_factor = float(pattern_match.group(1))
        elif pattern_match := NOTE_PATTERNS["ai_widen"].match(note):
            widen = float(pattern_match.group(1)) / 100
        elif pattern_match := NOTE_PATTERNS["cue"].match(note):
            cue, cue_w = math.log1p(float(pattern_match.group(1)) / 100), float(pattern_match.group(2))
    s_pre = horizon_sigma / (1 + widen)
    daily_sigma = (
        s_pre
        / ((regime_factor or 1.0) * (event_factor or 1.0))
        / math.sqrt(horizon + (earnings_multiple * earnings_multiple - 1 if earnings_multiple else 0.0))
    )
    conf, direction = row["confidence"], row["direction"]
    sign = {"up": 1, "down": -1}.get(direction, 0) if isinstance(direction, str) else 0
    ai_edge = sign * (float(conf) - 0.5) if conf is not None and not pd.isna(conf) else 0.0
    est = cue_w * cue + ranges_config["ai_drift_scale"] * ai_edge * s_pre
    capped = abs(abs(center) - ranges_config["max_center_shift_sigma"] * horizon_sigma) < 2e-6 and abs(est) > abs(
        center
    )
    return {
        "h": horizon,
        "base": base,
        "y": float(row["actual_close"]),
        "q": z_quantiles,
        "sd": daily_sigma,
        "earnings": earnings_multiple is not None,
        "regime": row["regime"],
        "event": event_factor is not None,
        "widen": widen,
        "cue": cue,
        "ai": ai_edge,
        "residual": 0.0 if capped else center - est,
    }


def replay_range(comp: dict, params: dict) -> dict:
    daily_sigma, horizon = comp["sd"], comp["h"]
    var = daily_sigma * daily_sigma * horizon + (
        (params["earnings_vol_multiple"] ** 2 - 1) * daily_sigma * daily_sigma if comp["earnings"] else 0.0
    )
    horizon_sigma = math.sqrt(var) * params["regime_factor"].get(comp["regime"], 1.0)
    horizon_sigma *= params["major_event_factor"] if comp["event"] else 1.0
    center = (
        comp["residual"] + params["cue_weight"] * comp["cue"] + params["ai_drift_scale"] * comp["ai"] * horizon_sigma
    )
    horizon_sigma *= 1 + min(max(comp["widen"], 0.0), params["max_ai_widen"])
    cap = params["max_center_shift_sigma"] * horizon_sigma
    center = max(-cap, min(cap, center))
    base, actual_close, z_quantiles = comp["base"], comp["y"], comp["q"]
    band_edges = {key: base * math.exp(center + value * horizon_sigma) for key, value in z_quantiles.items()}
    return {
        "horizon_days": horizon,
        "lo80": band_edges["q10"],
        "hi80": band_edges["q90"],
        "hit50": band_edges["q25"] <= actual_close <= band_edges["q75"],
        "hit80": band_edges["q10"] <= actual_close <= band_edges["q90"],
        "is50": 100 * range_math.interval_score(band_edges["q25"], band_edges["q75"], actual_close, 0.5) / base,
        "is80": 100 * range_math.interval_score(band_edges["q10"], band_edges["q90"], actual_close, 0.8) / base,
        "width80": 100 * (band_edges["q90"] - band_edges["q10"]) / base,
    }


def replay_summary(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    means = res.mean(numeric_only=True)
    return {
        "n": int(len(res)),
        "cover50": round(float(means["hit50"]), 4),
        "cover80": round(float(means["hit80"]), 4),
        "width80_pct": round(float(means["width80"]), 3),
        "score50_pct": round(float(means["is50"]), 3),
        "score80_pct": round(float(means["is80"]), 3),
    }


def per_horizon(res: pd.DataFrame, horizons) -> dict:
    return {f"{horizon}d": replay_summary(res[res["horizon_days"] == horizon]) for horizon in horizons if not res.empty}


def live_ablation(frame: pd.DataFrame, ranges_config: dict, review_config: dict) -> dict:
    comps = (
        [
            component
            for component in (decompose(row, ranges_config) for row in frame.to_dict("records"))
            if component is not None
        ]
        if not frame.empty
        else []
    )
    if not comps:
        return {"n": 0, "reproduced": 0, "variants": []}
    base_rows = [replay_range(component, ranges_config) for component in comps]
    pub = frame.to_dict("records")
    reproduced = sum(
        abs(pair["lo80"] / float(params["lo80"]) - 1) < 1e-4 and abs(pair["hi80"] / float(params["hi80"]) - 1) < 1e-4
        for pair, params in zip(base_rows, pub)
    )
    variants = []
    for variant in [{"name": BASELINE, "set": {}}, *review_config["live_variants"]]:
        params = merge(ranges_config, variant.get("set"))
        res = pd.DataFrame(
            base_rows if not variant.get("set") else [replay_range(component, params) for component in comps]
        )
        variants.append(
            {
                "name": variant["name"],
                "set": variant.get("set") or {},
                "n": len(res),
                "by_h": per_horizon(res, ranges_config["horizons"]),
            }
        )
    return {"n": len(comps), "reproduced": int(reproduced), "variants": variants}
