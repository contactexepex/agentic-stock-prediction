"""Which watchlist companies released quarterly results or filed an earnings-call text (deterministic).

India: a results release is the first NSE Integrated Filing of a quarter (financials, min filed_at over both
bases), so a revised filing of an old quarter is no new release; an earnings-call text is an NSE announcement in
`india_concall_categories` whose subject names a transcript. US: a results release is an SEC item 2.02 date that
event_history.earnings_events keeps as a quarter's results release (results_filter, with the 10-Q/10-K reports
accepted by now), and every US release has an earnings-call entry (prepared remarks filed with the SEC, else
transcript_unavailable). Only rows known by `now` are read (first_seen_at, filed_at, published_at <= now)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from marketbrief.analytics.event_history import earnings_events, load_events
from marketbrief.collectors.event_timing import timing
from marketbrief.constants.config_keys import CFG_FILINGS, CFG_TIMEZONE, FILINGS_SOURCE_SEC
from marketbrief.constants.range_inputs import SOURCE_SEC_HISTORY, TYPE_EARNINGS
from marketbrief.results.constants import KIND_CONCALL, KIND_RESULTS, TIME_DATE_ONLY, TIME_FILED

INDIA_RELEASES_SQL = """
SELECT ticker, period_end, min(filed_at) AS release_at FROM financials
WHERE period_type = 'quarterly' AND filed_at IS NOT NULL AND filed_at <= ?::TIMESTAMPTZ
  AND first_seen_at <= ?::TIMESTAMPTZ
GROUP BY ticker, period_end HAVING min(filed_at) >= ?::TIMESTAMPTZ ORDER BY release_at, ticker"""
ANNOUNCEMENTS_SQL = """
SELECT id, ticker, category, subject, url, coalesce(published_at, first_seen_at) AS published_at
FROM announcements_latest
WHERE first_seen_at <= ?::TIMESTAMPTZ AND coalesce(published_at, first_seen_at) <= ?::TIMESTAMPTZ
  AND coalesce(published_at, first_seen_at) >= ?::TIMESTAMPTZ
ORDER BY published_at, id"""
SEC_DATES_SQL = """
SELECT DISTINCT ticker, date FROM event_history
WHERE type = ? AND source = ? AND first_seen_at <= ?::TIMESTAMPTZ"""


@dataclass
class Release:
    """One results release or earnings-call text of one company."""

    id: str
    kind: str
    ticker: str
    release_at: pd.Timestamp
    release_date: date
    timing: str | None
    time_basis: str
    period_end: date | None = None
    announcement_ids: list[str] = field(default_factory=list)


def matches(text: str | None, terms: list[str]) -> bool:
    """True when the text holds one of the terms (case-insensitive)."""
    lowered = (text or "").lower()
    return any(term.lower() in lowered for term in terms)


def local_midnight_utc(cfg: dict, day: date) -> pd.Timestamp:
    """00:00 of a local date in the market's time zone, in UTC (the earliest a date-only release can be)."""
    local = datetime.combine(day, time(0), tzinfo=ZoneInfo(cfg[CFG_TIMEZONE]))
    return pd.Timestamp(local).tz_convert("UTC")


def announcements(con, now: pd.Timestamp, since: pd.Timestamp) -> list[dict]:
    """NSE announcements published in [since, now] and seen by now."""
    rows = con.execute(ANNOUNCEMENTS_SQL, [now.isoformat(), now.isoformat(), since.isoformat()]).df()
    return rows.to_dict("records")


def results_announcements(rows: list[dict], ticker: str, release_at: pd.Timestamp, conf: dict) -> list[str]:
    """Ids of a ticker's results announcements published within `india_results_days` of the release."""
    low, high = (pd.Timedelta(days=int(days)) for days in conf.get("india_results_days", [-1, 2]))
    return [
        row["id"]
        for row in rows
        if row["ticker"] == ticker
        and row["category"] in conf.get("india_results_categories", [])
        and matches(row["subject"], conf.get("india_results_terms", []))
        and release_at + low <= pd.Timestamp(row["published_at"]) <= release_at + high
    ]


def india_releases(con, cfg: dict, now: pd.Timestamp, since: pd.Timestamp, conf: dict) -> list[Release]:
    """India results releases (first filing of a quarter) and earnings-call transcripts published since `since`."""
    window_start = since + pd.Timedelta(days=int(conf.get("india_results_days", [-1, 2])[0]))
    rows = announcements(con, now, min(since, window_start))
    found = []
    for ticker, period_end, release_at in con.execute(
        INDIA_RELEASES_SQL, [now.isoformat(), now.isoformat(), since.isoformat()]
    ).fetchall():
        stamp = pd.Timestamp(release_at).tz_convert("UTC")
        day, when = timing(cfg, stamp)
        found.append(
            Release(
                f"{ticker}-results-{pd.Timestamp(period_end).date()}",
                KIND_RESULTS,
                ticker,
                stamp,
                day,
                when,
                TIME_FILED,
                pd.Timestamp(period_end).date(),
                results_announcements(rows, ticker, stamp, conf),
            )
        )
    for row in rows:
        stamp = pd.Timestamp(row["published_at"]).tz_convert("UTC")
        if (
            stamp >= since
            and row["category"] in conf.get("india_concall_categories", [])
            and matches(row["subject"], conf.get("india_concall_terms", []))
        ):
            day, when = timing(cfg, stamp)
            found.append(
                Release(
                    f"{row['ticker']}-concall-{row['id']}",
                    KIND_CONCALL,
                    row["ticker"],
                    stamp,
                    day,
                    when,
                    TIME_FILED,
                    announcement_ids=[row["id"]],
                )
            )
    return found


def us_releases(con, cfg: dict, now: pd.Timestamp, since: pd.Timestamp) -> list[Release]:
    """US results releases (SEC 2.02 dates kept by results_filter) since `since`, each with its call entry. The
    release time is the date's local midnight until the 2.02 filing's acceptance time is known (texts.refine)."""
    events = load_events(con)
    kept = earnings_events(events, as_of=now.date(), made_at=now.to_pydatetime()) if not events.empty else {}
    sec_dates = {
        (ticker, pd.Timestamp(day).date())
        for ticker, day in con.execute(SEC_DATES_SQL, [TYPE_EARNINGS, SOURCE_SEC_HISTORY, now.isoformat()]).fetchall()
    }
    found = []
    for ticker, rows in sorted(kept.items()):
        for day, when in rows:
            start = local_midnight_utc(cfg, day)
            if (ticker, day) not in sec_dates or day < since.date() or start > now:
                continue
            for kind in (KIND_RESULTS, KIND_CONCALL):
                found.append(Release(f"{ticker}-{kind}-{day}", kind, ticker, start, day, when, TIME_DATE_ONLY))
    return found


def detect(con, cfg: dict, now: pd.Timestamp, since: pd.Timestamp, conf: dict) -> list[Release]:
    """Every release of the market published in [since, now], newest first (ties by id)."""
    if cfg.get(CFG_FILINGS) == FILINGS_SOURCE_SEC:
        found = us_releases(con, cfg, now, since)
    else:
        found = india_releases(con, cfg, now, since, conf)
    tickers = set(cfg.get("tickers") or {})
    found = [release for release in found if release.ticker in tickers]
    return sorted(found, key=lambda release: (-release.release_at.value, release.id))
