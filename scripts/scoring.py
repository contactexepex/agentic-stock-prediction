"""Proper scores for the track record (library, pure functions; docs/DESIGN.md section 6).

Direction calls: a call states the probability `confidence` (0.50-0.90) that its direction is
right; the outcome is `hit` (1/0).
- Brier score  = mean((p - y)^2); a coin flip (p = 0.5 always) scores 0.25. Lower is better.
- Log loss     = -mean(y ln p + (1 - y) ln(1 - p)); a coin flip scores ln 2 = 0.693.
- Reliability  = stated-confidence bins vs hit rate, with counts and Wilson 95% intervals.

Ranges: each published range stores four quantiles of the target close, lo80 = q10,
lo50 = q25, hi50 = q75, hi80 = q90.
- Interval score (Gneiting-Raftery) per band: rangelib.interval_score.
- Quantile score = mean pinball loss over those four quantiles (a coarse CRPS estimate: the CRPS
  is twice the pinball loss integrated over all levels). Identity used in the tests:
  QS = (0.1 * IS80 + 0.25 * IS50) / 4.
All range scores are in % of the base close, as the rest of the scorecard."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import rangelib as rl

EPS = 1e-6
CALL_BINS = (0.5, 0.6, 0.7, 0.8, 0.9)   # bins [0.5, 0.6), [0.6, 0.7), [0.7, 0.8), [0.8, 0.9]
RANGE_QUANTILES = (("lo80", 0.10), ("lo50", 0.25), ("hi50", 0.75), ("hi80", 0.90))


def wilson(k: int, n: int, zc: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval for k successes out of n."""
    if not n:
        return None, None
    p = k / n
    den = 1 + zc * zc / n
    mid = (p + zc * zc / (2 * n)) / den
    half = zc * math.sqrt(p * (1 - p) / n + zc * zc / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def _py(p, y) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(p) & np.isfinite(y)
    return p[ok], y[ok]


def _mean(values) -> float | None:
    """Mean of the non-NaN values, summed exactly (math.fsum), so it does not depend on row order."""
    a = np.asarray(values, dtype=float)
    a = a[~np.isnan(a)]
    return math.fsum(a) / len(a) if len(a) else None


def brier(p, y) -> float | None:
    p, y = _py(p, y)
    return _mean((p - y) ** 2)


def log_loss(p, y) -> float | None:
    p, y = _py(p, y)
    if not len(p):
        return None
    p = np.clip(p, EPS, 1 - EPS)
    return -_mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def reliability(p, y, edges=CALL_BINS) -> list[dict]:
    """One row per confidence bin [lo, hi) (the last bin closed): count, mean stated confidence,
    hit rate and its Wilson 95% interval. Empty bins are kept with n = 0."""
    p, y = _py(p, y)
    out = []
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        last = i == len(edges) - 2
        m = (p >= lo) & ((p <= hi) if last else (p < hi))
        n, k = int(m.sum()), int(y[m].sum())
        wl, wh = wilson(k, n)
        out.append({"bin": f"{lo:.2f}-{hi:.2f}", "lo": lo, "hi": hi, "n": n,
                    "mean_conf": _mean(p[m]) if n else None,
                    "hit_rate": k / n if n else None, "wilson_lo": wl, "wilson_hi": wh})
    return out


def call_scores(df: pd.DataFrame) -> dict:
    """Brier, log loss and Brier skill vs a coin flip (1 - Brier / 0.25) for scored calls
    (columns confidence, hit)."""
    if df is None or df.empty:
        return {"n": 0}
    p, y = df["confidence"].astype(float), df["hit"].astype(float)
    b, ll = brier(p, y), log_loss(p, y)
    return {"n": int(len(df)), "brier": _r(b), "log_loss": _r(ll),
            "brier_skill": _r(1 - b / 0.25) if b is not None else None}


def pinball(q_value: float, level: float, y: float) -> float:
    """Pinball (quantile) loss of the `level` quantile forecast q_value for outcome y."""
    return max(level * (y - q_value), (level - 1) * (y - q_value))


def quantile_score(qs: dict[float, float], y: float) -> float:
    """Mean pinball loss over the given {level: value} quantiles."""
    return float(np.mean([pinball(v, lv, y) for lv, v in qs.items()]))


def range_scores_row(lo50, hi50, lo80, hi80, y, base) -> dict:
    """Interval scores (50%, 80%) and quantile score of one scored range, in % of base."""
    vals = {"lo50": lo50, "hi50": hi50, "lo80": lo80, "hi80": hi80}
    qs = {lv: float(vals[k]) for k, lv in RANGE_QUANTILES}
    return {"is50_pct": 100 * rl.interval_score(lo50, hi50, y, 0.5) / base,
            "is80_pct": 100 * rl.interval_score(lo80, hi80, y, 0.8) / base,
            "qs_pct": 100 * quantile_score(qs, y) / base}


def range_scores(df: pd.DataFrame) -> dict:
    """Coverage, interval scores, quantile score and width for scored ranges (columns lo50, hi50,
    lo80, hi80, actual_close, base_close, hit50, hit80)."""
    if df is None or df.empty:
        return {"n": 0}
    rows = [range_scores_row(*(float(x) for x in r))
            for r in df[["lo50", "hi50", "lo80", "hi80", "actual_close", "base_close"]].itertuples(index=False)]
    s = pd.DataFrame(rows)
    base = df["base_close"].astype(float)
    return {"n": int(len(df)), "cover50": _r(_mean(df["hit50"].astype(float))),
            "cover80": _r(_mean(df["hit80"].astype(float))),
            "is50_pct": _r(_mean(s["is50_pct"])), "is80_pct": _r(_mean(s["is80_pct"])),
            "qs_pct": _r(_mean(s["qs_pct"])),
            "width50_pct": _r(_mean(100 * (df["hi50"] - df["lo50"]) / base)),
            "width80_pct": _r(_mean(100 * (df["hi80"] - df["lo80"]) / base))}


def _r(x, k: int = 4):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), k)


