"""The market config and the clock of one prices run, shared by the prices collector's modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceRun:
    """cfg: the market config; today: the UTC date of the run; now: its ISO timestamp; own_through: the newest
    session whose bar is final (calendar.last_complete_session): the market's own stocks and indices are stored
    up to it, cues and factors (other calendars) up to the day before `today` (issue #20)."""

    cfg: dict
    today: date
    now: str
    own_through: date | None = None
