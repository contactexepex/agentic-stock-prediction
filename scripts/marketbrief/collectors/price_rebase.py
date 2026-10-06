"""Price-step tests and the claim of a suspected re-base, shared by split detection and the NSE basis check."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from marketbrief.constants.prices import STEP_RATIO_HIGH, STEP_RATIO_LOW


def step_matches(step: float, factor: float) -> bool:
    """True when a price step (close / previous close) looks like the split factor: within
    0.8-1.25x of it and nearer to it than to no step at all (log distance)."""
    if step <= 0:
        return False
    return STEP_RATIO_LOW <= step / factor <= STEP_RATIO_HIGH and abs(math.log(step / factor)) < abs(math.log(step))


@dataclass(frozen=True)
class RebaseClaim:
    """A suspected re-base of one stock's stored closes: `last` is the newest re-based stored bar (stored close
    `stored_last`), `known_factor` the recorded adjustments after it, `factor` the suspected ratio, `later` the
    frame sessions after `last` and `yahoo_closes` Yahoo's closes."""

    key: str
    last: date
    stored_last: float
    known_factor: float
    factor: float
    later: list[date]
    yahoo_closes: dict[date, float]
