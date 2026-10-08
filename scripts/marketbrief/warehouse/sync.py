"""One market's warehouse sync: stage every mirrored table as Parquet and build the read models (from the
repo's DuckDB, as of the run's clock), then in one transaction replace the market's mirrored tables and upsert
its read models by hash; record the run in meta.sync_runs and rm.builds and write the summary to
work/warehouse/<market>-sync.json.

Replace, not incremental: every mirrored table is rebuilt (CREATE OR REPLACE ... AS SELECT from the staged
file) because the whole market is a few tens of thousands of rows (docs/ws/ws1.md, measured costs). --full
also drops the market's schema and read-model rows first. A dry run computes the same row counts and pages and
writes nothing. The kill switch of config/warehouse.yaml (enabled, monthly_hours_ceiling) skips a sync."""

from __future__ import annotations

import tempfile
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from marketbrief.constants.warehouse import (
    KIND_DAILY,
    KIND_FULL,
    MODE_DRY_RUN,
    MODE_FULL,
    MODE_REPLACE,
    MSG_BAD_NAME,
    MSG_DISABLED,
    MSG_OVER_CEILING,
    MSG_REVALIDATE_LOCAL,
    PROVIDER_MOTHERDUCK,
    MSG_SYNC_FAILED,
    READ_MODEL_SCHEMA,
    SUMMARY_DIR,
    WAREHOUSE_STEP,
)
from marketbrief.core import database, paths
from marketbrief.core.clock import clock
from marketbrief.warehouse import rm_writer
from marketbrief.warehouse.connection import (
    NAME_PATTERN,
    Target,
    connect_warehouse,
    load_warehouse_config,
    select_target,
)
from marketbrief.warehouse.errors import WarehouseError, redact
from marketbrief.warehouse.read_models import build_rows
from marketbrief.warehouse.revalidate import revalidate
from marketbrief.warehouse.rm_registry import tables
from marketbrief.warehouse.sql_statements import quoted
from marketbrief.warehouse.sync_records import (
    build_row,
    ensure_sync_runs_table,
    month_hours,
    new_run_row,
    page_facts,
    record_sync_run,
    source_commit,
    wall_now,
    write_summary,
)
from marketbrief.warehouse.tables import count_tables, stage_tables


@dataclass
class Staged:
    """One market's staged batch: the Parquet folder, row counts, read-model rows and the invalid pages."""

    folder: Path
    counts: dict[str, int]
    rows: dict
    invalid: list[tuple[str, str, list[str]]]


class PhaseTimer:
    """Seconds spent in each named phase of a run that completed (`<phase>_s`, rounded to 0.01 s)."""

    def __init__(self):
        """No phase timed yet."""
        self.seconds: dict[str, float] = {}

    @contextmanager
    def phase(self, name: str):
        """Time the block as phase `name`; a block that raises is not recorded."""
        started = time.monotonic()
        yield
        self.seconds[f"{name}_s"] = round(time.monotonic() - started, 2)


def write_market(warehouse, market: str, staged: Staged, full: bool) -> dict:
    """Replace the market's mirrored tables and upsert its read models in one transaction; the page counts."""
    warehouse.execute("BEGIN TRANSACTION")
    try:
        if full:
            warehouse.execute(f"DROP SCHEMA IF EXISTS {market} CASCADE")
            for table in tables():
                warehouse.execute(f"DELETE FROM {READ_MODEL_SCHEMA}.{table} WHERE market = ?", [market])
        warehouse.execute(f"CREATE SCHEMA IF NOT EXISTS {market}")
        for name in staged.counts:
            path = quoted((staged.folder / f"{name}.parquet").as_posix())
            warehouse.execute(f"CREATE OR REPLACE TABLE {market}.{name} AS SELECT * FROM read_parquet({path})")
        keep = {(table, page_key) for table, page_key, _missing in staged.invalid}
        page_counts = rm_writer.write_read_models(warehouse, market, staged.rows, keep, staged.folder)
        warehouse.execute("COMMIT")
        return page_counts
    except Exception:
        with suppress(duckdb.Error):  # a failed ROLLBACK must not hide the error that caused it
            warehouse.execute("ROLLBACK")
        raise


