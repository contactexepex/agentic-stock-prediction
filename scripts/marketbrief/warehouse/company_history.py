"""The company page's forecast history (B12; docs/ws/b12.md): every stored run of ranges.py's published ranges and of
the signal model's scores of the last FORECAST_HISTORY_SESSIONS as-of dates, per horizon, as of the build's cut-off
(owner, 2026-10-10: see how each forecast was calculated and what changed between runs). A run's change is taken
against the previous stored run of the same company and horizon: the target and 80% width moves, P(up) and the points
per feature group, the news items added or dropped and the inputs that changed (model, calibration, regime, range
inputs). Ranges and scores are published for every company whatever a strategy's live_from."""
from __future__ import annotations

import json

from marketbrief.analytics.horizon_records import with_window
from marketbrief.constants.horizons import LABEL_N_PLUS_K, SQL_LABEL_MODEL_SCORES, SQL_LABEL_RANGES
from marketbrief.constants.rm_company import (HISTORY_RANGE_CHANGED, HISTORY_RANGE_FIELDS, HISTORY_SCORE_CHANGED,
                                              HISTORY_SCORE_FIELDS)
from marketbrief.lab.strategies import target_price
from marketbrief.warehouse.news_items import iso
from marketbrief.warehouse.rm_registry import BuildContext

# every stored run (each id once per made_at / computed_at) of the window's N+k rows, stored by the cut-off; the
# horizon label is B10's rule (old open-to-close 1-day scores count as N+1, analytics/horizon_records.py)
RANGES_SQL = f"""
WITH runs AS (
    SELECT DISTINCT ON (id, made_at) * REPLACE ({SQL_LABEL_RANGES} AS horizon_label) FROM ranges
    WHERE made_at <= $cutoff::TIMESTAMPTZ AND as_of_date BETWEEN $first::DATE AND $as_of::DATE
    ORDER BY id, made_at, lo80, hi80
)
SELECT * FROM runs WHERE horizon_label = '{LABEL_N_PLUS_K}' ORDER BY id, made_at"""
SCORES_SQL = f"""
WITH runs AS (
    SELECT DISTINCT ON (id, computed_at) * REPLACE ({SQL_LABEL_MODEL_SCORES} AS horizon_label) FROM model_scores
    WHERE computed_at <= $cutoff::TIMESTAMPTZ AND as_of_date BETWEEN $first::DATE AND $as_of::DATE
    ORDER BY id, computed_at, prob_up, model_id
)
SELECT * FROM runs WHERE horizon_label = '{LABEL_N_PLUS_K}' ORDER BY id, computed_at"""
PCT = 100.0
DIGITS = 4


def records(con, sql: str, params: dict) -> list[dict]:
    """The query's rows as dicts of plain Python values (lists, dates, None; no pandas types)."""
    cursor = con.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]


def day(value) -> str | None:
    return None if value is None else str(value)[:10]


def pct_move(new: float | None, old: float | None) -> float | None:
    """The move from `old` to `new` in percent of `old` (None when either is missing)."""
    return None if new is None or not old else round((new / old - 1) * PCT, DIGITS)


def changed(row: dict, previous: dict, fields: tuple[str, ...]) -> list[str]:
    """The fields whose value differs from the previous run's."""
    return [name for name in fields if row.get(name) != previous.get(name)]


def range_row(rec: dict) -> dict:
    """One stored range run in the page's fields (dates as YYYY-MM-DD, made_at as ISO Z)."""
    row = {name: rec.get(name) for name in HISTORY_RANGE_FIELDS}
    row.update(made_at=iso(rec["made_at"]), as_of_date=day(rec["as_of_date"]), session_date=day(rec["session_date"]),
               exit_date=day(rec["exit_date"]), target_price=target_price(rec, None),
               inputs=list(rec.get("inputs") or []), notes=list(rec.get("notes") or []))
    return row


