"""As-of dates, the model's training cutoff (leakage label) and the pre-open data cutoff."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from marketbrief.core import calendar, paths
from marketbrief.core.settings import load_settings
from marketbrief.constants.ai_replay import (
    CONTAMINATED,
    CUTOFF_LOCAL,
    FAIR,
    REGULAR_LEAD,
    SAMPLE_END,
    SAMPLE_START,
    SAMPLE_STEP,
)
from marketbrief.constants.ai_replay import MSG_HAS_NO_MODEL_TRAINING_CUTOFF_YYYY


def training_cutoff() -> date:
    """`model_training_cutoff` from config/settings.yaml: the model may have seen data up to this date."""
    value = (load_settings() or {}).get("model_training_cutoff")
    if value is None:
        raise SystemExit(MSG_HAS_NO_MODEL_TRAINING_CUTOFF_YYYY.format(value=paths.CONFIG / "settings.yaml"))
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def leakage_label(as_of_day, cutoff: date | None = None) -> str:
    """ "fair" for an as-of date after the training cutoff, else "contaminated" (never pooled)."""
    as_of_day = as_of_day if isinstance(as_of_day, date) else date.fromisoformat(str(as_of_day)[:10])
    return FAIR if as_of_day > (cutoff or training_cutoff()) else CONTAMINATED


def next_session(cfg: dict, as_of_day: date) -> date:
    return calendar.next_session(cfg, as_of_day, include=False)


def cutoff_for(cfg: dict, as_of_day: date) -> datetime:
    """Pre-open time of the session after d (UTC): the routine's start on that session."""
    session = next_session(cfg, as_of_day)
    opens = calendar.session_open_utc(cfg, session)
    local = CUTOFF_LOCAL.get(cfg["market"])
    cutoff_time = (
        datetime.combine(session, local, ZoneInfo(cfg["timezone"])).astimezone(timezone.utc)
        if local
        else opens - REGULAR_LEAD
    )
    return min(cutoff_time, opens - timedelta(minutes=1)).replace(microsecond=0)


def sample_dates(cfg: dict, start: date = SAMPLE_START, end: date = SAMPLE_END, step: int = SAMPLE_STEP) -> list[date]:
    """Every `step`-th exchange trading day from start to end (inclusive), starting with the first."""
    days, day = [], start
    while day <= end:
        if calendar.is_session(cfg, day):
            days.append(day)
        day += timedelta(days=1)
    return days[::step]