class SyncRun:
    """One writing sync of a market: stage it locally, connect, check the monthly ceiling, write, record."""

    def __init__(self, cfg: dict, warehouse_cfg: dict, mode: str, kind: str, target: Target, clocks: tuple):
        """A run that has not started: its sync_runs row, no connection, nothing counted. `clocks` is
        (cutoff_time, started_at): the data's cut-off and the wall time the sync started, before any work."""
        cutoff_time, started_at = clocks
        self.cfg, self.market, self.kind, self.target = cfg, cfg["market"], kind, target
        self.full = mode == MODE_FULL
        self.ceiling = warehouse_cfg.get("monthly_hours_ceiling")
        self.cutoff_time = cutoff_time
        self.commit = source_commit()
        self.row = new_run_row(self.market, mode, started_at, cutoff_time.isoformat(), target.label())
        self.timer = PhaseTimer()
        self.warehouse = None
        self.facts: dict = {}
        self.page_counts: dict = {}
        self.skipped: str | None = None
        self.app_url = warehouse_cfg.get("app_url")
        self.changed_keys: list[dict] = []
        self.revalidated: str | None = None

    def stage(self, con, folder: Path) -> Staged:
        """Write the mirrored tables as Parquet and build the pages; counts go into the run's row."""
        with self.timer.phase("stage"):
            counts = stage_tables(self.cfg, con, self.row["cutoff"], folder)
            built_at = self.row["started_at"].isoformat()
            rows, invalid = build_rows(self.cfg, con, self.cutoff_time, self.commit, built_at)
        self.facts = page_facts(rows, invalid)
        self.row.update(tables=list(counts), table_rows=counts, rows=sum(counts.values()))
        self.row["read_models"] = sum(len(pages) for pages in rows.values())
        return Staged(folder, counts, rows, invalid)

    def connect(self) -> None:
        """Open the warehouse for writing and make sure the bookkeeping and read-model tables exist."""
        with self.timer.phase("connect"):
            self.warehouse = connect_warehouse(read_only=False, target=self.target)
        ensure_sync_runs_table(self.warehouse)
        rm_writer.ensure_read_model_tables(self.warehouse)

    def over_ceiling(self) -> str | None:
        """The skip reason when this month's recorded sync time has reached the ceiling, else None."""
        if self.ceiling is None:
            return None
        hours = month_hours(self.warehouse, self.row["started_at"])
        return MSG_OVER_CEILING.format(hours=hours, ceiling=self.ceiling) if hours >= float(self.ceiling) else None

    def revalidate(self) -> str:
        """After the commit: invalidate the app's cache of the changed pages (MotherDuck only; non-blocking)."""
        if self.target.kind != PROVIDER_MOTHERDUCK or not self.app_url:
            return MSG_REVALIDATE_LOCAL
        return revalidate(self.app_url, self.row["run_id"], self.changed_keys)

    def run(self, con) -> None:
        """Stage, connect and write (unless over the ceiling). A failure becomes the run's redacted error."""
        staging = paths.ROOT / SUMMARY_DIR
        staging.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=staging, prefix=f"stage-{self.market}-") as folder:
                staged = self.stage(con, Path(folder))
                self.connect()
                self.skipped = self.over_ceiling()
                if not self.skipped:
                    with self.timer.phase("write"):
                        self.page_counts = write_market(self.warehouse, self.market, staged, self.full)
                    self.changed_keys = self.page_counts.pop("changed_keys", [])
                    self.revalidated = self.revalidate()
            self.row["ok"], self.row["error"] = not self.skipped, self.skipped
        except Exception as exc:  # recorded in sync_runs, rm.builds and the summary; sync_market raises it
            self.row["error"] = redact(f"{type(exc).__name__}: {exc}")

    def record(self) -> dict:
        """Record the run in meta.sync_runs and rm.builds (when connected), close the connection; the build row."""
        self.row["finished_at"] = wall_now()
        build = build_row(self.row, self.kind, self.commit, self.page_counts, self.facts.get("invalid_pages", []))
        if self.warehouse is None:
            return build
        try:
            record_sync_run(self.warehouse, self.row)
            rm_writer.record_build(self.warehouse, build)
        except Exception as exc:  # the sync's own error, if any, stays the one reported
            self.row["error"] = self.row["error"] or redact(f"sync_runs: {type(exc).__name__}: {exc}")
            self.row["ok"] = build["ok"] = False
        self.warehouse.close()
        return build

    def summary_fields(self, build: dict) -> dict:
        """The run's part of the step summary, in the order the steps happen; a ceiling skip counts as ok."""
        fields = {key: self.row[key] for key in ("run_id", "ok", "error", "rows", "read_models")}
        fields.update(tables=self.row["table_rows"], **self.facts)
        fields.update({key: self.timer.seconds[key] for key in ("stage_s", "connect_s") if key in self.timer.seconds})
        if self.skipped:
            fields["skipped"] = self.skipped
        fields.update(self.page_counts)
        if "write_s" in self.timer.seconds:
            fields["write_s"] = self.timer.seconds["write_s"]
        if self.revalidated is not None:
            fields["revalidate"] = self.revalidated
        fields["build_ok"] = build["ok"]
        if self.skipped:
            fields["ok"] = True
        return fields


