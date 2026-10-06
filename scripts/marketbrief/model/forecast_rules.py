"""The forecaster's anchor on the signal model (forecast-v11), checked by validate.py --stage forecast.

When a model score exists for the call's id (the newest model_scores row computed by made_at):
- model_prob must equal that score's prob_up;
- agent_adjustment is required, |agent_adjustment| <= 0.10, and adjustment_reason (text) is required
  whenever it is not 0;
- the final probability of up is model_prob + agent_adjustment: the direction must be the side of 0.5
  it is on (exactly 0.5: abstain), and confidence must be max(final, 1 - final) to within 0.005
  (the existing rules still cap confidence at 0.50-0.90).
With no score for the id (e.g. the model step failed) model_prob must be absent: the call is checked by
the other rules only and the gate warns MODEL_SCORE_MISSING."""
from __future__ import annotations

from marketbrief.constants.model import (CODE_MODEL_ADJUSTMENT, CODE_MODEL_SCORE_MISSING, CONFIDENCE_TOLERANCE,
                                         MAX_AGENT_ADJUSTMENT, MODEL_PROB_TOLERANCE, MSG_ADJUSTMENT_MISSING,
                                         MSG_ADJUSTMENT_TOO_LARGE, MSG_ANCHOR_MISMATCH, MSG_ANCHOR_MISSING,
                                         MSG_ANCHOR_UNEXPECTED, MSG_CONFIDENCE_IMPLIED, MSG_DIRECTION_SIDE,
                                         MSG_FINAL_HALF, MSG_LINE_PREFIX, MSG_REASON_MISSING,
                                         MSG_SCORE_MISSING_WARNING)
from marketbrief.utils.timefmt import as_utc_timestamp

SCORE_SQL = """
SELECT DISTINCT ON (id) id, prob_up FROM model_scores
WHERE id = ? AND computed_at <= ?::TIMESTAMPTZ ORDER BY id, computed_at DESC"""
EPSILON = 1e-9


def is_number(value) -> bool:
    """A real number (not a bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def anchor_errors(rec: dict, stored_prob: float | None) -> list[str]:
    """Reasons a record breaks the model-anchor rules (empty = ok)."""
    model_prob = rec.get("model_prob")
    if stored_prob is None:
        return [] if model_prob is None else [MSG_ANCHOR_UNEXPECTED]
    adjustment = rec.get("agent_adjustment")
    if not is_number(model_prob):
        return [MSG_ANCHOR_MISSING.format(stored=stored_prob)]
    errors = []
    if abs(model_prob - stored_prob) > MODEL_PROB_TOLERANCE:
        errors.append(MSG_ANCHOR_MISMATCH.format(given=model_prob, stored=stored_prob))
    if not is_number(adjustment):
        return [*errors, MSG_ADJUSTMENT_MISSING]
    if abs(adjustment) > MAX_AGENT_ADJUSTMENT + EPSILON:
        errors.append(MSG_ADJUSTMENT_TOO_LARGE.format(size=abs(adjustment), cap=MAX_AGENT_ADJUSTMENT))
    reason = rec.get("adjustment_reason")
    if abs(adjustment) > EPSILON and not (isinstance(reason, str) and reason.strip()):
        errors.append(MSG_REASON_MISSING)
    final = stored_prob + adjustment
    if abs(final - 0.5) < EPSILON:
        return [*errors, MSG_FINAL_HALF]
    side = "up" if final > 0.5 else "down"
    if rec.get("direction") != side:
        errors.append(MSG_DIRECTION_SIDE.format(direction=rec.get("direction"), final=final))
    implied = max(final, 1 - final)
    if is_number(rec.get("confidence")) and abs(rec["confidence"] - implied) > CONFIDENCE_TOLERANCE + EPSILON:
        errors.append(MSG_CONFIDENCE_IMPLIED.format(confidence=rec["confidence"], implied=implied))
    return errors


def stored_score(con, rec: dict) -> float | None:
    """The newest model score's prob_up for the record's id computed by its made_at, or None."""
    made = as_utc_timestamp(rec.get("made_at"))
    if made is None:
        return None
    row = con.execute(SCORE_SQL, [rec["id"], made.isoformat()]).fetchone()
    return None if row is None else float(row[1])


def model_rules_pass(res, con, rec: dict, line: int) -> bool:
    """Apply the anchor rules to a record that passed the others; failures and warnings go to `res`."""
    stored = stored_score(con, rec)
    if stored is None and rec.get("model_prob") is None:
        res.warn(CODE_MODEL_SCORE_MISSING, MSG_SCORE_MISSING_WARNING.format(line=line, id=rec["id"]), [rec["ticker"]])
        return True
    errors = anchor_errors(rec, stored)
    if errors:
        res.block(CODE_MODEL_ADJUSTMENT, MSG_LINE_PREFIX.format(line=line, id=rec["id"]) + "; ".join(errors),
                  [rec["ticker"]])
    return not errors
