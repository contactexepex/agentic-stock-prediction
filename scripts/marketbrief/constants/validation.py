"""Stages, kind groups and enumerations of the daily gate (validate.py)."""

from __future__ import annotations


STAGES = ("collect", "news", "features", "context", "forecast", "report")

# kinds whose day files are named by the trading date, with the column that says when a row was written
TRADING_DATE_KINDS = {
    "prices": "collected_at",
    "features": "computed_at",
    "regime": "computed_at",
    "calibration": "computed_at",
    "ranges": "made_at",
    "replays": "computed_at",
    "adjustments": "detected_at",
}

STAGE_KINDS = {"features": ("features", "regime", "calibration")}

FETCH_COL = {
    "quotes": "collected_at",
    "news": "first_seen_at",
    "filings": "first_seen_at",
    "announcements": "first_seen_at",
}

ENRICH_ENUMS = {
    "materiality": {"low", "medium", "high"},
    "urgency": {"low", "medium", "high"},
    "event_type": {"earnings", "macro", "product", "legal", "sector", "analyst", "ma", "flows", "other"},
}
