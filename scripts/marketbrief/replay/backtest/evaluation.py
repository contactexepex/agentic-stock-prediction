"""Scoring of the walk-forward ranges and the off/on comparison of each range input."""
from __future__ import annotations

import math
import pandas as pd
from marketbrief.analytics import range_math
from marketbrief.constants.backtest import INPUT_ARMS


def score(base: float, y: float, center: float, sh: float, q: tuple) -> dict:
    q10, q25, q75, q90 = q
    lo50, hi50 = base * math.exp(center + q25 * sh), base * math.exp(center + q75 * sh)
    lo80, hi80 = base * math.exp(center + q10 * sh), base * math.exp(center + q90 * sh)
    return {"hit50": lo50 <= y <= hi50, "hit80": lo80 <= y <= hi80,
            "width80": 100 * (hi80 - lo80) / base, "is80": 100 * range_math.interval_score(lo80, hi80, y, 0.8) / base}


def arm_params(o, h: int, rc: dict, use: dict) -> dict[str, tuple[float, float]]:
    """(centre, horizon sigma) per arm for one observation. `configured` = the inputs switched on
    in config/ranges.yaml for this market; `current` = the formula before these inputs."""
    sd = o.sigma
    var = sd * sd * h
    fixed = rc["earnings_vol_multiple"]
    earn = bool(getattr(o, "earn", False))
    m_hist = o.m_hist if earn and o.m_hist == o.m_hist else fixed
    sh = {"core": math.sqrt(var),
          "fixed": math.sqrt(var + (fixed ** 2 - 1) * sd * sd) if earn else math.sqrt(var),
          "hist": math.sqrt(var + (m_hist ** 2 - 1) * sd * sd) if earn else math.sqrt(var)}
    own = o.own if o.own == o.own else None
    idx_cue = o.idx_cue if o.idx_cue == o.idx_cue else None
    beta = o.beta if o.beta == o.beta else None
    direct = rc["cue_weight"] * own if own is not None else 0.0
    bs = rc["beta_split"]
    split = range_math.beta_split_center(beta, idx_cue, own, bs["index_weight"], bs["own_weight"], rc["cue_weight"])
    cap = lambda x, s: max(-rc["max_center_shift_sigma"] * s, min(rc["max_center_shift_sigma"] * s, x))  # noqa: E731
    div = o.div_shift
    s_cfg = sh["hist"] if use.get("earnings_history") else sh["fixed"]
    return {"core": (0.0, sh["core"]), "earn_fixed": (0.0, sh["fixed"]), "earn_hist": (0.0, sh["hist"]),
            "exdiv": (div, sh["core"]),
            "cue_direct": (cap(direct, sh["core"]), sh["core"]), "cue_beta": (cap(split, sh["core"]), sh["core"]),
            "current": (cap(direct, sh["fixed"]), sh["fixed"]),
            "configured": (cap(split if use.get("beta_split") else direct, s_cfg)
                           + (div if use.get("ex_dividend") else 0.0), s_cfg)}


