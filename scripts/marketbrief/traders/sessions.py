"""Sessions of a trader prediction (decision 37): D, the exit session of N+k and the trader deadline.

These follow the F1 protocol definitions of `marketbrief.contracts.protocol` (entry_session, exit_session), computed
here from the market calendar (core/calendar.py) so the traders' gate works before session B2's engine merges; the
gate also requires the published range of the horizon to name the same D and exit date (ranges_asof)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.core.calendar import next_session, session_open_utc, sessions_ahead
from marketbrief.traders.constants import DEADLINE_MINUTES


def entry_session(cfg: dict, as_of_date: date) -> date:
    """D: the first session after the as-of date (special sessions count). A prediction made before the trader
    deadline (before D's open) therefore enters at D, as protocol.entry_session(cfg, made_at) defines it."""
    return next_session(cfg, as_of_date, include=False)


def exit_session(cfg: dict, entry_date: date, horizon_days: int) -> date:
    """The close of the k-th session after D (a Friday entry with k = 1 exits on Monday)."""
    return sessions_ahead(cfg, entry_date, horizon_days + 1)[-1]


def deadline(cfg: dict, entry_date: date) -> datetime:
    """The time by which a trader must be through its gate: D's open minus DEADLINE_MINUTES (F4.2)."""
    return session_open_utc(cfg, entry_date) - timedelta(minutes=DEADLINE_MINUTES)
