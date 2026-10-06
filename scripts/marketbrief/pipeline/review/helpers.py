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


def load_review_config() -> dict:
    path = paths.CONFIG / "review.yaml"
    return {**DEFAULTS, **((yaml.safe_load(path.read_text()) or {}) if path.exists() else {})}


def week_bounds(week: str) -> tuple[date, date]:
    m = re.fullmatch(r"(\d{4})-W(\d{2})", week)
    if not m:
        raise SystemExit(f"--week must look like 2026-W40, got {week!r}")
    start = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return start, start + timedelta(days=6)


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def previous_week(d: date) -> str:
    return iso_week(d - timedelta(days=7))


def numeric_series(s: pd.Series) -> pd.Series:
    return pd.Series([np.nan if v is None or (isinstance(v, float) and math.isnan(v)) else float(v) for v in s],
                     dtype=float, index=s.index)


def rounded_mean(s: pd.Series, digits: int = 4):
    s = numeric_series(s).dropna()
    return round(float(s.mean()), digits) if len(s) else None


def notes_list(v) -> list[str]:
    return [] if v is None or (isinstance(v, float) and math.isnan(v)) else [str(x) for x in v]


def note_tags(notes) -> list[str]:
    tags = []
    for n in notes_list(notes):
        tag = next((k for k, p in NOTE_PATTERNS.items() if p.match(n)), None)
        if tag is None:
            tag = re.sub(r"[^a-z0-9_-]", "", n.split()[0].lower()) if n.split() else "other"
        if tag and tag not in tags:
            tags.append(tag)
    return tags or ["none"]


def clean(o):
    """Plain JSON types (numpy scalars -> Python, NaN -> null, dates -> ISO strings)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, np.ndarray)):
        return [clean(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer, int)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) else float(o)
    if isinstance(o, (date, pd.Timestamp)):
        return str(o)[:10]
    return o


def merge(rc: dict, overrides: dict) -> dict:
    return {**rc, **(overrides or {})}