def evaluate(obs: pd.DataFrame, h: int, rc: dict, eval_sessions: int, use: dict | None = None, *,
             scale: dict[int, float] | None = None) -> pd.DataFrame:
    """`use`: the range inputs switched on (config/ranges.yaml) for the per-input arms.
    `scale` (keyword only) widens sigma per start rank (regime/event factors replayed by review.py)."""
    last = int(obs["rank"].max())
    start = last - eval_sessions + 1
    z_all, r_all = obs["z"].to_numpy(), obs["rank"].to_numpy()
    with_inputs = "earn" in obs.columns
    rows = []
    for d in range(start, last + 1):
        known = (r_all + h <= d) & (r_all > d - rc["history_sessions"])
        if known.sum() < rc["min_pool"]:
            continue
        w = range_math.recency_weights((d - r_all[known]).astype(float), rc["half_life_sessions"])
        z = z_all[known]
        q = tuple(range_math.weighted_quantile(z, w, p) for p in (0.10, 0.25, 0.75, 0.90))
        today = obs[obs["rank"] == d]
        for o in today.itertuples():
            base, sh = o.close, o.sigma * math.sqrt(h) * (scale.get(d, 1.0) if scale else 1.0)
            y = base * math.exp(o.fwd)
            core = score(base, y, 0.0, sh, q)
            lo50, hi50 = base * math.exp(q[1] * sh), base * math.exp(q[2] * sh)
            n50, n80 = range_math.naive_range(base, o.s20, h, 0.5), range_math.naive_range(base, o.s20, h, 0.8)
            row = {
                "rank": d, "ticker": o.ticker,
                "hit50": core["hit50"], "hit80": core["hit80"],
                "naive_hit50": n50[0] <= y <= n50[1], "naive_hit80": n80[0] <= y <= n80[1],
                "width80": core["width80"], "naive_width80": 100 * (n80[1] - n80[0]) / base,
                "is80": core["is80"],
                "naive_is80": 100 * range_math.interval_score(n80[0], n80[1], y, 0.8) / base,
                "is50": 100 * range_math.interval_score(lo50, hi50, y, 0.5) / base,
                "naive_is50": 100 * range_math.interval_score(n50[0], n50[1], y, 0.5) / base,
            }
            if with_inputs:
                row.update({"earn": bool(o.earn), "has_div": bool(o.has_div), "has_cue": bool(o.has_cue)})
                for arm, (center, s) in arm_params(o, h, rc, use or {}).items():
                    for k, v in score(base, y, center, s, q).items():
                        row[f"{arm}_{k}"] = v
            rows.append(row)
    return pd.DataFrame(rows)


def summarize(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    m = res.mean(numeric_only=True)
    return {"n": int(len(res)), "days": int(res["rank"].nunique()),
            "cover50": round(float(m["hit50"]), 3), "cover80": round(float(m["hit80"]), 3),
            "naive_cover50": round(float(m["naive_hit50"]), 3), "naive_cover80": round(float(m["naive_hit80"]), 3),
            "width80_pct": round(float(m["width80"]), 2), "naive_width80_pct": round(float(m["naive_width80"]), 2),
            "score80": round(float(m["is80"]), 3), "naive_score80": round(float(m["naive_is80"]), 3)}


def arm_summary(res: pd.DataFrame, arm: str) -> dict:
    if res.empty:
        return {"n": 0}
    return {"n": int(len(res)), "cover50": round(float(res[f"{arm}_hit50"].mean()), 3),
            "cover80": round(float(res[f"{arm}_hit80"].mean()), 3),
            "width80_pct": round(float(res[f"{arm}_width80"].mean()), 3),
            "score80": round(float(res[f"{arm}_is80"].mean()), 4)}


def verdict(off: dict, on: dict, min_gain: float) -> str:
    """DESIGN section 7 rule: improves only if the interval score drops by more than min_gain
    (relative); a change within it is noise."""
    if not off.get("n"):
        return "no data"
    a, b = off["score80"], on["score80"]
    if a == b:
        return "same"
    gain = (a - b) / a
    return "improves" if gain > min_gain else ("worse" if gain < -min_gain else "noise")


def compare_inputs(res: pd.DataFrame, min_gain: float = 0.005) -> dict:
    out = {}
    for name, (off, on, col) in INPUT_ARMS.items():
        sub = res[res[col]] if col in res.columns else res.iloc[0:0]
        a, b = arm_summary(sub, off), arm_summary(sub, on)
        out[name] = {"applies": a["n"], "off": a, "on": b, "verdict": verdict(a, b, min_gain)}
    if len(res):
        a, b = arm_summary(res, "current"), arm_summary(res, "configured")
        out["all_inputs"] = {"applies": int(len(res)), "off": a, "on": b, "verdict": verdict(a, b, min_gain)}
    out["implied_vol"] = {"verdict": "live only (no stored option history)"}
    return out
