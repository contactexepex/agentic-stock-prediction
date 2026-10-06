"""Ablation (a): replay of the stored live ranges with each input switched off."""
from __future__ import annotations

import math
import pandas as pd
from marketbrief.analytics import range_math
from marketbrief.constants.review import BASELINE, NOTE_PATTERNS
from marketbrief.pipeline.review.helpers import merge, notes_list


def decompose(r, rc: dict) -> dict | None:
    """Split a published range into its inputs (from its notes and stored numbers). Parts the
    replay cannot attribute (new inputs, changed settings) are kept fixed in `residual`/`sd`."""
    h, base, s, c = int(r["horizon_days"]), float(r["base_close"]), r["sigma_h"], r["center"]
    if s is None or pd.isna(s) or s <= 0 or base <= 0 or pd.isna(c):
        return None
    s, c = float(s), float(c)
    q = {k: (math.log(float(r[col]) / base) - c) / s
         for k, col in (("q10", "lo80"), ("q25", "lo50"), ("q75", "hi50"), ("q90", "hi80"))}
    m = rf = mef = None
    widen, cue, cue_w = 0.0, 0.0, 0.0
    for n in notes_list(r["notes"]):
        if (x := NOTE_PATTERNS["earnings"].match(n)):
            m = float(x.group(1))
        elif (x := NOTE_PATTERNS["regime"].match(n)):
            rf = float(x.group(2))
        elif (x := NOTE_PATTERNS["event"].match(n)):
            mef = float(x.group(1))
        elif (x := NOTE_PATTERNS["ai_widen"].match(n)):
            widen = float(x.group(1)) / 100
        elif (x := NOTE_PATTERNS["cue"].match(n)):
            cue, cue_w = math.log1p(float(x.group(1)) / 100), float(x.group(2))
    s_pre = s / (1 + widen)
    sd = s_pre / ((rf or 1.0) * (mef or 1.0)) / math.sqrt(h + (m * m - 1 if m else 0.0))
    conf, direction = r["confidence"], r["direction"]
    sign = {"up": 1, "down": -1}.get(direction, 0) if isinstance(direction, str) else 0
    ai = sign * (float(conf) - 0.5) if conf is not None and not pd.isna(conf) else 0.0
    est = cue_w * cue + rc["ai_drift_scale"] * ai * s_pre
    capped = abs(abs(c) - rc["max_center_shift_sigma"] * s) < 2e-6 and abs(est) > abs(c)
    return {"h": h, "base": base, "y": float(r["actual_close"]), "q": q, "sd": sd, "earnings": m is not None,
            "regime": r["regime"], "event": mef is not None, "widen": widen, "cue": cue, "ai": ai,
            "residual": 0.0 if capped else c - est}


def replay_range(comp: dict, p: dict) -> dict:
    sd, h = comp["sd"], comp["h"]
    var = sd * sd * h + ((p["earnings_vol_multiple"] ** 2 - 1) * sd * sd if comp["earnings"] else 0.0)
    s = math.sqrt(var) * p["regime_factor"].get(comp["regime"], 1.0)
    s *= p["major_event_factor"] if comp["event"] else 1.0
    center = comp["residual"] + p["cue_weight"] * comp["cue"] + p["ai_drift_scale"] * comp["ai"] * s
    s *= 1 + min(max(comp["widen"], 0.0), p["max_ai_widen"])
    cap = p["max_center_shift_sigma"] * s
    center = max(-cap, min(cap, center))
    base, y, q = comp["base"], comp["y"], comp["q"]
    b = {k: base * math.exp(center + v * s) for k, v in q.items()}
    return {"horizon_days": h, "lo80": b["q10"], "hi80": b["q90"],
            "hit50": b["q25"] <= y <= b["q75"], "hit80": b["q10"] <= y <= b["q90"],
            "is50": 100 * range_math.interval_score(b["q25"], b["q75"], y, 0.5) / base,
            "is80": 100 * range_math.interval_score(b["q10"], b["q90"], y, 0.8) / base,
            "width80": 100 * (b["q90"] - b["q10"]) / base}


def replay_summary(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    m = res.mean(numeric_only=True)
    return {"n": int(len(res)), "cover50": round(float(m["hit50"]), 4), "cover80": round(float(m["hit80"]), 4),
            "width80_pct": round(float(m["width80"]), 3), "score50_pct": round(float(m["is50"]), 3),
            "score80_pct": round(float(m["is80"]), 3)}


def per_horizon(res: pd.DataFrame, horizons) -> dict:
    return {f"{h}d": replay_summary(res[res["horizon_days"] == h]) for h in horizons if not res.empty}


def live_ablation(df: pd.DataFrame, rc: dict, rv: dict) -> dict:
    comps = [c for c in (decompose(r, rc) for r in df.to_dict("records")) if c is not None] if not df.empty else []
    if not comps:
        return {"n": 0, "reproduced": 0, "variants": []}
    base_rows = [replay_range(c, rc) for c in comps]
    pub = df.to_dict("records")
    reproduced = sum(abs(b["lo80"] / float(p["lo80"]) - 1) < 1e-4 and abs(b["hi80"] / float(p["hi80"]) - 1) < 1e-4
                     for b, p in zip(base_rows, pub))
    variants = []
    for v in [{"name": BASELINE, "set": {}}, *rv["live_variants"]]:
        p = merge(rc, v.get("set"))
        res = pd.DataFrame(base_rows if not v.get("set") else [replay_range(c, p) for c in comps])
        variants.append({"name": v["name"], "set": v.get("set") or {}, "n": len(res),
                         "by_h": per_horizon(res, rc["horizons"])})
    return {"n": len(comps), "reproduced": int(reproduced), "variants": variants}
