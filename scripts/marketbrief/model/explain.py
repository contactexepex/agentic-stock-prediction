"""Why a score is what it is: per-feature and per-group contributions in probability points.

In logit units the issued probability decomposes exactly:
    logit(p) = logit(base_rate) + baseline + sum_j a * b_j * z_j + news
with base_rate the training share of up labels, a and c the Platt slope and offset (a = 1, c = 0 when
not calibrated), baseline = a * b0 + c - logit(base_rate) (what the model says for a stock-day with
every feature at its training mean, relative to the base rate) and news the fixed-prior news term.
The items are converted to percentage points by sharing p - base_rate in proportion to their logit
size (pts_i = item_i * 100 * (p - base_rate) / sum of items; when the items cancel, item_i * 100 *
base_rate * (1 - base_rate), the slope at the base rate), so the points add up exactly to
100 * (p - base_rate)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.constants.model import (DRIVER_MIN_POINTS, DRIVER_TEMPLATE, FEATURE_GROUPS, FEATURE_TEXT,
                                         GROUP_BASELINE, GROUP_NEWS,
                                         RSI_NEAR_OVERBOUGHT, RSI_NEAR_OVERSOLD, RSI_OVERBOUGHT, RSI_OVERSOLD,
                                         TEXT_BASELINE, TEXT_NEAR_OVERBOUGHT, TEXT_NEAR_OVERSOLD, TEXT_OVERBOUGHT,
                                         TEXT_OVERSOLD, TOP_DRIVERS, VALUE_FLAG, VALUE_LEVEL, VALUE_PERCENT)
from marketbrief.model.logistic import logit, sigmoid
from marketbrief.model.walk_forward import MonthlyFit

POINTS_DECIMALS = 2
SMALL = 1e-12
HORIZON_SUFFIXES = ("_1d", "_5d")


def base_name(feature: str) -> str:
    """The feature name without a per-horizon suffix (earnings_in_window_5d -> earnings_in_window)."""
    for suffix in HORIZON_SUFFIXES:
        if feature.endswith(suffix) and feature.removesuffix(suffix) in FEATURE_TEXT:
            return feature.removesuffix(suffix)
    return feature


def group_of(feature: str) -> str:
    """The feature's group (FEATURE_GROUPS)."""
    return FEATURE_GROUPS.get(base_name(feature), base_name(feature))


def rsi_phrase(value: float) -> str:
    """oversold / near oversold / near overbought / overbought, or '' in between."""
    if value < RSI_OVERSOLD:
        return TEXT_OVERSOLD
    if value < RSI_NEAR_OVERSOLD:
        return TEXT_NEAR_OVERSOLD
    if value > RSI_OVERBOUGHT:
        return TEXT_OVERBOUGHT
    if value > RSI_NEAR_OVERBOUGHT:
        return TEXT_NEAR_OVERBOUGHT
    return ""


def describe(feature: str, value) -> str:
    """'RSI 33.7, near oversold' style text for a feature and its raw value."""
    label, kind = FEATURE_TEXT.get(base_name(feature), (feature, "plain"))
    if value is None or pd.isna(value):
        return f"{label} missing (taken as its training mean)"
    if kind == VALUE_FLAG:
        return label if value >= 0.5 else f"not {label}"
    if kind == VALUE_PERCENT:
        return f"{label} {value * 100:+.1f}%"
    if kind == VALUE_LEVEL:
        return f"{label} {value * 100:.1f}%"
    text = f"{label} {value:.1f}" if base_name(feature) == "rsi_14" else f"{label} {value:.2f}"
    phrase = rsi_phrase(value) if base_name(feature) == "rsi_14" else ""
    return f"{text}, {phrase}" if phrase else text


def to_points(items: np.ndarray, base_rate: float, prob: float) -> np.ndarray:
    """Logit items -> percentage points that sum to 100 * (prob - base_rate)."""
    total = float(items.sum())
    if abs(total) < SMALL:
        return items * 100 * base_rate * (1 - base_rate)
    return items * 100 * (prob - base_rate) / total


def explain_row(fit: MonthlyFit, row: pd.DataFrame, news_logit: float = 0.0, news_text: str = "") -> dict:
    """The full explanation of one scored row (a one-row frame): probabilities, logit items, points per
    feature and group, the top TOP_DRIVERS up and down drivers in plain language, missing features."""
    model = fit.model
    slope, offset = fit.platt if fit.platt is not None else (1.0, 0.0)
    terms = slope * model.contributions(row)[0]
    baseline = slope * model.intercept + offset - float(logit(fit.base_rate))
    items = np.concatenate([[baseline], terms, [news_logit]])
    prob_model = float(sigmoid(float(logit(fit.base_rate)) + items[:-1].sum()))
    prob = float(sigmoid(float(logit(fit.base_rate)) + items.sum()))
    points = to_points(items, fit.base_rate, prob)
    names = [GROUP_BASELINE, *model.features, GROUP_NEWS]
    texts = [TEXT_BASELINE, *(describe(f, row[f].iloc[0]) for f in model.features), news_text or GROUP_NEWS]
    groups: dict[str, float] = {}
    for name, value in zip(names, points, strict=True):
        key = name if name in (GROUP_BASELINE, GROUP_NEWS) else group_of(name)
        groups[key] = groups.get(key, 0.0) + float(value)
    drivers = [(names[i], texts[i], float(points[i])) for i in range(1, len(names))
               if abs(points[i]) >= DRIVER_MIN_POINTS]
    ups = sorted((d for d in drivers if d[2] > 0), key=lambda d: (-d[2], d[0]))[:TOP_DRIVERS]
    downs = sorted((d for d in drivers if d[2] < 0), key=lambda d: (d[2], d[0]))[:TOP_DRIVERS]
    return {"base_rate": round(fit.base_rate, 4), "prob_model": prob_model, "prob_up": prob,
            "logit_items": {n: float(v) for n, v in zip(names, items, strict=True)},
            "points": {n: round(float(v), POINTS_DECIMALS) for n, v in zip(names, points, strict=True)},
            "groups": {g: round(v, POINTS_DECIMALS) for g, v in sorted(groups.items())},
            "up": [driver_json(d) for d in ups], "down": [driver_json(d) for d in downs],
            "missing": [f for f in model.features if pd.isna(row[f].iloc[0])]}


def driver_json(driver: tuple[str, str, float]) -> dict:
    """{feature, text, points} with the plain-language line."""
    name, text, points = driver
    return {"feature": name, "points": round(points, POINTS_DECIMALS),
            "text": DRIVER_TEMPLATE.format(text=text, points=points)}


def coefficient_table(model) -> list[dict]:
    """Per feature: group, coefficient (logit per 1 sd), training mean and sd; largest |coefficient| first."""
    rows = [{"feature": f, "group": group_of(f), "coefficient": round(c, 4), "mean": m, "sd": s}
            for f, c, m, s in zip(model.features, model.coefficients, model.means, model.sds, strict=True)]
    return sorted(rows, key=lambda r: (-abs(r["coefficient"]), r["feature"]))


def group_importance(model) -> dict[str, float]:
    """Sum of |coefficient| per group (logit per 1 sd): a global importance, largest first."""
    out: dict[str, float] = {}
    for feature, coefficient in zip(model.features, model.coefficients, strict=True):
        out[group_of(feature)] = out.get(group_of(feature), 0.0) + abs(coefficient)
    return {k: round(v, 4) for k, v in sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))}
