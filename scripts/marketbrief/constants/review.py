"""Defaults, targets and note patterns of the weekly review (review.py)."""

from __future__ import annotations

import re

DEFAULTS = {
    "rolling_days": 30,
    "min_n": 30,
    "min_n_recommend": 200,
    "min_n_calls": 50,
    "min_improvement": 0.02,
    "coverage_tolerance": 0.02,
    "min_coverage_gain": 0.04,
    "calibration_tolerance": 0.05,
    "confidence_bands": [0.5, 0.6, 0.7, 0.8, 0.9],
    "history_eval_sessions": 120,
    "live_variants": [],
    "history_variants": [],
}

TARGETS = {"50": 0.5, "80": 0.8}

BASELINE = "current config"

# Notes written by ranges.py -> (tag, pattern). Unknown notes are tagged by their first word.
NOTE_PATTERNS = {
    "earnings": re.compile(r"^earnings in horizon \(x([\d.]+) day\)"),
    "regime": re.compile(r"^regime (\w+) x([\d.]+)"),
    "event": re.compile(r"^major event x([\d.]+)"),
    "ai_widen": re.compile(r"^AI widened \+([\d.]+)%"),
    "cue": re.compile(r"^cue ([+-]?[\d.]+)% x([\d.]+)"),
}

ACI_SETTING_KEYS = ("gamma", "max_shift", "min_history", "by_regime")

# ---------- review helpers ----------
MSG_WEEK_MUST_LOOK_LIKE_2026_W40 = "--week must look like 2026-W40, got {week!r}"
