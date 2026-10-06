"""NSE part of the events collector (India): past results releases from the NSE results filings, polled only for
tickers that are due (see nse_due), dated and timed by the filings and refined by the results announcements."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.collectors.event_timing import timing
from marketbrief.constants.columns import COL_DATE, COL_SOURCE, COL_TICKER, COL_TYPE
from marketbrief.constants.events import (
    ANNUAL_QUARTER_MONTH,
    EVENT_EARNINGS,
    HISTORY_SUFFIX,
    LATE_FILING_DAYS_ANNUAL,
    LATE_FILING_DAYS_QUARTERLY,
    MSG_INTEGRATED_LIST_PARTIAL,
    MSG_LATE_QUARTERS,
    NEAR_DAYS,
    NSE_ENDPOINT_ANNOUNCEMENTS,
    NSE_ENDPOINT_FINANCIAL,
    NSE_ENDPOINT_INTEGRATED,
    NSE_FIELDS_ANNOUNCED,
    NSE_FIELDS_BROADCAST,
    NSE_FIELDS_FINANCIAL_BROADCAST,
    NSE_FIELDS_FINANCIAL_TO,
    NSE_FIELDS_QUARTER_END,
    NSE_INTEGRATED_TYPE,
    NSE_SOURCE_PREFIX,
    NSE_STALE_DAYS,
    PRIORITY_FILING,
    RELEASE_WINDOW_HOURS,
    RESULTS_ANNOUNCEMENTS,
    SOURCE_NSE_HISTORY,
)
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_client import Nse
from marketbrief.sources.nse_parsing import IST, nse_symbols, parse_day, parse_ts, pick, rows_of

RELEASE_WINDOW = timedelta(hours=RELEASE_WINDOW_HOURS)


def max_filing_lag(period_end: date) -> int:
    """SEBI LODR regulation 33: quarterly results within 45 days of the quarter end, the annual
    (March quarter) results within 60. A first filing later than that (plus 3 days' grace) is a
    late XBRL upload, not the release, so its date is not used."""
    return LATE_FILING_DAYS_ANNUAL if period_end.month == ANNUAL_QUARTER_MONTH else LATE_FILING_DAYS_QUARTERLY


def nse_results_filings(nse: Nse, symbol: str, backfill: bool) -> tuple[list[tuple[date, datetime]], list[str]]:
    """(period end, broadcast time UTC) of each results filing NSE lists for a symbol: SEBI
    Integrated Filing (Financials), used from the March 2025 quarter on, and, when backfilling,
    the older financial-results list (quarters to December 2024). Returns (filings, notes)."""
    notes = []
    payload = nse.json(NSE_ENDPOINT_INTEGRATED, {"index": "equities", "symbol": symbol, "type": NSE_INTEGRATED_TYPE})
    rows = rows_of(payload)
    total = payload.get("totalCount") if isinstance(payload, dict) else None
    if isinstance(total, int) and total > len(rows):
        notes.append(MSG_INTEGRATED_LIST_PARTIAL.format(symbol=symbol, rows=len(rows), total=total))
    found = [(parse_day(pick(r, NSE_FIELDS_QUARTER_END)), parse_ts(pick(r, *NSE_FIELDS_BROADCAST))) for r in rows]
    if backfill:
        rows = rows_of(nse.json(NSE_ENDPOINT_FINANCIAL, {"index": "equities", "period": "Quarterly", "symbol": symbol}))
        found += [
            (parse_day(pick(r, NSE_FIELDS_FINANCIAL_TO)), parse_ts(pick(r, *NSE_FIELDS_FINANCIAL_BROADCAST)))
            for r in rows
        ]
    return [(period_end, stamp) for period_end, stamp in found if period_end and stamp], notes


def nse_release_times(nse: Nse, symbol: str, start: date, today: date) -> list[datetime]:
    """Times (UTC) of the symbol's results-type announcements (board meeting outcome, results
    PDF) from start to today: the first public release, usually before the XBRL filing."""
    rows = rows_of(
        nse.json(
            NSE_ENDPOINT_ANNOUNCEMENTS,
            {"index": "equities", "symbol": symbol, "from_date": f"{start:%d-%m-%Y}", "to_date": f"{today:%d-%m-%Y}"},
        )
    )
    return [
        stamp
        for r in rows
        if pick(r, "desc") in RESULTS_ANNOUNCEMENTS and (stamp := parse_ts(pick(r, *NSE_FIELDS_ANNOUNCED)))
    ]


def nse_reports(
    cfg: dict, filings: list[tuple[date, datetime]], releases: list[datetime], after: date | None = None
) -> tuple[list[tuple[date, str | None, int]], int]:
    """One (date, timing, priority 0) per reported quarter: the earliest filing for the period
    end (standalone or consolidated, original or revised), moved earlier to a results
    announcement up to RELEASE_WINDOW before it. Only quarters first filed after `after` (IST).
    Returns (rows, quarters dropped because their first filing came after the SEBI deadline)."""
    first: dict[date, datetime] = {}
    for period_end, stamp in filings:
        first[period_end] = min(first.get(period_end, stamp), stamp)
    found, late = [], 0
    for period_end, stamp in sorted(first.items()):
        filed = stamp.astimezone(IST).date()
        if after is not None and filed <= after:
            continue
        if not 0 < (filed - period_end).days <= max_filing_lag(period_end):
            late += 1
            continue
        release = min([a for a in releases if stamp - RELEASE_WINDOW <= a <= stamp] + [stamp])
        day, when = timing(cfg, pd.Timestamp(release))
        found.append((day, when, PRIORITY_FILING))
    return found, late


def nse_due(stored: list[dict], tickers: list[str], today: date) -> dict[str, date | None]:
    """Tickers to poll -> newest stored past earnings date (a `_history` row of any source), or
    None = no NSE results stored yet: backfill (retried on the next run if it fails). A ticker
    with NSE results is due when an upcoming earnings date stored earlier has passed since its
    newest past date, or when that date is NSE_STALE_DAYS old. Otherwise it is not polled, so a
    quiet day costs no NSE calls."""
    last: dict[str, date] = {}
    has_nse: set[str] = set()
    known: dict[str, list[date]] = {}
    for row in stored:
        if row.get(COL_TYPE) != EVENT_EARNINGS or row.get(COL_TICKER) not in tickers:
            continue
        day = date.fromisoformat(str(row[COL_DATE])[:10])
        known.setdefault(row[COL_TICKER], []).append(day)
        if str(row.get(COL_SOURCE, "")).endswith(HISTORY_SUFFIX):
            last[row[COL_TICKER]] = max(last.get(row[COL_TICKER], day), day)
        if row.get(COL_SOURCE) == SOURCE_NSE_HISTORY:
            has_nse.add(row[COL_TICKER])
    due: dict[str, date | None] = {}
    for ticker in tickers:
        if ticker not in has_nse:
            due[ticker] = None
        elif (today - last[ticker]).days >= NSE_STALE_DAYS or any(
            last[ticker] + timedelta(days=NEAR_DAYS) < d <= today for d in known.get(ticker, [])
        ):
            due[ticker] = last[ticker]
    return due


def nse_ticker_rows(
    cfg: dict, nse: Nse, symbol: str, last: date | None, window: tuple[date, date], notes: list[str]
) -> tuple[list[tuple[date, str | None, int]], int]:
    """(rows, quarters filed late) of one ticker's NSE results, with the filings' notes added to `notes` as soon
    as they are known: a backfill (last is None) reaches back to `since`; a ticker with stored history only takes
    quarters filed more than NEAR_DAYS after its newest date. `window` = (since, today)."""
    since, today = window
    after = None if last is None else last + timedelta(days=NEAR_DAYS)
    filings, filing_notes = nse_results_filings(nse, symbol, backfill=last is None)
    notes += filing_notes
    filings = [(period_end, stamp) for period_end, stamp in filings if stamp.astimezone(IST).date() >= since]
    new = [stamp for _, stamp in filings if after is None or stamp.astimezone(IST).date() > after]
    releases = nse_release_times(nse, symbol, min(new).astimezone(IST).date() - timedelta(days=2), today) if new else []
    return nse_reports(cfg, filings, releases, after)


def nse_earnings(
    cfg: dict, nse: Nse, due: dict[str, date | None], since: date, today: date
) -> tuple[dict[str, list[tuple[date, str | None, int]]], list[dict], list[str]]:
    """Past results releases from NSE for the due tickers (see nse_due), dated and timed by the
    results filings and refined by the results announcements. Returns (rows per ticker, failures, notes);
    a host the egress proxy refuses stops the remaining calls."""
    symbol_of = {ticker: symbol for symbol, ticker in nse_symbols(cfg).items()}
    found: dict[str, list] = {}
    failed: list[dict] = []
    notes: list[str] = []
    for ticker, last in due.items():
        try:
            rows, late = nse_ticker_rows(cfg, nse, symbol_of[ticker], last, (since, today), notes)
        except FetchError as exc:
            failed.append(exc.entry(f"{NSE_SOURCE_PREFIX}{ticker}"))
            if exc.host:
                break
            continue
        if late:
            notes.append(MSG_LATE_QUARTERS.format(ticker=ticker, count=late))
        if rows:
            found[ticker] = rows
    return found, failed, notes
