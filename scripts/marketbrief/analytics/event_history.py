"""Event history for the range engine: earnings, ex-dividend and periodic-report rows from stored data. Earnings
dates are read through earnings_events, which keeps only the SEC item 2.02 filings that are a quarter's results
release (results_filter, by the stored 10-Q/10-K reports, without look-ahead).

Shared by the live ranges and the walk-forward backtest, so both use the same rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from marketbrief.constants.columns import COL_DATE, COL_FIRST_SEEN_AT, COL_SOURCE, COL_TICKER, COL_TYPE
from marketbrief.constants.range_inputs import (
    DAYS_PER_YEAR,
    HISTORY_SUFFIX,
    LOAD_EVENTS_SQL,
    MOVED_DAYS,
    NEAR_DAYS,
    PENDING_LAG_SHARE,
    PENDING_MIN_RELEASES,
    PROJECTED_SLACK_DAYS,
    REPORT_GRACE_DAYS,
    REPORT_WINDOW_DAYS,
    SAME_QUARTER_DAYS,
    SOURCE_SEC_HISTORY,
    SOURCE_YFINANCE_HISTORY,
    TYPE_EARNINGS,
    TYPE_EX_DIVIDEND,
    TYPE_PERIODIC_REPORT,
)

Release = tuple[date, str | None, str]  # (date, timing, source)


def as_date(value) -> date:
    """The calendar date of a date, timestamp or ISO text."""
    return pd.Timestamp(value).date()


def drop_moved_upcoming(events: pd.DataFrame) -> pd.DataFrame:
    """Drop upcoming rows whose date was later moved (a newer upcoming row within MOVED_DAYS)."""
    if events.empty:
        return events
    is_history = events[COL_SOURCE].fillna("").str.endswith(HISTORY_SUFFIX)
    keep = []
    for index, row in events.iterrows():
        if is_history[index]:
            keep.append(True)
            continue
        newer = events[
            (~is_history)
            & (events[COL_TICKER] == row[COL_TICKER])
            & (events[COL_TYPE] == row[COL_TYPE])
            & (events[COL_FIRST_SEEN_AT] > row[COL_FIRST_SEEN_AT])
            & (events[COL_DATE] != row[COL_DATE])
        ]
        keep.append(not any(abs((day - row[COL_DATE]).days) <= MOVED_DAYS for day in newer[COL_DATE]))
    return events[keep]


def load_events(con) -> pd.DataFrame:
    """Earnings, ex-dividend and (SEC markets) periodic-report rows of the event history."""
    events = con.execute(LOAD_EVENTS_SQL).df()
    if events.empty:
        return events
    events[COL_DATE] = events[COL_DATE].map(as_date)
    events["period_end"] = events["period_end"].map(lambda value: None if pd.isna(value) else as_date(value))
    return drop_moved_upcoming(events)


def periodic_reports(events: pd.DataFrame) -> dict[str, list[tuple[date, date | None]]]:
    """Per ticker: (acceptance date, period end) of each stored 10-Q/10-K, oldest first."""
    found: dict[str, list] = {}
    if events.empty or "period_end" not in events.columns:
        return found
    for row in events[events[COL_TYPE] == TYPE_PERIODIC_REPORT].itertuples():
        found.setdefault(row.ticker, []).append((row.date, None if pd.isna(row.period_end) else row.period_end))
    return {ticker: sorted(set(reports)) for ticker, reports in found.items()}


@dataclass
class ConfirmedReleases:
    """What the stored 10-Q/10-K reports confirm among the SEC 2.02 dates: the dates to keep, the confirmed
    releases, the period ends released, the release lags (days after a period end) and the earliest window start."""

    keep: set[date] = field(default_factory=set)
    confirmed: list[date] = field(default_factory=list)
    released: set[date] = field(default_factory=set)
    lags: list[int] = field(default_factory=list)
    first_lo: date | None = None


def confirm_releases(known: list[tuple[date, date | None]], sec: list[date]) -> ConfirmedReleases:
    """For each report, its results release is the latest 2.02 after its period end and up to REPORT_GRACE_DAYS
    after its acceptance; 2.02s within NEAR_DAYS before it are the same report."""
    found = ConfirmedReleases()
    for filed, period_end in known:
        low = period_end if period_end is not None else filed - timedelta(days=REPORT_WINDOW_DAYS)
        found.first_lo = low if found.first_lo is None else min(found.first_lo, low)
        candidates = [
            release_date for release_date in sec if low < release_date <= filed + timedelta(days=REPORT_GRACE_DAYS)
        ]
        if not candidates:
            continue
        release = max(candidates)
        found.keep.update(release_date for release_date in candidates if (release - release_date).days <= NEAR_DAYS)
        found.confirmed.append(release)
        if period_end is not None:
            found.released.add(period_end)
            found.lags.append((release - period_end).days)
    return found


def projected_period_ends(known: list[tuple[date, date | None]]) -> list[date]:
    """The known period ends, and each projected a year on unless a known one is that close."""
    period_ends = {known_end for _, known_end in known if known_end is not None}
    year = timedelta(days=DAYS_PER_YEAR)
    projected = {
        period_end + year
        for period_end in period_ends
        if all(abs((other_end - period_end).days - DAYS_PER_YEAR) > PROJECTED_SLACK_DAYS for other_end in period_ends)
    }
    return sorted(period_ends | projected)


def keep_unconfirmed(sec: list[date], found: ConfirmedReleases, known: list[tuple[date, date | None]]) -> None:
    """Add the 2.02 dates that no report window confirms or rejects to found.keep: those before the first window
    (cannot tell) and those pending after the newest one (its report is not filed yet), judged by their lag."""
    last_hi = known[-1][0] + timedelta(days=REPORT_GRACE_DAYS)
    ends = projected_period_ends(known)
    for day in sec:
        if day <= found.first_lo:
            found.keep.add(day)  # before the first report: cannot tell
        elif day > last_hi:  # pending: its report is not filed yet
            period_end = max((candidate_end for candidate_end in ends if candidate_end < day), default=None)
            if len(found.lags) < PENDING_MIN_RELEASES or period_end is None:
                found.keep.add(day)
            elif period_end not in found.released and (day - period_end).days >= PENDING_LAG_SHARE * min(found.lags):
                found.keep.add(day)


def results_filter(
    rows: list[Release], reports: list[tuple[date, date | None]], as_of: date | None = None
) -> list[Release]:
    """Drop the SEC item 2.02 filings that are not a quarter's results release, and the yfinance
    history dates that disagree with a confirmed SEC release. `rows` are (date, timing, source).

    Only the 10-Q/10-K reports accepted on or before `as_of` are used (all stored ones if None), so
    a walk-forward replay never uses a later filing. For each report, the results release is the
    latest 2.02 after its period end and up to REPORT_GRACE_DAYS after its acceptance (other 2.02s
    in that window, e.g. Tesla's delivery reports or pre-announcements, are not results; 2.02s
    within NEAR_DAYS before it are the same report). A 2.02 between that window and the next
    period end is not results either. A 2.02 after the newest report's window is pending (its
    10-Q is not filed yet) and counts, unless PENDING_MIN_RELEASES releases are confirmed and it
    falls before the next period end (projected a year from the same quarter) or sooner after it
    than PENDING_LAG_SHARE x the shortest confirmed lag. A 2.02 older than the first window, and
    every date of a ticker without reports (non-SEC markets, history stored before reports were),
    is kept. A `yfinance_history` date within SAME_QUARTER_DAYS of a confirmed SEC release
    (more than NEAR_DAYS away) is dropped: the SEC release wins. Other rows are kept."""
    known = sorted((filed, period_end) for filed, period_end in reports if as_of is None or filed <= as_of)
    if not known:
        return list(rows)
    sec = sorted({release_date for release_date, _, source in rows if source == SOURCE_SEC_HISTORY})
    found = confirm_releases(known, sec)
    keep_unconfirmed(sec, found, known)
    kept = []
    for day, timing, source in rows:
        if source == SOURCE_SEC_HISTORY:
            if day in found.keep:
                kept.append((day, timing, source))
        elif source == SOURCE_YFINANCE_HISTORY and any(
            NEAR_DAYS < abs((day - confirmed_release).days) <= SAME_QUARTER_DAYS
            for confirmed_release in found.confirmed
        ):
            continue
        else:
            kept.append((day, timing, source))
    return kept


def earnings_events(events: pd.DataFrame, as_of: date | None = None) -> dict[str, list[tuple[date, str | None]]]:
    """Per ticker: (date, timing) of every known earnings report, one row per report (a timed row
    beats an untimed one for the same report). SEC 2.02 filings that are not results releases are
    dropped using the 10-Q/10-K reports accepted by `as_of` (all if None; see results_filter)."""
    found: dict[str, list] = {}
    if events.empty:
        return found
    reports = periodic_reports(events)
    earnings = events[events[COL_TYPE] == TYPE_EARNINGS]
    for ticker, group in earnings.groupby(COL_TICKER):
        rows = results_filter(
            [
                (report.date, None if pd.isna(report.timing) else report.timing, str(report.source or ""))
                for report in group.itertuples()
            ],
            reports.get(ticker, []),
            as_of,
        )
        rows = sorted(
            ((day, timing) for day, timing, _ in rows), key=lambda candidate: (candidate[1] is None, candidate[0])
        )
        kept: list = []
        for day, timing in rows:
            if all(abs((day - kept_day).days) > NEAR_DAYS for kept_day, _ in kept):
                kept.append((day, timing))
        if kept:
            found[ticker] = sorted(kept)
    return found


def earnings_versions(events: pd.DataFrame) -> dict[str, list[tuple[date | None, list[tuple[date, str | None]]]]]:
    """Per ticker: (first as-of date, earnings events known then), oldest first. The events only
    change when a 10-Q/10-K is accepted, so a walk-forward backtest uses the version whose start
    is the latest on or before its as-of date (None = before the first stored report)."""
    reports = periodic_reports(events)
    tickers = sorted(set(events.loc[events[COL_TYPE] == TYPE_EARNINGS, COL_TICKER])) if not events.empty else []
    found: dict[str, list] = {}
    for ticker in tickers:
        sub = events[events[COL_TICKER] == ticker]
        cuts = sorted({filed for filed, _ in reports.get(ticker, [])})
        versions = [(None, earnings_events(sub, as_of=date.min).get(ticker, []))]
        versions += [(cut, earnings_events(sub, as_of=cut).get(ticker, [])) for cut in cuts]
        found[ticker] = versions
    return found


def dividend_events(events: pd.DataFrame) -> dict[str, list[tuple[date, float | None]]]:
    """Per ticker: (ex-date, amount); a missing amount is the last known one before it."""
    found: dict[str, list] = {}
    if events.empty:
        return found
    dividends = events[events[COL_TYPE] == TYPE_EX_DIVIDEND]
    for ticker, group in dividends.groupby(COL_TICKER):
        rows, last = [], None
        for day, same_day in group.groupby(COL_DATE):
            amounts = [
                float(stored_amount)
                for stored_amount in same_day["amount"]
                if stored_amount == stored_amount and stored_amount is not None
            ]
            amount = amounts[0] if amounts else last
            rows.append((day, amount))
            last = amount if amount is not None else last
        found[ticker] = rows
    return found
