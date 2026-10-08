"""Learning loop: after the close, pair each explained deviation with what happened by the close (the move since
the open held, reversed or faded), for the weekly review and the cockpit's history. Reads the view
intraday_explanation_close; as_of keeps notes written and closes collected by then (no look-ahead)."""

from __future__ import annotations

import json
from datetime import date, datetime

from marketbrief.intraday.constants import OUTCOME_FADED, OUTCOME_HELD, OUTCOME_PENDING, OUTCOME_REVERSED
from marketbrief.intraday.inputs import records
from marketbrief.intraday.measures import rounded


def classify(ret_at_check: float | None, ret_at_close: float | None, hold_fraction: float) -> str:
    """held: same sign and at least hold_fraction of the move kept; reversed: the sign flipped; else faded.
    pending: no close yet (or no move at the check)."""
    if ret_at_check is None or ret_at_close is None or ret_at_check == 0:
        return OUTCOME_PENDING
    if (ret_at_close > 0) != (ret_at_check > 0) and ret_at_close != 0:
        return OUTCOME_REVERSED
    if abs(ret_at_close) >= hold_fraction * abs(ret_at_check):
        return OUTCOME_HELD
    return OUTCOME_FADED


def closed_outside(row: dict, horizon: int = 1) -> bool | None:
    """The close outside the 80% band of horizon k (bands JSON; for k = 1 the legacy _1d columns of rows written
    before B9), or None without a close or band."""
    bands = row.get("bands") or {}
    if isinstance(bands, str):
        bands = json.loads(bands)
    band = bands.get(str(horizon)) or (
        {"lo80": row.get("lo80_1d"), "hi80": row.get("hi80_1d")} if horizon == 1 else {})
    close, low, high = row.get("session_close"), band.get("lo80"), band.get("hi80")
    if close is None or low is None or high is None:
        return None
    return close < low or close > high


def closed_outside_by_horizon(row: dict) -> dict[str, bool | None]:
    """{"<k>": closed outside the 80% band} for every horizon of the row's bands (B9: no fixed horizon)."""
    bands = row.get("bands") or {}
    if isinstance(bands, str):
        bands = json.loads(bands)
    keys = sorted({*bands, "1"} if row.get("lo80_1d") is not None else set(bands), key=int)
    return {k: closed_outside(row, int(k)) for k in keys}


def explanation_outcomes(con, settings: dict, start: date | None = None, end: date | None = None,
                         as_of: datetime | None = None) -> list[dict]:
    """One row per explained deviation in [start, end] (session dates) with its outcome by the close."""
    frame = con.execute(
        "SELECT * FROM intraday_explanation_close WHERE (? IS NULL OR session_date >= ?) "
        "AND (? IS NULL OR session_date <= ?) AND (? IS NULL OR explained_at <= ?) "
        "ORDER BY session_date, check_at, ticker",
        [start, start, end, end, as_of, as_of],
    ).df()
    hold = settings["outcome"]["hold_fraction"]
    out = []
    for row in records(frame):
        if as_of is not None and row.get("close_collected_at") is not None and row["close_collected_at"] > as_of:
            row.update(session_close=None, close_ret_since_open=None, ret_after_check=None)
        out.append({
            "check_row_id": row["check_row_id"], "explanation_id": row["explanation_id"], "ticker": row["ticker"],
            "session_date": str(row["session_date"])[:10], "check_at": row["check_at"].isoformat(),
            "flags": as_list(row["flags"]), "attribution": row["attribution"], "explanation": row["explanation"],
            "cited_ids": as_list(row["cited_ids"]), "ret_since_open": rounded(row["ret_since_open"]),
            "session_close": rounded(row["session_close"], 4),
            "close_ret_since_open": rounded(row["close_ret_since_open"]),
            "ret_after_check": rounded(row["ret_after_check"]),
            "outcome": classify(row["ret_since_open"], row["close_ret_since_open"], hold),
            "closed_outside_1d_80": closed_outside(row),
            "closed_outside_80": closed_outside_by_horizon(row),
        })
    return out


def outcome_summary(rows: list[dict]) -> dict:
    """Counts per outcome, overall and per attribution (the weekly review's table)."""
    overall: dict[str, int] = {}
    by_attribution: dict[str, dict[str, int]] = {}
    for row in rows:
        overall[row["outcome"]] = overall.get(row["outcome"], 0) + 1
        bucket = by_attribution.setdefault(row["attribution"], {})
        bucket[row["outcome"]] = bucket.get(row["outcome"], 0) + 1
    return {"n": len(rows), "outcomes": dict(sorted(overall.items())),
            "by_attribution": {key: dict(sorted(value.items())) for key, value in sorted(by_attribution.items())}}


def as_list(value) -> list:
    """A stored list column (array or None) as a list."""
    return [] if value is None else list(value)


def notes_in_window(con, settings: dict, ticker: str, after: date, through: date) -> list[dict]:
    """The reflector's optional input (lessons.py prepare): the stored intraday notes of a ticker for the sessions
    after `after` (a call's as-of or base date) up to `through` (its target date), each with its outcome by the
    close. Read only for settled calls, so every note and close is in the past; nothing here is stored."""
    rows = [row for row in explanation_outcomes(con, settings, after, through) if row["ticker"] == ticker
            and row["session_date"] > after.isoformat()]
    keys = ("explanation_id", "session_date", "check_at", "flags", "attribution", "explanation", "outcome")
    return [{key: row[key] for key in keys} for row in rows]
