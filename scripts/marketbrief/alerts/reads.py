"""The stored records each post needs, read through DuckDB (core.database.connect) as of the run's clock
(MB_NOW-aware): nothing made, checked, settled or written after `now` is used."""
from __future__ import annotations

import json
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from marketbrief.constants.kinds import (
    KIND_COMMAND_LOG,
    KIND_EOD_ANALYSES,
    KIND_HEAD_TO_HEAD_PICKS,
    KIND_PAPER_TRADES_SETTLED,
    KIND_RESEARCH_REVIEWS,
    KIND_STRATEGY_PREDICTIONS,
    KIND_TRADE_CHECKS,
)
from marketbrief.core.schemas import SCHEMAS


def plain(value, is_json: bool = False):
    """A DuckDB/pandas value as plain JSON-ready Python (ISO strings for times and dates)."""
    if isinstance(value, np.ndarray | list):
        return [plain(v) for v in list(value)]
    if value is pd.NaT or value is None:
        return None
    if isinstance(value, pd.Timestamp | datetime | date):
        return value.isoformat()
    value = value.item() if isinstance(value, np.generic) else value
    if isinstance(value, float) and math.isnan(value):
        return None
    return json.loads(value) if is_json and isinstance(value, str) else value


def records(con, kind: str, sql: str, params: list) -> list[dict]:
    """Rows of a query on one kind as dicts, its JSON columns parsed."""
    json_cols = {c for c, t in SCHEMAS[kind][1].items() if t == "JSON"}
    frame = con.execute(sql, params).df()
    return [{c: plain(v, c in json_cols) for c, v in row.items()} for row in frame.to_dict("records")]


def session_predictions(con, session_date: str, now: datetime) -> list[dict]:
    """The session's strategy predictions made by `now` (one row per id, the first made)."""
    return records(con, KIND_STRATEGY_PREDICTIONS, f"""
        SELECT * FROM {KIND_STRATEGY_PREDICTIONS} WHERE session_date = ?::DATE AND made_at <= ?::TIMESTAMPTZ
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY made_at) = 1 ORDER BY id""", [session_date, now])


def session_picks(con, session_date: str, now: datetime) -> list[dict]:
    """The session's head-to-head picks made by `now`."""
    return records(con, KIND_HEAD_TO_HEAD_PICKS, f"""
        SELECT * FROM {KIND_HEAD_TO_HEAD_PICKS} WHERE session_date = ?::DATE AND made_at <= ?::TIMESTAMPTZ
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY made_at) = 1 ORDER BY id""", [session_date, now])


def latest_check(con, session_date: str, now: datetime, check_id: str | None = None) -> list[dict]:
    """The trade checks of one check run of the session (the newest by `now` unless `check_id` is given)."""
    if check_id is None:
        newest = con.execute(f"""SELECT check_id FROM {KIND_TRADE_CHECKS} WHERE session_date = ?::DATE
            AND check_at <= ?::TIMESTAMPTZ ORDER BY check_at DESC, check_id DESC LIMIT 1""",
                             [session_date, now]).fetchone()
        if newest is None:
            return []
        check_id = newest[0]
    return records(con, KIND_TRADE_CHECKS, f"""
        SELECT * FROM {KIND_TRADE_CHECKS} WHERE check_id = ? AND check_at <= ?::TIMESTAMPTZ
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY computed_at) = 1 ORDER BY id""", [check_id, now])


def settled_today(con, session_date: str, timezone: str, now: datetime) -> list[dict]:
    """Settlement rows written on the session's local date by `now` (a later correction of the same trade
    settled that day replaces the earlier row)."""
    return records(con, KIND_PAPER_TRADES_SETTLED, f"""
        SELECT * FROM {KIND_PAPER_TRADES_SETTLED}
        WHERE CAST(timezone(?, settled_at) AS DATE) = ?::DATE AND settled_at <= ?::TIMESTAMPTZ
        QUALIFY row_number() OVER (PARTITION BY trade_id ORDER BY settled_at DESC, id DESC) = 1
        ORDER BY trade_id""", [timezone, session_date, now])


def eod_analysis(con, session_date: str, now: datetime) -> dict | None:
    """The session's end-of-day analysis written by `now` (the newest)."""
    rows = records(con, KIND_EOD_ANALYSES, f"""
        SELECT * FROM {KIND_EOD_ANALYSES} WHERE session_date = ?::DATE AND created_at <= ?::TIMESTAMPTZ
        ORDER BY created_at DESC, id DESC LIMIT 1""", [session_date, now])
    return rows[0] if rows else None


def research_review(con, now: datetime, iso_week: str | None = None) -> dict | None:
    """The newest research review written by `now` (of `iso_week` when given)."""
    week_sql, params = ("AND iso_week = ?", [now, iso_week]) if iso_week else ("", [now])
    rows = records(con, KIND_RESEARCH_REVIEWS, f"""
        SELECT * FROM {KIND_RESEARCH_REVIEWS} WHERE written_at <= ?::TIMESTAMPTZ {week_sql}
        ORDER BY written_at DESC, id DESC LIMIT 1""", params)
    return rows[0] if rows else None


def command(con, command_id: str) -> dict | None:
    """A command_log record (the newest row of that id)."""
    rows = records(con, KIND_COMMAND_LOG, f"""
        SELECT * FROM {KIND_COMMAND_LOG} WHERE id = ? ORDER BY completed_at DESC NULLS LAST LIMIT 1""",
                   [command_id])
    return rows[0] if rows else None
