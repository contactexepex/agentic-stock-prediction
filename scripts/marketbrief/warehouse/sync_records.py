"""What a warehouse sync records about itself: its row in meta.sync_runs, its row in rm.builds, the
summary JSON under work/warehouse/, and the facts these share (source commit, page counts, the month's
recorded sync time that the kill switch reads)."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone

from marketbrief.constants.warehouse import (
    MARKET_PAGE_KEY,
    META_SCHEMA,
    MSG_INVALID_PAGE,
    RM_OVERVIEW,
    SUMMARY_DIR,
    SYNC_RUNS_TABLE,
    UNKNOWN_COMMIT,
)
from marketbrief.core import paths
from marketbrief.warehouse.sql_statements import column_definitions, insert_row

SYNC_RUNS_COLUMNS = {
    "run_id": "VARCHAR",
    "market": "VARCHAR",
    "started_at": "TIMESTAMPTZ",
    "finished_at": "TIMESTAMPTZ",
    "cutoff": "TIMESTAMPTZ",
    "target": "VARCHAR",
    "tables": "VARCHAR[]",
    "table_rows": "JSON",
    "rows": "BIGINT",
    "read_models": "INTEGER",
    "mode": "VARCHAR",
    "ok": "BOOLEAN",
    "error": "VARCHAR",
}
SYNC_RUNS = f"{META_SCHEMA}.{SYNC_RUNS_TABLE}"
MONTH_HOURS_SQL = f"""SELECT coalesce(sum(epoch(finished_at) - epoch(started_at)), 0) / 3600
                      FROM {SYNC_RUNS} WHERE started_at >= ?"""


def wall_now() -> datetime:
    """The real time (UTC): when the sync ran, as opposed to the data's cut-off (MB_NOW)."""
    return datetime.now(timezone.utc)


def source_commit() -> str:
    """The git commit of the repo whose data/ the build reads, `unknown` outside a git checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(paths.ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return UNKNOWN_COMMIT
    return result.stdout.strip() or UNKNOWN_COMMIT


def new_run_row(market: str, mode: str, started_at: datetime, cutoff: str, target_label: str) -> dict:
    """The meta.sync_runs row of a run before it starts: not ok, nothing counted yet."""
    run_id = f"{market}-{started_at:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    return {
        **dict.fromkeys(SYNC_RUNS_COLUMNS),
        "run_id": run_id,
        "market": market,
        "mode": mode,
        "started_at": started_at,
        "cutoff": cutoff,
        "target": target_label,
        "ok": False,
        "tables": [],
        "table_rows": {},
        "rows": 0,
        "read_models": 0,
    }


def page_facts(rows: dict, invalid: list) -> dict:
    """The summary's view of the built pages: as_of, pages per table, payload bytes and invalid pages."""
    overview = rows.get(RM_OVERVIEW, {}).get(MARKET_PAGE_KEY)
    return {
        "as_of": overview["as_of"] if overview else None,
        "read_model_pages": {table: len(pages) for table, pages in rows.items()},
        "read_model_bytes": {
            table: sum(len(row["payload"].encode()) for row in pages.values()) for table, pages in rows.items()
        },
        "invalid_pages": [
            MSG_INVALID_PAGE.format(table=table, page_key=page_key, missing=", ".join(missing))
            for table, page_key, missing in invalid
        ],
    }


def build_row(run: dict, kind: str, commit: str, page_counts: dict, invalid_pages: list[str]) -> dict:
    """The rm.builds row of a finished run: ok only when the run committed and every page was valid."""
    return {
        "build_id": run["run_id"],
        "market": run["market"],
        "kind": kind,
        "cutoff": run["cutoff"],
        "source_commit": commit,
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "ok": bool(run["ok"] and not invalid_pages),
        "pages_written": page_counts.get("pages_written", 0),
        "pages_unchanged": page_counts.get("pages_unchanged", 0),
        "error": run["error"] or "; ".join(invalid_pages) or None,
    }


def ensure_sync_runs_table(warehouse) -> None:
    """The meta.sync_runs table."""
    warehouse.execute(f"CREATE SCHEMA IF NOT EXISTS {META_SCHEMA}")
    warehouse.execute(f"CREATE TABLE IF NOT EXISTS {SYNC_RUNS} ({column_definitions(SYNC_RUNS_COLUMNS)})")


def record_sync_run(warehouse, run: dict) -> None:
    """Append the run to meta.sync_runs (table_rows as JSON text)."""
    insert_row(warehouse, SYNC_RUNS, SYNC_RUNS_COLUMNS, {**run, "table_rows": json.dumps(run["table_rows"])})


def month_hours(warehouse, now: datetime) -> float:
    """This UTC month's recorded sync wall time in hours (all markets)."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return float(warehouse.execute(MONTH_HOURS_SQL, [month_start]).fetchone()[0])


def write_summary(market: str, summary: dict) -> str:
    """work/warehouse/<market>-sync.json; returns its repo-relative path."""
    folder = paths.ROOT / SUMMARY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{market}-sync.json").write_text(json.dumps(summary, indent=2, default=str))
    return f"{SUMMARY_DIR}/{market}-sync.json"
