"""What the dashboard says about the signal model: its stored formula (base rate, Platt calibration,
coefficients per feature group), the latest weekly review's backtest headline (Brier vs base rate,
AUC, paper long vs baselines after costs) and the skill verdict that decides the "paper only" label.
The verdict is the review's own `model_skill` with the thresholds of config/review.yaml; nothing is
re-decided here. The backtest's reliability table is read from the review's JSON when that file exists."""

from __future__ import annotations

import json

import pandas as pd

from marketbrief.constants.dashboard import (
    MSG_NO_REVIEW,
    MSG_PAPER_ONLY,
    MSG_SKILL_RULE,
    MSG_SKILL_SHOWN,
    SKILL_PAPER,
    SKILL_SHOWN,
)
from marketbrief.core import paths
from marketbrief.model.explain import group_of
from marketbrief.model.settings import load_costs, round_trip_cost
from marketbrief.pipeline.review.helpers import load_review_config
from marketbrief.utils.numbers import json_safe_float


def loaded(value):
    """A JSON column as a Python object (DuckDB returns JSON as text)."""
    if isinstance(value, str):
        return json.loads(value)
    return value if value is not None and not (isinstance(value, float) and pd.isna(value)) else None


def version_view(row) -> dict:
    """One stored fit: training size, base rate, Platt calibration and coefficient sizes per group."""
    model = loaded(row.model) or {}
    by_group: dict[str, float] = {}
    for feature, coefficient in zip(model.get("features", []), model.get("coefficients", []), strict=False):
        by_group[group_of(feature)] = by_group.get(group_of(feature), 0.0) + abs(float(coefficient))
    return {
        "id": row.id,
        "h": int(row.horizon_days),
        "label": row.label_convention,
        "trained_until": pd.Timestamp(row.trained_until).date().isoformat(),
        "fitted_at": pd.Timestamp(row.fitted_at).isoformat(),
        "train_rows": int(row.train_rows),
        "train_sessions": int(row.train_sessions),
        "base_rate": json_safe_float(row.base_rate),
        "intercept": json_safe_float(model.get("intercept")),
        "features": len(model.get("features", [])),
        "platt_slope": json_safe_float(row.platt_slope),
        "platt_offset": json_safe_float(row.platt_offset),
        "platt_rows": None if pd.isna(row.platt_rows) else int(row.platt_rows),
        "group_weight": {g: round(v, 4) for g, v in sorted(by_group.items(), key=lambda kv: (-kv[1], kv[0]))},
    }


def versions_used(versions: pd.DataFrame, model_ids: set[str]) -> list[dict]:
    """The fits behind today's scores, by horizon."""
    rows = versions[versions["id"].isin(model_ids)] if len(versions) else versions
    return [version_view(r) for r in rows.sort_values(["horizon_days", "id"]).itertuples()] if len(rows) else []


def backtest_reliability(model: dict, market: str) -> dict:
    """{key: reliability rows} from the review's backtest JSON, when that file is present."""
    path = paths.ROOT / (model.get("json") or "")
    if not model.get("json") or not path.is_file():
        return {}
    results = (json.loads(path.read_text()).get("results") or {}).get(market) or {}
    return {
        key: [same_keys(row) for row in res["reliability"]]
        for key, res in sorted(results.items())
        if res.get("reliability")
    }


def same_keys(row: dict) -> dict:
    """A backtest reliability row (model/metrics.py) under the keys of scoring.reliability."""
    low, high = row.get("wilson95") or [None, None]
    return {
        "bin": row.get("bin"),
        "n": row.get("n"),
        "mean_conf": row.get("mean_p"),
        "hit_rate": row.get("up_share"),
        "wilson_lo": low,
        "wilson_hi": high,
    }


def skill_status(review: dict | None) -> dict:
    """The label every signal carries: paper only unless the latest review found skill."""
    rules = load_review_config()["model_skill"]
    rule_text = MSG_SKILL_RULE.format(**rules)
    if review is None:
        return {"state": SKILL_PAPER, "label": MSG_PAPER_ONLY, "why": MSG_NO_REVIEW, "rule": rule_text, "review": None}
    shown = review.get("model_skill") is True
    detail = loaded(review.get("detail")) or {}
    verdict = (detail.get("model") or {}).get("verdict")
    return {
        "state": SKILL_SHOWN if shown else SKILL_PAPER,
        "label": MSG_SKILL_SHOWN if shown else MSG_PAPER_ONLY,
        "why": verdict or MSG_NO_REVIEW,
        "rule": rule_text,
        "review": {"id": review.get("id"), "computed_at": pd.Timestamp(review["computed_at"]).isoformat()},
    }


def backtest_view(review: dict | None, market: str) -> dict | None:
    """The review's backtest headline: score rows, paper strategy rows, panel facts and reliability."""
    if review is None:
        return None
    model = (loaded(review.get("detail")) or {}).get("model") or {}
    if "scores" not in model:
        return {"error": model.get("error") or model.get("skipped")}
    return {
        "computed_at": model.get("computed_at"),
        "data": model.get("data"),
        "scores": model.get("scores"),
        "strategy": model.get("strategy"),
        "verdict": model.get("verdict"),
        "json": model.get("json"),
        "reliability": backtest_reliability(model, market),
    }


def cost_at(market: str, price) -> float | None:
    """The round-trip cost fraction of config/costs.yaml at a price (the backtest's cost)."""
    if price is None:
        return None
    return json_safe_float(round_trip_cost(market, load_costs(market), float(price)))