def dry_run(cfg: dict, con, cutoff_time: datetime, commit: str) -> dict:
    """The row counts and pages a sync would write; nothing is written."""
    counts = count_tables(cfg, con, cutoff_time.isoformat())
    rows, invalid = build_rows(cfg, con, cutoff_time, commit, wall_now().isoformat())
    return {"tables": counts, "rows": sum(counts.values()), **page_facts(rows, invalid), "written": False}


def sync_market(
    cfg: dict, full: bool = False, dry_run_only: bool = False, force_local: bool = False, kind: str = KIND_DAILY
) -> dict:
    """Sync one market; returns the step summary (and raises WarehouseError, after recording it, on failure).
    A skip (kill switch) returns ok true with `skipped` set; no data is written then."""
    market = cfg["market"]
    if not NAME_PATTERN.fullmatch(market):
        raise WarehouseError(MSG_BAD_NAME.format(name=market))
    warehouse_cfg = load_warehouse_config()
    mode = MODE_DRY_RUN if dry_run_only else (MODE_FULL if full else MODE_REPLACE)
    kind = KIND_FULL if full else kind
    target = select_target(warehouse_cfg, force_local=force_local, require_token=not dry_run_only)
    cutoff_time, started_at, run_started = clock(), wall_now(), time.monotonic()
    summary = {"step": WAREHOUSE_STEP, "market": market, "mode": mode, "kind": kind, "target": target.label()}
    summary["cutoff"] = cutoff_time.isoformat()
    if not warehouse_cfg.get("enabled", True) and not dry_run_only:
        summary.update(ok=True, skipped=MSG_DISABLED)
        return {**summary, "summary_file": write_summary(market, summary)}
    con = database.connect(market)
    if dry_run_only:
        commit = source_commit()
        planned = dry_run(cfg, con, cutoff_time, commit)
        return {**summary, "source_commit": commit, **planned, "elapsed_s": round(time.monotonic() - run_started, 2)}
    sync_run = SyncRun(cfg, warehouse_cfg, mode, kind, target, (cutoff_time, started_at))
    sync_run.run(con)
    build = sync_run.record()
    summary.update(source_commit=sync_run.commit, **sync_run.summary_fields(build))
    summary["elapsed_s"] = round(time.monotonic() - run_started, 2)
    summary["summary_file"] = write_summary(market, summary)
    if not summary["ok"]:
        raise WarehouseError(MSG_SYNC_FAILED.format(market=market, error=sync_run.row["error"]))
    return summary
