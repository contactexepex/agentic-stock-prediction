"""Storage and summary helpers shared by the collectors of dated source files: the free-source collectors (issue #9:
macro, shorts, flows_india) and the NSE collectors.

The HTTP clients are in marketbrief/sources/ and FetchError is marketbrief/sources/errors.py. Tests pass a fake
client with the same `get` method, so nothing here touches the network."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from marketbrief.constants.columns import COL_COMPLETE, COL_DATE, COL_ID
from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.constants.free_sources import REFETCH_SESSIONS
from marketbrief.constants.statuses import (
    SUMMARY_ALLOWLIST,
    SUMMARY_ALLOWLIST_NEEDED,
    SUMMARY_COLLECTOR,
    SUMMARY_FAILED,
    SUMMARY_MARKET,
    SUMMARY_NEW,
    SUMMARY_NOTES,
    SUMMARY_REQUESTS,
    SUMMARY_WARNINGS,
)
from marketbrief.core.calendar import prev_session
from marketbrief.core.paths import data_dir
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.sources.errors import FetchError

NOT_PUBLISHED_STATUSES = (403, 404)



@dataclass
class Problems:
    """What went wrong or is worth a note in one collector run: the summary's failed, notes and warnings lists."""

    failed: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def not_published(exc: FetchError) -> bool:
    """Per-day files on S3/CDN buckets answer 403 or 404 for a day that has no file (yet)."""
    return exc.status in NOT_PUBLISHED_STATUSES


def stale_cutoff(cfg: dict, today: date) -> date:
    """A per-day file missing for a session before this date is a failure, not a publishing lag:
    the latest completed session (before today) may still be in the publisher's queue."""
    return prev_session(cfg, today, include=False)


def stored_rows(market: str, kind: str, files: int = 400) -> dict[str, dict]:
    """Latest stored row per id across the newest `files` daily files of a kind."""
    latest: dict[str, dict] = {}
    for file in sorted((data_dir(market) / kind).glob(JSONL_GLOB))[-files:]:
        for line in file.read_text(encoding=ENCODING_UTF8).splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row[COL_ID]] = row
    return latest


def is_complete(row: dict) -> bool:
    """A stored row's `complete`; rows stored before the field existed count as complete (issue #27)."""
    return row.get(COL_COMPLETE, True) is not False


def refetch_since(cfg: dict, today: date) -> date:
    """The oldest session still fetched again when stored incomplete (REFETCH_SESSIONS sessions back)."""
    day = today
    for _ in range(REFETCH_SESSIONS):
        day = prev_session(cfg, day, include=False)
    return day


def complete_days(
    market: str, kind: str, key_col: str, required: set[str], final_before: date | None = None
) -> set[str]:
    """Dates whose stored rows (latest per id) cover every required key with `complete` true, plus (with
    `final_before`) every stored date before it: a key still absent then is taken as absent at the source, so the
    day is not fetched and reported again on every run (issue #27). Other dates (missing, partial, truncated) are
    fetched again while they are in the lookback."""
    have: dict[str, set[str]] = {}
    stored_days: set[str] = set()
    for row in stored_rows(market, kind).values():
        stored_days.add(str(row[COL_DATE]))
        if is_complete(row) and row.get(key_col) in required:
            have.setdefault(row[COL_DATE], set()).add(row[key_col])
    done = {day for day, keys in have.items() if keys >= required}
    return done | ({day for day in stored_days if day < str(final_before)} if final_before else set())


def store_changed(market: str, kind: str, rows: list[dict], today: date, value_cols: list[str]) -> int:
    """Append rows whose id is new, or whose values differ from the latest stored row with that id
    (a revision is a new record, never an edit). Duplicates within `rows` keep the last one."""
    stored = stored_rows(market, kind)
    fresh: dict[str, dict] = {}
    for row in rows:
        old = stored.get(row[COL_ID])
        if old is None or any(
            (is_complete(old) != is_complete(row)) if column == COL_COMPLETE else old.get(column) != row.get(column)
            for column in value_cols
        ):
            fresh[row[COL_ID]] = row
    return append_jsonl(day_file(market, kind, today), fresh.values()) if fresh else 0


def summary(collector: str, market: str, new: dict, problems: Problems, client) -> dict:
    """A collector's JSON summary; names the hosts to allowlist when the egress proxy refused some."""
    failed, notes, warnings = problems.failed, problems.notes, problems.warnings
    out = {
        SUMMARY_COLLECTOR: collector,
        SUMMARY_MARKET: market,
        SUMMARY_NEW: new,
        SUMMARY_FAILED: failed,
        SUMMARY_WARNINGS: warnings,
        SUMMARY_NOTES: notes,
        SUMMARY_REQUESTS: getattr(client, "requests", None),
    }
    hosts = sorted({failure[SUMMARY_ALLOWLIST] for failure in failed if failure.get(SUMMARY_ALLOWLIST)})
    if hosts:
        out[SUMMARY_ALLOWLIST_NEEDED] = hosts
    return out