# ---------- track-record summary (score_predictions, context pack, review, HTML) ----------

def summary(con) -> dict:
    """All-time proper scores from the scored track record: calls per horizon and overall
    (Brier, log loss, reliability) and ranges per horizon (coverage, interval and quantile scores)."""
    calls = con.execute("SELECT horizon_days, confidence, hit FROM track_record "
                        "WHERE confidence IS NOT NULL AND hit IS NOT NULL ORDER BY id, scored_at").df()
    rng = con.execute("SELECT horizon_days, lo50, hi50, lo80, hi80, actual_close, base_close, hit50, hit80 "
                      "FROM range_record WHERE actual_close IS NOT NULL ORDER BY id").df()
    out = {"calls": {"all": call_scores(calls)}, "ranges": {}}
    out["calls"]["all"]["reliability"] = reliability(calls["confidence"], calls["hit"]) if len(calls) else []
    for h, g in (calls.groupby("horizon_days") if len(calls) else []):
        out["calls"][f"{int(h)}d"] = call_scores(g)
    for h, g in (rng.groupby("horizon_days") if len(rng) else []):
        out["ranges"][f"{int(h)}d"] = range_scores(g)
    return out


def _f(v, k: int = 3) -> str:
    return "–" if v is None else f"{v:.{k}f}"


def _p(v) -> str:
    return "–" if v is None else f"{100 * v:.0f}%"


def markdown(s: dict) -> str:
    """Compact Markdown for the context pack."""
    calls = s["calls"]
    lines = ["Calls: Brier (coin flip 0.250) and log loss (coin flip 0.693), lower is better; "
             "skill = 1 - Brier/0.25.", "",
             "| h | n | brier | log_loss | skill |", "|---|---|---|---|---|"]
    for k, v in calls.items():
        lines.append(f"| {k} | {v['n']} | {_f(v.get('brier'))} | {_f(v.get('log_loss'))} | {_f(v.get('brier_skill'))} |")
    rel = [r for r in calls["all"].get("reliability", []) if r["n"]]
    if rel:
        lines += ["", "Reliability (all horizons): stated confidence vs hit rate, Wilson 95%.", "",
                  "| bin | n | mean_conf | hit_rate | 95% |", "|---|---|---|---|---|"]
        lines += [f"| {r['bin']} | {r['n']} | {_p(r['mean_conf'])} | {_p(r['hit_rate'])} | "
                  f"{_p(r['wilson_lo'])}-{_p(r['wilson_hi'])} |" for r in rel]
    lines += ["", "Ranges (all time; % of price, lower is better): interval scores and quantile score "
              "(mean pinball loss over q10/q25/q75/q90).", "",
              "| h | n | cover50 | cover80 | is50 | is80 | qs |", "|---|---|---|---|---|---|---|"]
    for k, v in s["ranges"].items():
        lines.append(f"| {k} | {v['n']} | {_p(v.get('cover50'))} | {_p(v.get('cover80'))} | {_f(v.get('is50_pct'))} | "
                     f"{_f(v.get('is80_pct'))} | {_f(v.get('qs_pct'))} |")
    if not s["ranges"]:
        lines.append("| – | 0 | – | – | – | – | – |")
    return "\n".join(lines) + "\n"
