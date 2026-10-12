"""Request spacing and a polite stop for free sources without an API agreement (Google News RSS, Yahoo).

RequestPacer keeps at least `min_interval` seconds between the starts of two requests (the wait is measured
on a monotonic clock, so a slow answer counts toward it). PoliteStop is a run-long circuit breaker: once a
source says it is rate limiting (HTTP 429/503, a captcha page, yfinance's YFRateLimitError), `trip` records
why and every later request of that source in the run is skipped and listed instead of sent. Nothing is ever
retried in a loop. Clock and sleep are injectable; the default sleep is looked up at call time (`pause`), so
the offline test suite can replace it once for every pacer."""

from __future__ import annotations

import time
from typing import Callable


def pause(seconds: float) -> None:
    """Sleep `seconds` (the default sleep of every pacer; tests replace this one function)."""
    time.sleep(seconds)


class RequestPacer:
    """At least `min_interval` seconds between the starts of two requests."""

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        """A pacer with its interval; clock and sleep default to time.monotonic and `pause`."""
        self.min_interval = max(float(min_interval or 0), 0.0)
        self._clock, self._sleep = clock or time.monotonic, sleep
        self._last_start: float | None = None
        self.requests = 0
        self.waited = 0.0

    def wait(self) -> float:
        """Sleep until `min_interval` has passed since the last request started, then mark this one's start;
        returns the seconds slept."""
        slept = 0.0
        if self._last_start is not None and self.min_interval:
            slept = self._last_start + self.min_interval - self._clock()
            if slept > 0:
                (self._sleep or pause)(slept)
            else:
                slept = 0.0
        self._last_start = self._clock()
        self.requests += 1
        self.waited += slept
        return slept


class PoliteStop:
    """A run-long stop for one source: after `trip`, later requests are skipped and listed (never sent)."""

    def __init__(self):
        """An open stop (requests allowed)."""
        self.reason: str | None = None
        self.skipped: list[str] = []

    @property
    def stopped(self) -> bool:
        """True once the source has asked us to stop."""
        return self.reason is not None

    def trip(self, reason: str) -> None:
        """Stop the source for the rest of the run (the first reason is kept)."""
        if self.reason is None:
            self.reason = reason

    def skip(self, item: str) -> None:
        """Record a request not sent because of the stop (each item once, in order)."""
        if item not in self.skipped:
            self.skipped.append(item)
