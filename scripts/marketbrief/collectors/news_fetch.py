"""Request spacing of the news collector and Google News' polite stop (docs/DESIGN.md section 3, "News timing").

One NewsPacing per run: a RequestPacer for news.google.com (queries and per-day re-asks, `news.google_news.
pause_seconds`, default 1.5 s between the starts of two requests) and one for the outlet feeds
(`news.outlet_pause_seconds`, default 0.5 s), plus a PoliteStop for Google News. When Google answers HTTP 429 or
503, its /sorry/ (captcha) page, or an HTML page instead of RSS (`google_block`), the stop trips: that answer is a
failed query, it is not retried, and every later Google News job of the run is skipped (listed in
`google_skipped`, never sent). Outlet feeds are other hosts and are still read. A stopped run is recorded with
`ok` false in news_runs, so the next run's catch-up window still reaches back to the last successful run and
covers the queries this run did not ask (collectors/news_window.py)."""

from __future__ import annotations

from marketbrief.constants.news import (
    CFG_GOOGLE_PAUSE_SECONDS,
    CFG_OUTLET_PAUSE_SECONDS,
    GOOGLE_NEWS_PAUSE_SECONDS,
    GOOGLE_SORRY_MARKER,
    GOOGLE_STOP_CAPTCHA,
    GOOGLE_STOP_HTML,
    GOOGLE_STOP_HTTP,
    GOOGLE_STOP_STATUSES,
    HTML_CONTENT_MARKER,
    OUTLET_PAUSE_SECONDS,
)
from marketbrief.sources.pacing import PoliteStop, RequestPacer


def google_block(parsed, status: int) -> str | None:
    """Why Google's answer means "stop asking" (HTTP 429/503, the /sorry/ captcha page, HTML instead of RSS),
    or None for an ordinary answer or failure."""
    if status in GOOGLE_STOP_STATUSES:
        return GOOGLE_STOP_HTTP.format(status=status)
    if GOOGLE_SORRY_MARKER in str(parsed.get("href") or ""):
        return GOOGLE_STOP_CAPTCHA
    content_type = str((parsed.get("headers") or {}).get("content-type", "")).lower()
    if not parsed.get("entries") and HTML_CONTENT_MARKER in content_type:
        return GOOGLE_STOP_HTML
    return None


class NewsPacing:
    """The run's request spacing (Google News and outlet feeds) and Google News' polite stop."""

    def __init__(self, feeds: dict, clock=None, sleep=None):
        """Pacers from the market config's `news` section (clock and sleep injectable for tests)."""
        google = feeds.get("google_news") or {}
        google_pause = google.get(CFG_GOOGLE_PAUSE_SECONDS, GOOGLE_NEWS_PAUSE_SECONDS)
        outlet_pause = feeds.get(CFG_OUTLET_PAUSE_SECONDS, OUTLET_PAUSE_SECONDS)
        self.google = RequestPacer(google_pause, clock=clock, sleep=sleep)
        self.outlets = RequestPacer(outlet_pause, clock=clock, sleep=sleep)
        self.stop = PoliteStop()

    def pacer(self, is_google: bool) -> RequestPacer:
        """The pacer of a job's host."""
        return self.google if is_google else self.outlets

    def skip_if_stopped(self, job: dict) -> bool:
        """True (and the job listed as skipped) when Google News stopped this run earlier."""
        if not self.stop.stopped:
            return False
        self.stop.skip(f"{job['feed']} {job['slice']}" if job.get("slice") else job["feed"])
        return True

    def check(self, job: dict, parsed, status: int) -> bool:
        """Trip the stop when Google's answer to `job` asks us to stop; True when it did."""
        blocked = google_block(parsed, status)
        if blocked:
            self.stop.trip(f"{blocked} at {job['feed']}" + (f" {job['slice']}" if job.get("slice") else ""))
        return bool(blocked)

    def summary(self) -> dict:
        """The summary keys: why Google News stopped (None: it did not) and the jobs not asked."""
        return {"google_stopped": self.stop.reason, "google_skipped": list(self.stop.skipped)}
