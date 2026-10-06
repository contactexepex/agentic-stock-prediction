"""Date helpers over the calendar of major market events."""

from __future__ import annotations

import bisect
from datetime import date


def major_event_between(majors: list[date], start: date, end: date) -> bool:
    """A major market event after the as-of date `start` and on or before the target `end` (as ranges.py).
    `majors` is the sorted list of major event dates."""
    first_after_start = bisect.bisect_right(majors, start)
    return first_after_start < len(majors) and majors[first_after_start] <= end
