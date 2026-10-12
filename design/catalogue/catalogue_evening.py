"""Evening preview rows (B2's `strategy_predictions_evening`, `lab.py predict --evening`) as EXAMPLES: the rows of
B2's write_evening_predictions (each pre-open row plus run "evening") for the rule.model_news.v1 predictions of NVDA
and RELIANCE in prediction.json, made the evening before (after the 6 Oct close). The ids are the pre-open ids they
preview. Their numbers are the pre-open example's: in stored data an evening row is computed on the day's close with
B10's evening ranges (no overnight cue, no forecaster widening) and the scores as of the evening clock, so its range,
target and probability can differ from the pre-open revision of record. The evening times are examples (the evening
run's schedule is B17's)."""
from __future__ import annotations

from marketbrief.lab.constants import RUN_EVENING

EVENING_MADE_AT = {"india": "2026-10-06T12:30:00Z", "us": "2026-10-06T22:30:00Z"}   # 18:00 IST, 18:30 New York
STRATEGY = "rule.model_news.v1"


def evening_rows(predictions: list[dict]) -> list[dict]:
    return [{**p, "made_at": EVENING_MADE_AT[p["market"]], "run": RUN_EVENING} for p in predictions
            if p["strategy_id"] == STRATEGY]
