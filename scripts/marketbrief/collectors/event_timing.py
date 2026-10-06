"""Dates and timing of company events: the local date of a timestamp and whether it falls before the open, during
or after the close, plus the helpers that merge report dates from several sources."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from marketbrief.constants.config_keys import CFG_CALENDAR, CFG_TIMEZONE
from marketbrief.constants.events import (
    NEAR_DAYS,
    QUARTER_GAP_DAYS,
    TIMING_AFTER_CLOSE,
    TIMING_BEFORE_OPEN,
    TIMING_DURING,
)
from marketbrief.core.calendar import exchange_calendar


def as_dates(value) -> list[date]:
    """The dates in a yfinance calendar value (one date or datetime, or a list or tuple of them)."""
    values = value if isinstance(value, (list, tuple)) else [value]
    found = []
    for item in values:
        if isinstance(item, datetime):
            found.append(item.date())
        elif isinstance(item, date):
            found.append(item)
        elif hasattr(item, "date"):
            found.append(item.date())
    return found


def timing(cfg: dict, stamp) -> tuple[date, str | None]:
    """Local date of a timestamp and whether it falls before the open, during or after the close."""
    stamp = pd.Timestamp(stamp)
    if stamp.tzinfo is None:
        return stamp.date(), None
    local = stamp.tz_convert(ZoneInfo(cfg[CFG_TIMEZONE]))
    day = local.date()
    try:
        calendar = exchange_calendar(cfg[CFG_CALENDAR])
        if not calendar.is_session(day.isoformat()):
            return day, TIMING_BEFORE_OPEN  # weekend/holiday: first reaction is the next session
        opens, closes = calendar.session_open(day.isoformat()), calendar.session_close(day.isoformat())
    except Exception:
        return day, None
    instant = stamp.tz_convert("UTC")
    if instant < opens:
        return day, TIMING_BEFORE_OPEN
    return day, TIMING_AFTER_CLOSE if instant >= closes else TIMING_DURING


def merge_near(candidates: list[tuple[date, str | None, int]]) -> list[tuple[date, str | None, int]]:
    """One row per report: best source first (SEC or NSE filings, then yfinance report, then call)."""
    kept: list[tuple[date, str | None, int]] = []
    for candidate in sorted(candidates, key=lambda entry: (entry[2], entry[0])):
        if all(abs((candidate[0] - other[0]).days) > NEAR_DAYS for other in kept):
            kept.append(candidate)
    return kept


def between_quarters(day: date, nse_dates: list[date]) -> bool:
    """Is `day` between two consecutive NSE results dates at most QUARTER_GAP_DAYS apart? Then the
    filings list that quarter and `day` adds nothing (a later gap, e.g. a quarter whose first filing
    missed the SEBI deadline, is left for other sources to fill)."""
    before = max((nse_day for nse_day in nse_dates if nse_day <= day), default=None)
    after = min((nse_day for nse_day in nse_dates if nse_day >= day), default=None)
    return before is not None and after is not None and (after - before).days <= QUARTER_GAP_DAYS
