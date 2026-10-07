"""Proof status of the signals: the deterministic criterion of config/portfolio.yaml `proof`, as of the clock.

A (horizon, confidence band) cell is proven only when the newest weekly review stored by the clock has
model_skill true (when proof.require_model_skill), and the forecaster's calls scored on proof.basis only
(open_to_close; never pooled with close_to_close), made and scored by the clock, in that horizon and band number
at least proof.min_count with a Wilson 95% lower bound of the hit rate >= proof.min_wilson_low. The market is
proven when any cell is."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from marketbrief.analytics.scoring import wilson
from marketbrief.portfolio.constants import PROOF_NOT_PROVEN, PROOF_PROVEN
from marketbrief.portfolio.horizons import horizons, is_n_plus_k, label_sql

RULE_TEXT = ("proven = weekly review model_skill true{skill} and, per horizon and confidence band, >= {min_count} "
             "scored {basis} calls with Wilson 95% low >= {min_wilson_low}")


def latest_review(con, clock: datetime) -> dict | None:
    """The newest weekly review stored by the clock (reviews.computed_at <= clock), or None."""
    rows = con.execute("SELECT id, computed_at, model_skill FROM reviews WHERE computed_at <= ? "
                       "ORDER BY computed_at DESC, id DESC LIMIT 1", [clock]).fetchall()
    return None if not rows else {"id": rows[0][0], "computed_at": rows[0][1], "model_skill": rows[0][2]}


def scored_calls(con, clock: datetime, basis: str) -> pd.DataFrame:
    """Calls made by the clock with their first outcome scored by the clock, on `basis` only, that measure N+k
    (portfolio/horizons.py: the legacy 5-day calls are never pooled with N+5)."""
    frame = con.execute(
        f"SELECT p.id, p.horizon_days, {label_sql(con, 'predictions', 'p.')}, p.confidence, o.hit FROM "
        "(SELECT DISTINCT ON (id) * FROM predictions WHERE made_at <= ? ORDER BY id, made_at) p JOIN "
        "(SELECT DISTINCT ON (prediction_id) * FROM outcomes WHERE scored_at <= ? ORDER BY prediction_id, scored_at) o "
        "ON o.prediction_id = p.id WHERE coalesce(o.label_basis, 'close_to_close') = ? AND o.hit IS NOT NULL "
        "ORDER BY p.id", [clock, clock, basis]).df()
    if frame.empty:
        return frame
    keep = [is_n_plus_k(h, None if pd.isna(label) else label)
            for h, label in zip(frame["horizon_days"], frame["horizon_label"])]
    return frame[keep].reset_index(drop=True)


def band_of(confidence: float | None, edges: list[float]) -> str | None:
    """The band label 'lo-hi' of a confidence ([lo, hi), the last band closed), or None outside the bands."""
    if confidence is None or confidence != confidence:
        return None
    for low, high in zip(edges[:-1], edges[1:]):
        if low <= confidence < high or (high == edges[-1] and confidence == high):
            return f"{low:.1f}-{high:.1f}"
    return None


def proof_status(con, clock: datetime, settings: dict) -> dict:
    """{status, model_skill, review, basis, rule, cells: [{horizon_days, band, n, hits, hit_rate, wilson_low,
    wilson_high, proven}]} as of the clock."""
    rules = settings["proof"]
    review = latest_review(con, clock)
    skill = review is not None and review.get("model_skill") is True
    skill_ok = skill or not rules["require_model_skill"]
    calls = scored_calls(con, clock, rules["basis"])
    if not calls.empty:
        calls["band"] = [band_of(c, rules["bands"]) for c in calls["confidence"]]
    cells = []
    edges = rules["bands"]
    for horizon in horizons():
        for low, high in zip(edges[:-1], edges[1:]):
            band = f"{low:.1f}-{high:.1f}"
            rows = calls[(calls["horizon_days"] == horizon) & (calls["band"] == band)] if not calls.empty else calls
            n, hits = len(rows), int(rows["hit"].astype(bool).sum()) if len(rows) else 0
            low_ci, high_ci = wilson(hits, n)
            proven = bool(skill_ok and n >= rules["min_count"] and low_ci is not None
                          and low_ci >= rules["min_wilson_low"])
            cells.append({"horizon_days": horizon, "band": band, "n": n, "hits": hits,
                          "hit_rate": round(hits / n, 4) if n else None,
                          "wilson_low": None if low_ci is None else round(low_ci, 4),
                          "wilson_high": None if high_ci is None else round(high_ci, 4), "proven": proven})
    status = PROOF_PROVEN if any(cell["proven"] for cell in cells) else PROOF_NOT_PROVEN
    rule = RULE_TEXT.format(skill="" if rules["require_model_skill"] else " (not required)", **rules)
    return {"status": status, "model_skill": review.get("model_skill") if review else None,
            "review": None if review is None else {"id": review["id"],
                                                    "computed_at": pd.Timestamp(review["computed_at"]).isoformat()},
            "basis": rules["basis"], "rule": rule, "cells": cells}


def cell(proof: dict, horizon: int, band: str | None) -> dict | None:
    """The proof cell of a horizon and band, or None."""
    return next((c for c in proof["cells"] if c["horizon_days"] == horizon and c["band"] == band), None)
