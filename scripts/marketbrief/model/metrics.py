"""Out-of-sample probability scores of the signal model (library, pure functions).

- Brier = mean((p - y)^2), log loss = -mean(y ln p + (1 - y) ln(1 - p)), both lower is better; the
  reference is the base rate known at each refit (the training share of ups), never the test period's;
  Brier skill = 1 - Brier / Brier(base rate).
- AUC = probability that a random up row has a higher p than a random down row (Mann-Whitney, ties 1/2).
- Reliability: rows binned by p, with count, mean p, observed up share and its Wilson 95% interval.
- Hit rates at a threshold t: long when p >= t (hit = return > 0), short when p <= 1 - t (hit = return < 0),
  with coverage = share of stock-days that qualify.
- Intervals for means and differences: moving-block bootstrap over as-of dates (blocks of `block`
  consecutive dates: every stock shares a date, and multi-day outcomes overlap), percentile 95%."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.analytics.scoring import wilson

DECIMALS = 4


def r(value) -> float | None:
    """Rounded to DECIMALS, None for missing."""
    return None if value is None or not np.isfinite(value) else round(float(value), DECIMALS)


def brier(p, y) -> float:
    """Mean squared error of probabilities."""
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def log_loss(p, y) -> float:
    """Mean negative log likelihood (p clipped to 1e-6 .. 1 - 1e-6)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(p, y) -> float | None:
    """Area under the ROC curve by ranks (ties count 1/2); None without both classes."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    positives, negatives = int((y == 1).sum()), int((y == 0).sum())
    if not positives or not negatives:
        return None
    ranks = pd.Series(p).rank(method="average").to_numpy()
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def reliability(p, y, edges) -> list[dict]:
    """Per bin [edge_i, edge_i+1) (the last closed): n, mean p, up share and its Wilson interval."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    out = []
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        inside = (p >= lo) & ((p <= hi) if i == len(edges) - 2 else (p < hi))
        n, k = int(inside.sum()), int(y[inside].sum())
        low, high = wilson(k, n)
        out.append({"bin": f"[{lo:.2f}, {hi:.2f}{']' if i == len(edges) - 2 else ')'}", "n": n,
                    "mean_p": r(p[inside].mean()) if n else None, "up_share": r(k / n) if n else None,
                    "wilson95": [r(low) if low is not None else None, r(high) if high is not None else None]})
    return out


def threshold_hits(frame: pd.DataFrame, threshold: float, cost) -> dict:
    """Long (p >= t) and short (p <= 1 - t) hit rates, coverage and Wilson intervals; `cost` per row for
    the cost-aware long hit (return > cost)."""
    out = {}
    total = len(frame)
    for side, chosen, hit in (("long", frame["prob"] >= threshold, frame["ret"] > 0),
                              ("short", frame["prob"] <= 1 - threshold, frame["ret"] < 0)):
        n, k = int(chosen.sum()), int((hit & chosen).sum())
        low, high = wilson(k, n)
        out[side] = {"n": n, "coverage": r(n / total) if total else None, "hit_rate": r(k / n) if n else None,
                     "wilson95": [r(low) if low is not None else None, r(high) if high is not None else None]}
    long_rows = frame["prob"] >= threshold
    beat = (frame["ret"] > cost)[long_rows]
    out["long"]["hit_after_cost"] = r(beat.mean()) if long_rows.any() else None
    return out


def block_bootstrap(series: pd.Series, block: int, samples: int, seed: int) -> tuple[float | None, float | None]:
    """95% percentile interval of the mean of a date-indexed series by moving-block bootstrap."""
    values = series.dropna().to_numpy(dtype=float)
    n = len(values)
    if n < 2:
        return None, None
    block = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - block + 1, size=(samples, int(np.ceil(n / block))))
    index = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(samples, -1)[:, :n]
    means = values[index].mean(axis=1)
    return r(np.percentile(means, 2.5)), r(np.percentile(means, 97.5))


def daily_auc_interval(frame: pd.DataFrame, block: int, samples: int, seed: int) -> tuple[float | None, float | None]:
    """95% interval of the AUC by resampling blocks of as-of dates (moving-block bootstrap)."""
    ordered = frame.sort_values("date")
    codes, starts = np.unique(ordered["date"].to_numpy(), return_index=True)
    n = len(codes)
    if n < 2:
        return None, None
    bounds = list(starts) + [len(ordered)]
    probs, ups = ordered["prob"].to_numpy(dtype=float), ordered["up"].to_numpy(dtype=float)
    rows = [np.arange(bounds[i], bounds[i + 1]) for i in range(n)]
    rng = np.random.default_rng(seed)
    block = max(1, min(block, n))
    values = []
    for _ in range(samples):
        first = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
        picked = (first[:, None] + np.arange(block)[None, :]).ravel()[:n]
        index = np.concatenate([rows[i] for i in picked])
        value = auc(probs[index], ups[index])
        if value is not None:
            values.append(value)
    return (r(np.percentile(values, 2.5)), r(np.percentile(values, 97.5))) if values else (None, None)


def probability_scores(frame: pd.DataFrame, settings: dict, block: int) -> dict:
    """Brier, log loss, AUC (with interval), base-rate references and the reliability table of resolved rows."""
    p, y, base = frame["prob"], frame["up"], frame["base_rate"]
    boot = settings["backtest"]
    model_brier, base_brier = brier(p, y), brier(base, y)
    return {"n": int(len(frame)), "dates": int(frame["date"].nunique()),
            "first_date": str(frame["date"].min().date()), "last_date": str(frame["date"].max().date()),
            "up_share": r(y.mean()), "brier": r(model_brier), "brier_base_rate": r(base_brier),
            "brier_skill": r(1 - model_brier / base_brier) if base_brier else None,
            "brier_raw": r(brier(frame["prob_raw"], y)),
            "log_loss": r(log_loss(p, y)), "log_loss_base_rate": r(log_loss(base, y)),
            "auc": r(auc(p, y)), "auc_raw": r(auc(frame["prob_raw"], y)),
            "auc95": list(daily_auc_interval(frame, block, boot["bootstrap_samples"], boot["bootstrap_seed"])),
            "calibrated_share": r(frame["calibrated"].mean()),
            "reliability": reliability(p, y, boot["reliability_edges"])}
