"""As-of dates, the model's training cutoff (leakage label) and the pre-open data cutoff."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from marketbrief.core import calendar, paths
from marketbrief.core.settings import load_settings
from marketbrief.constants.ai_replay import CONTAMINATED, CUTOFF_LOCAL, FAIR, REGULAR_LEAD, SAMPLE_END, SAMPLE_START, SAMPLE_STEP


def training_cutoff() -> date:
    """`model_training_cutoff` from config/settings.yaml: the model may have seen data up to this date."""
    v = (load_settings() or {}).get("model_training_cutoff")
    if v is None:
        raise SystemExit(f"{paths.CONFIG / 'settings.yaml'} has no model_training_cutoff (YYYY-MM-DD)")
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def leakage_label(d, cutoff: date | None = None) -> str:
    """"fair" for an as-of date after the training cutoff, else "contaminated" (never pooled)."""
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    return FAIR if d > (cutoff or training_cutoff()) else CONTAMINATED


def next_session(cfg: dict, d: date) -> date:
    return calendar.next_session(cfg, d, include=False)


def cutoff_for(cfg: dict, d: date) -> datetime:
    """Pre-open time of the session after d (UTC): the routine's start on that session."""
    s = next_session(cfg, d)
    opens = calendar.session_open_utc(cfg, s)
    local = CUTOFF_LOCAL.get(cfg["market"])
    at = (datetime.combine(s, local, ZoneInfo(cfg["timezone"])).astimezone(timezone.utc) if local
          else opens - REGULAR_LEAD)
    return min(at, opens - timedelta(minutes=1)).replace(microsecond=0)


def sample_dates(cfg: dict, start: date = SAMPLE_START, end: date = SAMPLE_END, step: int = SAMPLE_STEP) -> list[date]:
    """Every `step`-th exchange trading day from start to end (inclusive), starting with the first."""
    days, d = [], start
    while d <= end:
        if calendar.is_session(cfg, d):
            days.append(d)
        d += timedelta(days=1)
    return days[::step]