def range_change(row: dict, previous: dict | None) -> dict | None:
    """How a range run differs from the previous run of its company and horizon (None for the first)."""
    if previous is None:
        return None
    width, before = row["hi80"] - row["lo80"], previous["hi80"] - previous["lo80"]
    return {"from_id": previous["id"], "from_made_at": previous["made_at"],
            "target_pct": pct_move(row["target_price"], previous["target_price"]),
            "width80_pct": pct_move(width, before), "changed": changed(row, previous, HISTORY_RANGE_CHANGED)}


def score_row(rec: dict) -> dict:
    """One stored score run: P(up), its model, the points per feature group, the strongest drivers each way and
    the news items it counted (the score's explanation, model/explain.py)."""
    explain = rec.get("contributions")
    explain = json.loads(explain) if isinstance(explain, str) else (explain or {})
    news = explain.get("news") or {}
    row = {name: rec.get(name) for name in HISTORY_SCORE_FIELDS}
    row.update(computed_at=iso(rec["computed_at"]), as_of_date=day(rec["as_of_date"]),
               entry_date=day(rec["entry_date"]), exit_date=day(rec["exit_date"]),
               trained_until=day(rec.get("trained_until")), groups=explain.get("groups") or {},
               drivers_up=explain.get("up") or [], drivers_down=explain.get("down") or [],
               news_items=news.get("items"), news_ids=list(news.get("ids") or []))
    return row


def score_change(row: dict, previous: dict | None) -> dict | None:
    """How a score run differs from the previous run of its company and horizon (None for the first): the P(up)
    move as a fraction (0.01 = one percentage point), the feature groups whose points moved, the news ids added
    and dropped."""
    if previous is None:
        return None
    groups = sorted(set(row["groups"]) | set(previous["groups"]))
    moved = {name: round((row["groups"].get(name) or 0.0) - (previous["groups"].get(name) or 0.0), DIGITS)
             for name in groups}
    return {"from_id": previous["id"], "from_computed_at": previous["computed_at"],
            "prob_up": None if None in (row["prob_up"], previous["prob_up"])
            else round(row["prob_up"] - previous["prob_up"], DIGITS),
            "groups": {name: points for name, points in moved.items() if points},
            "news_added": [item for item in row["news_ids"] if item not in previous["news_ids"]],
            "news_dropped": [item for item in previous["news_ids"] if item not in row["news_ids"]],
            "changed": changed(row, previous, HISTORY_SCORE_CHANGED)}


def with_changes(rows: list[dict], time_key: str, change) -> list[dict]:
    """The runs per company and horizon in time order, each with its change from the run before."""
    ordered = sorted(rows, key=lambda row: (row["ticker"], row["horizon_days"], row[time_key], row["id"]))
    previous: dict[tuple, dict] = {}
    for row in ordered:
        key = (row["ticker"], row["horizon_days"])
        row["change"] = change(row, previous.get(key))
        previous[key] = row
    return ordered


def forecast_history(ctx: BuildContext, first_day: str | None, as_of: str | None) -> dict[str, dict]:
    """ticker -> {ranges, scores}: every stored run of the as-of dates first_day..as_of, by horizon then time, of
    the collected companies; {} without a window."""
    if not (first_day and as_of):
        return {}
    params = {"cutoff": ctx.cutoff, "first": first_day, "as_of": as_of}
    ranges = [range_row(with_window(ctx.cfg, rec)) for rec in records(ctx.con, RANGES_SQL, params)
              if rec["ticker"] in ctx.collected]
    scores = [score_row(with_window(ctx.cfg, rec)) for rec in records(ctx.con, SCORES_SQL, params)
              if rec["ticker"] in ctx.collected]
    history: dict[str, dict] = {}
    for kind, rows in (("ranges", with_changes(ranges, "made_at", range_change)),
                       ("scores", with_changes(scores, "computed_at", score_change))):
        for row in rows:
            history.setdefault(row["ticker"], {"ranges": [], "scores": []})[kind].append(row)
    return history
