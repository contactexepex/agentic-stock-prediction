"""News and NSE announcements awaiting the news analyst (routine step 7; docs/DESIGN.md section 3, "News timing").

With news-only light runs collecting every 4 hours, the pre-open run must enrich everything stored since the
previous pre-open enrichment, not just today's file. The window is (since, now], since = the EARLIER of
- the newest `first_seen_at` among the news and announcements already enriched (news_enriched rows analyzed
  at or before now): items collected after the last enriched item, even by a light run that pushed while
  the previous pre-open run was working, are pending; and
- the start of today (UTC): today's items, the window used before light runs existed, are always in it;
and never more than PENDING_MAX_DAYS (7) before now. No enrichment stored: the start of today.
Pending = the window's news and announcement ids that have no news_enriched row yet, plus every news item whose
headline changed in the window (a news_updates row seen in (since, now], news de-duplication, DESIGN.md section 3)
after its latest enrichment: the analyst scores the new headline and appends a newer news_enriched row, so the
latest enrichment as of a time belongs to the headline shown then. Such rows carry `headline_updated_at`.
`validate.py --stage news` checks the analyst's file against the same window.

    python scripts/news_pending.py [--out work/news_pending.jsonl]

writes one JSON line per pending item (news: title, source, url, feed, category, tickers; announcements:
ticker, category, subject, url) for the news analyst and prints a JSON summary (`since`, counts, `out`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from marketbrief.constants.news_pending import (
    ANNOUNCEMENT_COLUMNS,
    ITEM_KIND_ANNOUNCEMENT,
    ITEM_KIND_NEWS,
    NEWS_COLUMNS,
    PENDING_FILE,
    PENDING_MAX_DAYS,
    STEP_NEWS_PENDING,
)
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock
from marketbrief.core.database import connect

LAST_ENRICHED_ITEM_SQL = """
WITH done AS (SELECT DISTINCT id FROM news_enriched WHERE analyzed_at <= ?::TIMESTAMPTZ)
SELECT max(first_seen_at) FROM (
    SELECT first_seen_at FROM news_stored WHERE id IN (SELECT id FROM done)
    UNION ALL SELECT first_seen_at FROM announcements WHERE id IN (SELECT id FROM done)
) WHERE first_seen_at <= ?::TIMESTAMPTZ"""
ENRICHED_SQL = "SELECT DISTINCT id FROM news_enriched"
WINDOW_SQL = (
    "SELECT {columns} FROM {table} WHERE first_seen_at > ?::TIMESTAMPTZ AND first_seen_at <= ?::TIMESTAMPTZ "
    "ORDER BY first_seen_at, id"
)
NEWS_WINDOW_SQL = (  # one row per item, the headline seen by now
    "SELECT {columns} FROM news_asof(?::TIMESTAMPTZ) WHERE first_seen_at > ?::TIMESTAMPTZ "
    "AND first_seen_at <= ?::TIMESTAMPTZ ORDER BY first_seen_at, id"
)
UPDATED_SQL = """
SELECT coalesce(m.canonical_id, u.news_id) AS id, max(u.seen_at) AS headline_at
FROM news_updates u LEFT JOIN news_id_map m ON m.id = u.news_id
WHERE u.seen_at > ?::TIMESTAMPTZ AND u.seen_at <= ?::TIMESTAMPTZ GROUP BY 1 ORDER BY 1"""
LATEST_ENRICHMENT_SQL = "SELECT id, max(analyzed_at) FROM news_enriched_asof(?::TIMESTAMPTZ) GROUP BY id"
UPDATED_ROWS_SQL = "SELECT {columns} FROM news_asof(?::TIMESTAMPTZ) WHERE list_contains(?, id) ORDER BY id"


def as_utc(value) -> pd.Timestamp:
    """A timestamp as an aware UTC pandas Timestamp."""
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def enrichment_since(con, now) -> pd.Timestamp:
    """The start of the window the analyst covers (see the module docstring)."""
    now = as_utc(now)
    since = now.normalize()
    last = con.execute(LAST_ENRICHED_ITEM_SQL, [now.isoformat(), now.isoformat()]).fetchone()[0]
    if last is not None:
        since = min(since, as_utc(last))
    return max(since, now - pd.Timedelta(days=PENDING_MAX_DAYS))


def headline_updates(con, since: pd.Timestamp, now) -> dict[str, pd.Timestamp]:
    """Item id -> its newest headline update seen in (since, now]."""
    rows = con.execute(UPDATED_SQL, [since.isoformat(), as_utc(now).isoformat()]).fetchall()
    return {news_id: as_utc(seen) for news_id, seen in rows}


def rescore_ids(con, since: pd.Timestamp, now) -> set[str]:
    """Items whose headline changed in the window after their latest enrichment analyzed by now (or never enriched)."""
    updated = headline_updates(con, since, now)
    if not updated:
        return set()
    scored = {
        news_id: as_utc(at)
        for news_id, at in con.execute(LATEST_ENRICHMENT_SQL, [as_utc(now).isoformat()]).fetchall()
        if at is not None
    }
    return {news_id for news_id, seen in updated.items() if news_id not in scored or scored[news_id] < seen}


def window_rows(con, since: pd.Timestamp, now) -> list[dict]:
    """News and announcement rows first seen in (since, now], oldest first, each with its `kind`, then the news items
    first seen earlier whose headline changed in the window; a news row shows its headline as of now."""
    now_text = as_utc(now).isoformat()
    bounds = [since.isoformat(), now_text]
    rows = []
    for kind, sql, params in (
        (ITEM_KIND_NEWS, NEWS_WINDOW_SQL.format(columns=", ".join(NEWS_COLUMNS)), [now_text, *bounds]),
        (
            ITEM_KIND_ANNOUNCEMENT,
            WINDOW_SQL.format(columns=", ".join(ANNOUNCEMENT_COLUMNS), table="announcements"),
            bounds,
        ),
    ):
        frame = con.execute(sql, params).df()
        for record in frame.to_dict("records"):
            rows.append({"kind": kind, **{key: clean(value) for key, value in record.items()}})
    updated = headline_updates(con, since, now)
    seen = {row["id"] for row in rows}
    later = sorted(set(updated) - seen)
    if later:
        frame = con.execute(UPDATED_ROWS_SQL.format(columns=", ".join(NEWS_COLUMNS)), [now_text, later]).df()
        rows += [
            {"kind": ITEM_KIND_NEWS, **{key: clean(value) for key, value in record.items()}}
            for record in frame.to_dict("records")
        ]
    for row in rows:
        if row["kind"] == ITEM_KIND_NEWS and row["id"] in updated:
            row["headline_updated_at"] = updated[row["id"]].isoformat()
    return rows


def clean(value):
    """A DuckDB value as plain JSON: timestamps as ISO strings, arrays as lists, missing as None."""
    if isinstance(value, pd.Timestamp):
        return as_utc(value).isoformat()
    if hasattr(value, "tolist"):
        return value.tolist()
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def window_ids(con, now) -> tuple[pd.Timestamp, set[str]]:
    """(since, every news and announcement id first seen in the window, enriched or not)."""
    since = enrichment_since(con, now)
    return since, {row["id"] for row in window_rows(con, since, now)}


def pending_rows(con, now) -> tuple[pd.Timestamp, list[dict]]:
    """(since, the window's rows that have no enrichment yet or whose headline changed after their enrichment)."""
    since = enrichment_since(con, now)
    done = {row[0] for row in con.execute(ENRICHED_SQL).fetchall()}
    again = rescore_ids(con, since, now)
    return since, [row for row in window_rows(con, since, now) if row["id"] not in done or row["id"] in again]


def write_pending(market: str, out: Path) -> dict:
    """Write the pending rows to `out` (replaced: it is a work file) and return the summary."""
    now = as_utc(clock())
    since, rows = pending_rows(connect(market), now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows), encoding="utf-8")
    return {
        "step": STEP_NEWS_PENDING,
        "market": market,
        "now": now.isoformat(),
        "since": since.isoformat(),
        "news": sum(1 for row in rows if row["kind"] == ITEM_KIND_NEWS),
        "announcements": sum(1 for row in rows if row["kind"] == ITEM_KIND_ANNOUNCEMENT),
        "out": out.relative_to(paths.ROOT).as_posix() if out.is_relative_to(paths.ROOT) else str(out),
    }


def main() -> int:
    """Entry point of scripts/news_pending.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--out", type=Path, help=f"output file (default {PENDING_FILE})")
    args = parser.parse_args()
    cfg = require_market(args)
    out = args.out or paths.ROOT / PENDING_FILE
    print(json.dumps(write_pending(cfg["market"], out), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
