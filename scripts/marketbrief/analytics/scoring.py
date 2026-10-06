"""Proper scores for the track record (library, pure functions; docs/DESIGN.md section 6).

Direction calls: a call states the probability `confidence` (0.50-0.90) that its direction is
right; the outcome is `hit` (1/0).
- Brier score  = mean((p - y)^2); a coin flip (p = 0.5 always) scores 0.25. Lower is better.
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
from marketbrief.constants.scoring import CALL_BINS, COIN_FLIP_BRIER, EPS, MISSING_DASH, RANGE_QUANTILES, WILSON_Z
from marketbrief.utils.numbers import round_or_none


def wilson(k: int, n: int, zc: float = WILSON_Z) -> tuple[float | None, float | None]:
    """Wilson score interval for k successes out of n."""
    if not n:
        return None, None
    p = k / n
    den = 1 + zc * zc / n
    mid = (p + zc * zc / (2 * n)) / den
    half = zc * math.sqrt(p * (1 - p) / n + zc * zc / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def finite_pairs(p, y) -> tuple[np.ndarray, np.ndarray]:
    """The (p, y) pairs where both are finite, as float arrays."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(p) & np.isfinite(y)
    return p[ok], y[ok]


def exact_mean(values) -> float | None:
    """Mean of the non-NaN values, computed exactly (rational sum, rounded once), so it does not depend
    on row order: the mean of n copies of 0.7 is 0.7. An infinite value gives the float mean."""
    a = np.asarray(values, dtype=float)
    a = a[~np.isnan(a)]
    if not len(a):
        return None
    return float(sum(map(Fraction, a.tolist()), Fraction(0)) / len(a)) if np.isfinite(a).all() else float(a.mean())


def brier(p, y) -> float | None:
    """The Brier score: mean((p - y)^2) over the finite pairs."""
    p, y = finite_pairs(p, y)
    return exact_mean((p - y) ** 2)


def log_loss(p, y) -> float | None:
    """The log loss: -mean(y ln p + (1 - y) ln(1 - p)) over the finite pairs (p clipped away from 0 and 1)."""
    p, y = finite_pairs(p, y)
    if not len(p):
        return None
    p = np.clip(p, EPS, 1 - EPS)
    return -exact_mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def reliability(p, y, edges=CALL_BINS) -> list[dict]:
    """One row per confidence bin [lo, hi) (the last bin closed): count, mean stated confidence,
    hit rate and its Wilson 95% interval. Empty bins are kept with n = 0."""
    p, y = finite_pairs(p, y)
    out = []
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        last = i == len(edges) - 2
        m = (p >= lo) & ((p <= hi) if last else (p < hi))
        n, k = int(m.sum()), int(y[m].sum())
        wl, wh = wilson(k, n)
        out.append(
            {
                "bin": f"{lo:.2f}-{hi:.2f}",
                "lo": lo,
                "hi": hi,
                "n": n,
                "mean_conf": exact_mean(p[m]) if n else None,
                "hit_rate": k / n if n else None,
                "wilson_lo": wl,
                "wilson_hi": wh,
            }
        )
    return out


def call_scores(df: pd.DataFrame) -> dict:
    """Brier, log loss and Brier skill vs a coin flip (1 - Brier / 0.25) for scored calls
    (columns confidence, hit)."""
    if df is None or df.empty:
        return {"n": 0}
    p, y = df["confidence"].astype(float), df["hit"].astype(float)
    b, ll = brier(p, y), log_loss(p, y)
    return {
        "n": int(len(df)),
        "brier": round_or_none(b),
        "log_loss": round_or_none(ll),
        "brier_skill": round_or_none(1 - b / COIN_FLIP_BRIER) if b is not None else None,
    }


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
    return {
        "is50_pct": 100 * range_math.interval_score(lo50, hi50, y, 0.5) / base,
        "is80_pct": 100 * range_math.interval_score(lo80, hi80, y, 0.8) / base,
        "qs_pct": 100 * quantile_score(qs, y) / base,
    }


def range_scores(df: pd.DataFrame) -> dict:
    """Coverage, interval scores, quantile score and width for scored ranges (columns lo50, hi50,
    lo80, hi80, actual_close, base_close, hit50, hit80)."""
    if df is None or df.empty:
        return {"n": 0}
    rows = [
        range_scores_row(*(float(x) for x in r))
        for r in df[["lo50", "hi50", "lo80", "hi80", "actual_close", "base_close"]].itertuples(index=False)
    ]
    s = pd.DataFrame(rows)
    base = df["base_close"].astype(float)
    return {
        "n": int(len(df)),
        "cover50": round_or_none(exact_mean(df["hit50"].astype(float))),
        "cover80": round_or_none(exact_mean(df["hit80"].astype(float))),
        "is50_pct": round_or_none(exact_mean(s["is50_pct"])),
        "is80_pct": round_or_none(exact_mean(s["is80_pct"])),
        "qs_pct": round_or_none(exact_mean(s["qs_pct"])),
        "width50_pct": round_or_none(exact_mean(100 * (df["hi50"] - df["lo50"]) / base)),
        "width80_pct": round_or_none(exact_mean(100 * (df["hi80"] - df["lo80"]) / base)),
    }


