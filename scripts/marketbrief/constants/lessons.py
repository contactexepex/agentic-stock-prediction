"""Limits, field lists, SQL and patterns of the reflection log (lessons.py)."""

from __future__ import annotations

import re


MAX_WORDS = 60

DEFAULT_MAX = 40

FACT_FIELDS = (
    "id",
    "prediction_id",
    "ticker",
    "horizon_days",
    "as_of_date",
    "made_at",
    "direction",
    "confidence",
    "rationale",
    "evidence_ids",
    "call_prompt_version",
    "base_date",
    "base_close",
    "target_date",
    "target_close",
    "actual_return",
    "hit",
    "range_id",
    "range_target_date",
    "range_actual_close",
    "lo80",
    "lo50",
    "hi50",
    "hi80",
    "hit50",
    "hit80",
    "range_position",
    "settled_at",
    "available_from",
)

AGENT_FIELDS = ("prediction_id", "lesson", "prompt_version")

SETTLED_SQL = """
WITH o AS (SELECT DISTINCT ON (prediction_id) * FROM outcomes ORDER BY prediction_id, scored_at),
     p AS (SELECT DISTINCT ON (id) * FROM predictions ORDER BY id, made_at)
SELECT p.id, p.ticker, p.horizon_days, p.as_of_date, p.made_at, p.direction, p.confidence, p.rationale,
       p.evidence_ids, p.prompt_version, o.base_date, o.base_close, o.target_date, o.target_close,
       o.actual_return, o.hit, o.scored_at
FROM p JOIN o ON o.prediction_id = p.id
"""

RANGE_SQL = """
SELECT r.id, r.as_of_date, r.made_at, r.lo80, r.lo50, r.hi50, r.hi80, ro.target_date, ro.actual_close,
       ro.hit50, ro.hit80, ro.scored_at
FROM ranges_latest r
LEFT JOIN (SELECT DISTINCT ON (range_id) * FROM range_outcomes ORDER BY range_id, scored_at) ro ON ro.range_id = r.id
WHERE r.id = ?
"""

ID_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[0-9:.+\-Z]+)?(?:-[A-Za-z0-9&.\-]+-\d+d)?\b")

NUM_RE = re.compile(r"(?<![\w.])([+\-−]?)(\d+(?:,\d{3})*(?:\.\d+)?)(\s*%)?")

PCT_KINDS = ("return", "confidence_pct")  # (and "distance from ...") only with a % sign

BOTH_KINDS = ("band", "rationale")  # with or without a % sign

TIME_FIELDS = ("made_at", "settled_at", "available_from")

# ---------- reflection log validation ----------
MSG_DOES_NOT_EXIST = "{path} does not exist"
MSG_PREDICTION_DOES_NOT_EXIST_OR_IS = (
    "prediction {prediction_id!r} does not exist or is not settled (no stored outcome)"
)
MSG_A_LESSON_FOR_IS_ALREADY_STORED = "a lesson for {prediction_id} is already stored"
MSG_DUPLICATE_LESSON_FOR_IN_THIS_FILE = "duplicate lesson for {prediction_id} in this file"
MSG_NUMBER_IN_THE_LESSON_MATCHES_NOTHING = (
    "number {sign}{num}{strip} in the lesson matches nothing in the call or its outcome"
)
MSG_MISSING_AGENT_FIELD = "missing {key}"
MSG_PREDICTION_IS_SETTLED_BUT_ITS_RANGE = (
    "prediction {prediction_id!r} is settled but its range is still open; wait for it"
)
MSG_LESSON_WORD_COUNT = "lesson must be 1-{max_words} words (got {word_count})"
MSG_RETURN_HAS_THE_WRONG_SIGN_ACTUAL = "return {sign}{num}% has the wrong sign (actual_return {actual_return:+.6f})"
MSG_MUST_BE_TEXT = "{key} must be text"
MSG_IS_BUT_THE_STORED_VALUE_IS = "{key} is {value!r} but the stored value is {value_2!r}"
