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
    # the signal-model check (pipeline/review/model_skill.py): skill = n >= min_n out-of-sample rows, Brier skill
    # vs the base rate above min_brier_skill and the AUC's 95% interval above min_auc_low
    "model_skill": {"min_n": 500, "min_brier_skill": 0.0, "min_auc_low": 0.5},
}

# ---------- signal-model check of the weekly review (model_skill.py) ----------
MODEL_BACKTEST_DIR = "work/model_backtest"
MSG_MODEL_SKILL = "Yes: the signal model has shown skill out of sample on {keys}."
MSG_MODEL_NO_SKILL = ("No: the signal model has not shown skill. No horizon has at least {n} out-of-sample rows with a "
                      "Brier skill above {margin} against the base rate and an AUC 95% interval above {auc}.")
MSG_STRATEGY_BEATS = "Its paper long beats a baseline after costs on: {which}."
MSG_STRATEGY_NONE = "Its paper long beats no baseline after costs (95% interval above 0)."
MSG_MODEL_CHECK_SKIPPED = "skipped (--no-model-backtest)"
MSG_MODEL_CHECK_FAILED = "the backtest failed: {error}"

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
EARNINGS_TAG = "earnings"   # note tag; breakdown rows "earnings · <k>d" = N+k ranges with earnings in the horizon

# ---------- review helpers ----------
MSG_WEEK_MUST_LOOK_LIKE_2026_W40 = "--week must look like 2026-W40, got {week!r}"
MSG_HISTORY_ABLATION_SKIPPED = "skipped (--no-history)"
MSG_NOT_ENOUGH_BENCHMARK_BARS = "not enough benchmark bars"
SKIP_HISTORY = "history"  # review.build: no walk-forward on stored prices (--no-history)
SKIP_MODEL = "model"  # review.build: no signal-model backtest (--no-model-backtest)
