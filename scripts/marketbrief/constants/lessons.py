"""Limits, field lists, SQL and patterns of the reflection log (lessons.py)."""
from __future__ import annotations

import re


MAX_WORDS = 60

DEFAULT_MAX = 40

FACT_FIELDS = ("id", "prediction_id", "ticker", "horizon_days", "as_of_date", "made_at", "direction",
               "confidence", "rationale", "evidence_ids", "call_prompt_version", "base_date", "base_close",
               "target_date", "target_close", "actual_return", "hit", "range_id", "range_target_date",
               "range_actual_close", "lo80", "lo50", "hi50", "hi80", "hit50", "hit80", "range_position",
               "settled_at", "available_from")

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

PCT_KINDS = ("return", "confidence_pct")       # (and "distance from ...") only with a % sign

BOTH_KINDS = ("band", "rationale")              # with or without a % sign

TIME_FIELDS = ("made_at", "settled_at", "available_from")
