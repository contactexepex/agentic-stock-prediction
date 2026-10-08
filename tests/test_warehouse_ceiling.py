"""The kill switch's monthly time (scripts/marketbrief/warehouse/sync_records.py): each run counts the seconds it
held the warehouse connection (connected_s), a run recorded before that column existed its whole wall time, and a
meta.sync_runs table created before the column gets it on the next sync. Offline, in-memory DuckDB."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.warehouse import sync_records  # noqa: E402
from marketbrief.warehouse.sql_statements import column_definitions  # noqa: E402

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
COLUMNS_BEFORE = {name: kind for name, kind in sync_records.SYNC_RUNS_COLUMNS.items() if name != "connected_s"}


def run_row(started_at: datetime, wall_seconds: float, connected_s: float | None) -> dict:
    """A recorded run that started at `started_at` and took `wall_seconds`."""
    row = sync_records.new_run_row("us", "replace", started_at, started_at.isoformat(), "md:market_brief")
    return {**row, "finished_at": started_at + timedelta(seconds=wall_seconds), "ok": True, "connected_s": connected_s}


def test_month_counts_connected_time_and_wall_time_of_older_rows():
    warehouse = duckdb.connect()
    warehouse.execute("CREATE SCHEMA meta")
    warehouse.execute(f"CREATE TABLE {sync_records.SYNC_RUNS} ({column_definitions(COLUMNS_BEFORE)})")
    old = run_row(NOW - timedelta(days=5), 60.0, None)
    sync_records.insert_row(warehouse, sync_records.SYNC_RUNS, COLUMNS_BEFORE, {**old, "table_rows": "{}"})
    sync_records.ensure_sync_runs_table(warehouse)
    sync_records.ensure_sync_runs_table(warehouse)  # idempotent
    names = [row[0] for row in warehouse.execute(f"DESCRIBE {sync_records.SYNC_RUNS}").fetchall()]
    assert names == list(sync_records.SYNC_RUNS_COLUMNS)
    for row in (run_row(NOW - timedelta(days=1), 60.0, 25.0), run_row(NOW - timedelta(days=40), 3600.0, 3600.0)):
        sync_records.record_sync_run(warehouse, row)
    hours = sync_records.month_hours(warehouse, NOW)
    assert abs(hours - (60.0 + 25.0) / 3600) < 1e-9  # last month's run is not counted
