"""The news collector's catch-up window (docs/DESIGN.md section 3, "News timing").

The window of a run is the time since the last SUCCESSFUL news collection of the market plus
WINDOW_MARGIN_HOURS, capped at WINDOW_CAP_HOURS (7 days), and never narrower than the fixed values used
before (Google News `when:` = the config's `news.google_news.window`, default 1d; item age MAX_AGE_DAYS):
- the last success is the newest `ran_at` of a data/<market>/news_runs/ row with `ok` true (a run is ok
  when at most RUN_OK_MAX_FAILED_SHARE of its Google News queries failed and not every feed failed);
- when news_runs rows exist but none of the newest SEEN_LOOKBACK_DAYS files is ok, the window is the cap;
- before the first news_runs row exists, the newest stored news `first_seen_at` stands in;
- with neither (a first run), the defaults apply unchanged.
So Monday's run reaches back to the last run on Friday (or Saturday's light run), the day after a holiday
reaches back over it, and a failed run's span is covered by the next successful one.
Google News accepts `when:<n>h` and `when:<n>d` (checked live 2026-10-07: 1h-170h and 1d-8d answered;
`when:1w` and `when:1m` returned nothing), so a span above the floor is asked as whole hours, rounded up.
Google News answers at most GOOGLE_NEWS_ITEM_CAP items per query, so a query that fills the cap over a
window longer than a day is asked again per day (`after:YYYY-MM-DD before:YYYY-MM-DD`, Google's days end
at midnight Pacific time; the slices start a day before the window and items older than it are dropped)."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.constants.kinds import KIND_NEWS, KIND_NEWS_RUNS
from marketbrief.constants.news import (
    DEFAULT_WINDOW,
    HOURS_PER_DAY,
    MAX_AGE_DAYS,
    MSG_BAD_WINDOW,
    RUN_OK_MAX_FAILED_SHARE,
    SEEN_LOOKBACK_DAYS,
    WINDOW_CAP_HOURS,
    WINDOW_MARGIN_HOURS,
    WINDOW_REASON_FIRST_RUN,
    WINDOW_REASON_NO_RECENT_SUCCESS,
    WINDOW_REASON_SINCE_NEWS,
    WINDOW_REASON_SINCE_RUN,
)
from marketbrief.core import paths
from marketbrief.core.clock import utc_today

WHEN_PATTERN = re.compile(r"^(\d+)([hd])$")


@dataclass(frozen=True)
class NewsWindow:
    """One run's window: the Google News `when:` value, the oldest item age kept, and why."""

    since: datetime | None  # the last successful collection (None on a first run)
    hours: float  # the span asked from Google News, in hours
    google_when: str  # the `when:` value, e.g. "1d" or "61h"
    max_age: timedelta  # items published longer ago are skipped
    reason: str

    def summary(self) -> dict:
        """The window as written to the run's summary and news_runs row."""
        return {
            "since": self.since.isoformat() if self.since else None,
            "window_hours": round(self.hours, 2),
            "google_when": self.google_when,
            "max_age_hours": round(self.max_age.total_seconds() / 3600, 2),
            "reason": self.reason,
        }


def when_hours(value: str) -> float:
    """Hours of a Google News `when:` value such as "1d" or "12h"."""
    match = WHEN_PATTERN.match(str(value).strip())
    if not match:
        raise ValueError(MSG_BAD_WINDOW.format(value=value))
    count, unit = int(match.group(1)), match.group(2)
    return float(count * (HOURS_PER_DAY if unit == "d" else 1))


def catch_up_window(
    since: datetime | None, now: datetime, floor_when: str = DEFAULT_WINDOW, reason: str = ""
) -> NewsWindow:
    """The window of a run at `now` whose last successful collection was at `since` (see the module docstring)."""
    floor_hours = when_hours(floor_when)
    floor_age = timedelta(days=MAX_AGE_DAYS)
    if since is None:
        return NewsWindow(None, floor_hours, floor_when, floor_age, WINDOW_REASON_FIRST_RUN)
    span = (now - since).total_seconds() / 3600 + WINDOW_MARGIN_HOURS
    span = min(max(span, 0.0), float(WINDOW_CAP_HOURS))
    if span <= floor_hours:
        hours, google_when = floor_hours, floor_when
    else:
        hours = float(math.ceil(span))
        google_when = f"{int(hours)}h"
    max_age = max(floor_age, timedelta(hours=hours))
    return NewsWindow(since, hours, google_when, max_age, reason or WINDOW_REASON_SINCE_RUN)


def run_ok(google_queries: int, google_failed: int, feeds: int, failed: int) -> bool:
    """A successful run: not every feed failed, and at most RUN_OK_MAX_FAILED_SHARE of the Google News queries."""
    if feeds and failed >= feeds:
        return False
    return not google_queries or google_failed / google_queries <= RUN_OK_MAX_FAILED_SHARE


def parse_utc(value) -> datetime | None:
    """An ISO 8601 string as an aware UTC datetime (None when missing or unreadable)."""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def recent_rows(market: str, kind: str, files: int = SEEN_LOOKBACK_DAYS):
    """Rows of the newest `files` day files of a kind (newest file last), leaving out files dated after the run's
    clock (MB_NOW in a test or replay: a later day's file is not known yet)."""
    today = utc_today().isoformat()
    stored = [path for path in sorted((paths.data_dir(market) / kind).glob(JSONL_GLOB)) if path.stem <= today]
    for path in stored[-files:]:
        for line in path.read_text(encoding=ENCODING_UTF8).splitlines():
            if line.strip():
                yield json.loads(line)


def last_success(market: str, now: datetime) -> tuple[datetime | None, str]:
    """(the last successful news collection before `now`, the reason code) from the stored rows."""
    stored = [(parse_utc(row.get("ran_at")), bool(row.get("ok"))) for row in recent_rows(market, KIND_NEWS_RUNS)]
    stored = [(stamp, ok) for stamp, ok in stored if stamp and stamp <= now]
    successes = [stamp for stamp, ok in stored if ok]
    if successes:
        return max(successes), WINDOW_REASON_SINCE_RUN
    if stored:  # runs stored, none successful in the files read: reach back the whole cap
        return now - timedelta(hours=WINDOW_CAP_HOURS), WINDOW_REASON_NO_RECENT_SUCCESS
    seen = [parse_utc(row.get("first_seen_at")) for row in recent_rows(market, KIND_NEWS, files=1)]
    seen = [stamp for stamp in seen if stamp and stamp <= now]
    if seen:
        return max(seen), WINDOW_REASON_SINCE_NEWS
    return None, WINDOW_REASON_FIRST_RUN


def window_for(market: str, now: datetime, floor_when: str = DEFAULT_WINDOW) -> NewsWindow:
    """This run's window from the market's stored runs (see the module docstring)."""
    since, reason = last_success(market, now)
    return catch_up_window(since, now, floor_when, reason)


def slice_days(window: NewsWindow, now: datetime) -> list[date]:
    """The days asked one by one when a query fills Google News' item cap: from the day before the window's
    start (Google's days are Pacific time) through today (UTC); none for a window of a day or less."""
    if window.hours <= HOURS_PER_DAY:
        return []
    first = (now - timedelta(hours=window.hours)).date() - timedelta(days=1)
    return [first + timedelta(days=offset) for offset in range((now.date() - first).days + 1)]
