"""The inputs of the signal tiers, as of the clock: today's model scores (the newest as-of date scored by the
clock), the forecaster's calls with the same ids, the published ranges and the feature blocks (quality BLOCKED,
days to earnings). Each read keeps only rows stored by the clock; latest-row rules follow sql/views.sql
(model_scores_latest: newest computed_at; ranges_latest and calls: the first row of an id)."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd


def loaded(value):
    """A JSON column as a Python object (DuckDB returns JSON as text)."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def scores_on_latest_date(con, clock: datetime) -> pd.DataFrame:
    """The newest model score per id computed by the clock, on the latest as-of date among them."""
    frame = con.execute(
        "SELECT * FROM (SELECT DISTINCT ON (id) * FROM model_scores WHERE computed_at <= ? "
        "ORDER BY id, computed_at DESC, prob_up, model_id) s "
        "WHERE as_of_date = (SELECT max(as_of_date) FROM model_scores WHERE computed_at <= ?) "
        "ORDER BY ticker, horizon_days", [clock, clock]).df()
    if not frame.empty:
        frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
        frame["contributions"] = frame["contributions"].map(loaded)
    return frame


def calls_by_id(con, clock: datetime, ids: list[str]) -> dict[str, dict]:
    """The forecaster's stored call per id (made by the clock; the first row of an id)."""
    if not ids:
        return {}
    frame = con.execute(
        "SELECT DISTINCT ON (id) id, direction, confidence, model_prob, agent_adjustment, adjustment_reason, made_at "
        "FROM predictions WHERE made_at <= ? AND id IN (SELECT unnest(?)) ORDER BY id, made_at", [clock, ids]).df()
    return {row["id"]: row for row in frame.to_dict("records")}


def ranges_by_id(con, clock: datetime, ids: list[str]) -> dict[str, dict]:
    """The published range per id (made by the clock; the first row of an id, as ranges_latest)."""
    if not ids:
        return {}
    frame = con.execute(
        "SELECT DISTINCT ON (id) id, target_date, base_close, lo50, hi50, lo80, hi80 FROM ranges "
        "WHERE made_at <= ? AND id IN (SELECT unnest(?)) ORDER BY id, made_at", [clock, ids]).df()
    out = {}
    for row in frame.to_dict("records"):
        target = row["target_date"]
        row["target_date"] = None if pd.isna(target) else pd.Timestamp(target).date().isoformat()
        out[row.pop("id")] = row
    return out


def feature_blocks(con, clock: datetime, as_of) -> dict[str, dict]:
    """{ticker: {quality, days_to_earnings}} of the newest feature row of the as-of date computed by the clock."""
    frame = con.execute(
        "SELECT DISTINCT ON (ticker) ticker, quality, days_to_earnings FROM features "
        "WHERE as_of_date = ? AND computed_at <= ? ORDER BY ticker, computed_at DESC", [as_of, clock]).df()
    return {row["ticker"]: row for row in frame.to_dict("records")}
