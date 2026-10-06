"""Exchange announcements of the NSE primary-source collector: one market-wide call over the last `lookback` days;
with `since` (backfill), one call per week from `since` to today -> data/india/announcements/."""

from __future__ import annotations

from datetime import date, timedelta

from marketbrief.collectors.nse_runner import NseRun, coverage, date_windows
from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.nse_collection import (
    ENDPOINT_ANNOUNCEMENTS,
    MSG_ANNOUNCEMENTS_COVERAGE,
    MSG_PIT_LABEL_DAYS,
    MSG_PIT_LABEL_SINCE,
    NSE_DATE_ARGUMENT,
    SOURCE_ANNOUNCEMENTS,
)
from marketbrief.sources.nse_parsing import iso, parse_ts, pick, rows_of


def announcement_rows(run: NseRun, windows: list[tuple[date, date]]) -> list[dict]:
    """The announcement rows of every window (one call each)."""
    rows = []
    for start, end in windows:
        answer = run.nse.json(
            ENDPOINT_ANNOUNCEMENTS,
            {
                "index": "equities",
                "from_date": start.strftime(NSE_DATE_ARGUMENT),
                "to_date": end.strftime(NSE_DATE_ARGUMENT),
            },
        )
        rows += rows_of(answer if isinstance(answer, list) else answer.get("data", []))
    return rows


def announcements(run: NseRun, lookback: int, since: date | None = None) -> list[dict]:
    """The watchlist announcements of the last `lookback` days (or one call per week from `since`)."""
    windows = [(run.today - timedelta(days=lookback), run.today)] if since is None else date_windows(since, run.today)
    rows = announcement_rows(run, windows)
    label = (
        MSG_PIT_LABEL_DAYS.format(lookback=lookback)
        if since is None
        else MSG_PIT_LABEL_SINCE.format(since=since, windows=len(windows))
    )
    coverage(
        MSG_ANNOUNCEMENTS_COVERAGE.format(label=label),
        len(rows),
        sum((listed_row.get("symbol") or "").strip().upper() in run.symbols for listed_row in rows),
        run.problems,
    )
    found = []
    for row in rows:
        ticker = run.symbols.get((row.get("symbol") or "").strip().upper())
        sequence = pick(row, "seq_id")
        if not ticker or not sequence:
            continue
        found.append(
            {
                COL_ID: f"nse-ann-{sequence}",
                COL_TICKER: ticker,
                "company": pick(row, "sm_name"),
                "published_at": iso(parse_ts(pick(row, "an_dt", "exchdisstime", "sort_date"))),
                "category": pick(row, "desc"),
                "subject": pick(row, "attchmntText"),
                "url": pick(row, "attchmntFile"),
                "source": SOURCE_ANNOUNCEMENTS,
                "first_seen_at": run.now,
            }
        )
    return found
