"""Deterministic facts of settled calls for the reflection log: outcome, range position, evidence."""

from __future__ import annotations

import math
import pandas as pd
from marketbrief.pipeline.score_predictions import is_late
from marketbrief.constants.lessons import RANGE_SQL, SETTLED_SQL


def iso_utc_text(value) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    timestamp = pd.Timestamp(value)
    return (timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")).isoformat()


def date_text(value) -> str | None:
    return None if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value)[:10]


def float_or_none(value):
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def position(close: float, lo80: float, lo50: float, hi50: float, hi80: float) -> str:
    """Where the close landed against the published bands."""
    if close < lo80:
        return "below_80"
    if close < lo50:
        return "in_80_below_50"
    if close <= hi50:
        return "in_50"
    if close <= hi80:
        return "in_80_above_50"
    return "above_80"


def settled(cfg: dict, con) -> dict[str, dict]:
    """prediction_id -> deterministic lesson facts, for every call with a stored outcome. A call whose
    range is open (published, not late, not scored) maps to None: it waits for the range."""
    out = {}
    for row in con.execute(SETTLED_SQL).df().itertuples(index=False):
        rec = {
            "id": f"lesson-{row.id}",
            "prediction_id": row.id,
            "ticker": row.ticker,
            "horizon_days": int(row.horizon_days),
            "as_of_date": date_text(row.as_of_date),
            "made_at": iso_utc_text(row.made_at),
            "direction": row.direction,
            "confidence": float_or_none(row.confidence),
            "rationale": row.rationale,
            "evidence_ids": [
                str(evidence_id) for evidence_id in (row.evidence_ids if row.evidence_ids is not None else [])
            ],
            "call_prompt_version": row.prompt_version,
            "base_date": date_text(row.base_date),
            "base_close": float_or_none(row.base_close),
            "target_date": date_text(row.target_date),
            "target_close": float_or_none(row.target_close),
            "actual_return": float_or_none(row.actual_return),
            "hit": bool(row.hit),
            "range_id": None,
            "range_target_date": None,
            "range_actual_close": None,
            "lo80": None,
            "lo50": None,
            "hi50": None,
            "hi80": None,
            "hit50": None,
            "hit80": None,
            "range_position": None,
            "settled_at": iso_utc_text(row.scored_at),
            "available_from": iso_utc_text(row.scored_at),
        }
        range_frame = con.execute(RANGE_SQL, [row.id]).df()
        if len(range_frame):
            range_row = range_frame.iloc[0]
            if range_row["scored_at"] is None or pd.isna(range_row["scored_at"]):
                if not is_late(cfg, range_row["as_of_date"], range_row["made_at"]):
                    out[row.id] = None  # its range is still open: wait so the lesson can cite it
                    continue
            else:
                close = float(range_row["actual_close"])
                rec.update(
                    {
                        "range_id": range_row["id"],
                        "range_target_date": date_text(range_row["target_date"]),
                        "range_actual_close": close,
                        "lo80": float(range_row["lo80"]),
                        "lo50": float(range_row["lo50"]),
                        "hi50": float(range_row["hi50"]),
                        "hi80": float(range_row["hi80"]),
                        "hit50": bool(range_row["hit50"]),
                        "hit80": bool(range_row["hit80"]),
                        "range_position": position(
                            close, range_row["lo80"], range_row["lo50"], range_row["hi50"], range_row["hi80"]
                        ),
                        "available_from": max(
                            pd.Timestamp(rec["settled_at"]), pd.Timestamp(iso_utc_text(range_row["scored_at"]))
                        ).isoformat(),
                    }
                )
        out[row.id] = rec
    return out


def stored_ids(con) -> set[str]:
    return set(con.execute("SELECT DISTINCT id FROM lessons").df()["id"])


def evidence(con, ids: list[str]) -> list[dict]:
    """What each cited id said (title/description), for the reflector to read; not stored."""
    if not ids:
        return []
    rows = con.execute(
        """
        SELECT * FROM (SELECT id, 'news' AS kind, title AS text, published_at AS at FROM news WHERE list_contains(?, id)
        UNION ALL SELECT id, 'filing', form || ': ' || coalesce(description, ''), accepted_at FROM filings
            WHERE list_contains(?, id)
        UNION ALL SELECT id, 'announcement', coalesce(category, '') || ': ' || coalesce(subject, ''), published_at
            FROM announcements WHERE list_contains(?, id)
        ) ORDER BY id, kind = 'announcement', kind = 'filing', "at", text""",
        [ids, ids, ids],
    ).df()
    first: dict[str, dict] = {}  # per id the news row, else the filing, else the announcement (ORDER BY)
    for row in rows.itertuples(index=False):
        first.setdefault(row.id, {"id": row.id, "kind": row.kind, "text": row.text, "at": iso_utc_text(row.at)})
    return [
        first.get(cited_id, {"id": cited_id, "kind": "unknown", "text": None, "at": None})
        for cited_id in dict.fromkeys(ids)
    ]