# ---------- track-record summary (score_predictions, context pack, review, HTML) ----------


def summary(con) -> dict:
    """All-time proper scores from the scored track record: calls per horizon and overall
    (Brier, log loss, reliability) and ranges per horizon (coverage, interval and quantile scores)."""
    calls = con.execute(
        "SELECT horizon_days, confidence, hit FROM track_record "
        "WHERE confidence IS NOT NULL AND hit IS NOT NULL ORDER BY id, scored_at"
    ).df()
    rng = con.execute(
        "SELECT horizon_days, lo50, hi50, lo80, hi80, actual_close, base_close, hit50, hit80 "
        "FROM range_record WHERE actual_close IS NOT NULL ORDER BY id"
    ).df()
    out = {"calls": {"all": call_scores(calls)}, "ranges": {}}
    out["calls"]["all"]["reliability"] = reliability(calls["confidence"], calls["hit"]) if len(calls) else []
    for horizon, g in calls.groupby("horizon_days") if len(calls) else []:
        out["calls"][f"{int(horizon)}d"] = call_scores(g)
    for horizon, g in rng.groupby("horizon_days") if len(rng) else []:
        out["ranges"][f"{int(horizon)}d"] = range_scores(g)
    return out


def format_number(value, digits: int = 3) -> str:
    """A number with `digits` decimals, '–' when missing."""
    return MISSING_DASH if value is None else f"{value:.{digits}f}"


def percent(v, digits: int = 0, sign: bool = False) -> str:
    """A share (0.625) as a percent rounded half up on its decimal value ('63%', digits=1 '62.5%',
    sign=True '+63%'); '–' for a missing or non-finite value. The one convention for printed whole
    percents, also in the HTML report's JavaScript (pct0). Domain: finite values below about 1e26 in
    magnitude (shares are 0 to 1); larger ones raise decimal.InvalidOperation."""
    if v is None or not math.isfinite(float(v)):
        return MISSING_DASH
    value = Decimal(repr(float(v))).scaleb(2).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP)
    return f"{value:+}%" if sign else f"{value}%"


def format_percent(value) -> str:
    """A share as a whole percent, '–' when missing."""
    return MISSING_DASH if value is None else percent(value)


def markdown(s: dict) -> str:
    """Compact Markdown for the context pack."""
    calls = s["calls"]
    lines = [
        "Calls: Brier (coin flip 0.250) and log loss (coin flip 0.693), lower is better; skill = 1 - Brier/0.25.",
        "",
        "| h | n | brier | log_loss | skill |",
        "|---|---|---|---|---|",
    ]
    for k, v in calls.items():
        lines.append(
            f"| {k} | {v['n']} | {format_number(v.get('brier'))} | {format_number(v.get('log_loss'))} | "
            f"{format_number(v.get('brier_skill'))} |"
        )
    rel = [r for r in calls["all"].get("reliability", []) if r["n"]]
    if rel:
        lines += [
            "",
            "Reliability (all horizons): stated confidence vs hit rate, Wilson 95%.",
            "",
            "| bin | n | mean_conf | hit_rate | 95% |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {r['bin']} | {r['n']} | {format_percent(r['mean_conf'])} | {format_percent(r['hit_rate'])} | "
            f"{format_percent(r['wilson_lo'])}-{format_percent(r['wilson_hi'])} |"
            for r in rel
        ]
    lines += [
        "",
        "Ranges (all time; % of price, lower is better): interval scores and quantile score "
        "(mean pinball loss over q10/q25/q75/q90).",
        "",
        "| h | n | cover50 | cover80 | is50 | is80 | qs |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, v in s["ranges"].items():
        lines.append(
            f"| {k} | {v['n']} | {format_percent(v.get('cover50'))} | {format_percent(v.get('cover80'))} | "
            f"{format_number(v.get('is50_pct'))} | {format_number(v.get('is80_pct'))} | "
            f"{format_number(v.get('qs_pct'))} |"
        )
    if not s["ranges"]:
        lines.append("| – | 0 | – | – | – | – | – |")
    return "\n".join(lines) + "\n"
