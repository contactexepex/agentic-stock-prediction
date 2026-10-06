"""Timestamp parsing and formatting shared by the scripts."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]00:?00)$")


def as_utc_timestamp(value) -> pd.Timestamp | None:
    """A value as a UTC timestamp (naive values are read as UTC), or None if it is not one."""
    if value is None or value == "":
        return None
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def format_utc_z(instant: datetime) -> str:
    """UTC instant in the SEC submissions JSON's format (2026-07-14T10:30:38.000Z)."""
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_utc_z(text: str) -> datetime:
    """A 'Z'-suffixed or offset ISO timestamp as an aware UTC datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
