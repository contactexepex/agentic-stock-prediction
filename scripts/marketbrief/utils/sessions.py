"""Lists of a market's trading sessions. The two helpers answer different questions, so they stay separate."""
from __future__ import annotations

from datetime import date, timedelta


def last_completed_sessions(cfg: dict, today: date, count: int) -> list[date]:
    """The last `count` completed sessions before UTC `today`, oldest first."""
    import events as ev
    sessions, day = [], today
    for _ in range(count):
        day = ev.prev_session(cfg, day, include=False)
        sessions.append(day)
    return sessions[::-1]


def sessions_in_window(cfg: dict, today: date, lookback_days: int) -> list[date]:
    """The market's sessions in the last `lookback_days` calendar days up to today, oldest first."""
    import events as ev
    days = [today - timedelta(days=n) for n in range(lookback_days, -1, -1)]
    return [d for d in days if ev.is_session(cfg, d)]
