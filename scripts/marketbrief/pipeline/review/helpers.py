"""Review configuration, ISO weeks and small numeric and note helpers."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
import numpy as np
import pandas as pd
import yaml
from marketbrief.core import paths
from marketbrief.constants.review import DEFAULTS, NOTE_PATTERNS
from marketbrief.constants.review import MSG_WEEK_MUST_LOOK_LIKE_2026_W40


def load_review_config() -> dict:
    """The review thresholds from config/review.yaml over the defaults."""
    path = paths.CONFIG / "review.yaml"
    return {**DEFAULTS, **((yaml.safe_load(path.read_text()) or {}) if path.exists() else {})}


def week_bounds(week: str) -> tuple[date, date]:
    """First and last day of an ISO week such as 2026-W40."""
    match = re.fullmatch(r"(\d{4})-W(\d{2})", week)
    if not match:
        raise SystemExit(MSG_WEEK_MUST_LOOK_LIKE_2026_W40.format(week=week))
    start = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    return start, start + timedelta(days=6)


def iso_week(day: date) -> str:
    """The ISO week name (2026-W40) of a day."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def previous_week(day: date) -> str:
    """The ISO week before the one of a day."""
    return iso_week(day - timedelta(days=7))


def numeric_series(values: pd.Series) -> pd.Series:
    """A series coerced to float with NaN for what is not a number."""
    return pd.Series(
        [
            np.nan if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)
            for value in values
        ],
        dtype=float,
        index=values.index,
    )


def rounded_mean(values: pd.Series, digits: int = 4):
    """The mean of the numeric values, rounded; None when empty."""
    values = numeric_series(values).dropna()
    return round(float(values.mean()), digits) if len(values) else None


def notes_list(notes) -> list[str]:
    """A notes cell as a list of text."""
    return [] if notes is None or (isinstance(notes, float) and math.isnan(notes)) else [str(note) for note in notes]


def note_tags(notes) -> list[str]:
    """The widening tags of a range's notes (cue, ai_widen, earnings, event, regime ...)."""
    tags = []
    for note in notes_list(notes):
        tag = next((key for key, pattern in NOTE_PATTERNS.items() if pattern.match(note)), None)
        if tag is None:
            tag = re.sub(r"[^a-z0-9_-]", "", note.split()[0].lower()) if note.split() else "other"
        if tag and tag not in tags:
            tags.append(tag)
    return tags or ["none"]


def clean(obj):
    """Plain JSON types (numpy scalars -> Python, NaN -> null, dates -> ISO strings)."""
    if isinstance(obj, dict):
        return {str(key): clean(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [clean(value) for value in obj]
    if isinstance(obj, (np.bool_, bool)):
        obj = bool(obj)
    elif isinstance(obj, (np.integer, int)):
        obj = int(obj)
    elif isinstance(obj, (np.floating, float)):
        obj = None if math.isnan(obj) else float(obj)
    elif isinstance(obj, (date, pd.Timestamp)):
        obj = str(obj)[:10]
    return obj


def merge(ranges_config: dict, overrides: dict) -> dict:
    """The ranges config with a variant's overrides applied."""
    return {**ranges_config, **(overrides or {})}
