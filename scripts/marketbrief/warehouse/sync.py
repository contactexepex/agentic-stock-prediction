"""One market's warehouse sync: stage every mirrored table as Parquet and build the read models (from the
repo's DuckDB, as of the run's clock), then in one transaction replace the market's mirrored tables and upsert
its read models by hash; record the run in meta.sync_runs and rm.builds and write the summary to
work/warehouse/<market>-sync.json.

Replace, not incremental: every mirrored table is rebuilt (CREATE OR REPLACE ... AS SELECT from the staged
file) because the whole market is a few tens of thousands of rows (docs/ws/ws1.md, measured costs). --full
also drops the market's schema and read-model rows first. A dry run computes the same row counts and pages and
writes nothing. The kill switch of config/warehouse.yaml (enabled, monthly_hours_ceiling) skips a sync."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from marketbrief.constants.warehouse import (
    KIND_DAILY,
    KIND_FULL,
    MARKET_PAGE_KEY,
    META_SCHEMA,
    MODE_DRY_RUN,
    MODE_FULL,
    MODE_REPLACE,
    MSG_BAD_NAME,
    MSG_DISABLED,
    MSG_INVALID_PAGE,
    MSG_OVER_CEILING,
    MSG_SYNC_FAILED,
    READ_MODEL_SCHEMA,
    READ_MODEL_TABLES,
    RM_OVERVIEW,
    SUMMARY_DIR,
    SYNC_RUNS_TABLE,
    UNKNOWN_COMMIT,
    WAREHOUSE_STEP,
)
from marketbrief.core import database, paths
from marketbrief.core.clock import clock
from marketbrief.warehouse import rm_writer
from marketbrief.warehouse.connection import (
    NAME_PATTERN,
    WarehouseError,
    connect_warehouse,
    load_warehouse_config,
    redact,
    select_target,
)
from marketbrief.warehouse.read_models import build_rows
from marketbrief.warehouse.tables import count_tables, stage_tables

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
MONTH_HOURS_SQL = f"""SELECT coalesce(sum(epoch(finished_at) - epoch(started_at)), 0) / 3600
                      FROM {META_SCHEMA}.{SYNC_RUNS_TABLE} WHERE started_at >= ?"""


@dataclass
class Staged:
    """One market's staged batch: the Parquet folder, row counts, read-model rows and the invalid pages."""

    folder: Path
    counts: dict[str, int]
    rows: dict
    invalid: list[tuple[str, str, list[str]]]


def wall_now() -> datetime:
    """The real time (UTC): when the sync ran, as opposed to the data's cut-off (MB_NOW)."""
    return datetime.now(timezone.utc)


def source_commit() -> str:
    """The git commit of the repo whose data/ the build reads, `unknown` outside a git checkout."""
    try:
        res = subprocess.run(
            ["git", "-C", str(paths.ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return UNKNOWN_COMMIT
    return res.stdout.strip() or UNKNOWN_COMMIT


def page_facts(rows: dict, invalid: list) -> dict:
    """The summary's view of the built pages: as_of, pages per table, payload bytes and invalid pages."""
    overview = rows.get(RM_OVERVIEW, {}).get(MARKET_PAGE_KEY)
    return {
        "as_of": overview["as_of"] if overview else None,
        "read_model_pages": {t: len(p) for t, p in rows.items()},
        "read_model_bytes": {t: sum(len(r["payload"].encode()) for r in p.values()) for t, p in rows.items()},
        "invalid_pages": [MSG_INVALID_PAGE.format(table=t, page_key=k, missing=", ".join(m)) for t, k, m in invalid],
    }


def ensure_meta(wh) -> None:
    """The meta.sync_runs table."""
    wh.execute(f"CREATE SCHEMA IF NOT EXISTS {META_SCHEMA}")
    columns = rm_writer.column_sql(SYNC_RUNS_COLUMNS)
    wh.execute(f"CREATE TABLE IF NOT EXISTS {META_SCHEMA}.{SYNC_RUNS_TABLE} ({columns})")


def month_hours(wh, now: datetime) -> float:
    """This UTC month's recorded sync wall time in hours (all markets)."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return float(wh.execute(MONTH_HOURS_SQL, [month_start]).fetchone()[0])


def write_market(wh, market: str, staged: Staged, full: bool) -> dict:
    """Replace the market's mirrored tables and upsert its read models in one transaction; the page counts."""
    wh.execute("BEGIN TRANSACTION")
    try:
        if full:
            wh.execute(f"DROP SCHEMA IF EXISTS {market} CASCADE")
            for table in READ_MODEL_TABLES:
                wh.execute(f"DELETE FROM {READ_MODEL_SCHEMA}.{table} WHERE market = ?", [market])
        wh.execute(f"CREATE SCHEMA IF NOT EXISTS {market}")
        for name in staged.counts:
            path = rm_writer.sql_text((staged.folder / f"{name}.parquet").as_posix())
            wh.execute(f"CREATE OR REPLACE TABLE {market}.{name} AS SELECT * FROM read_parquet({path})")
        keep = {(t, k) for t, k, _ in staged.invalid}
        stats = rm_writer.write_read_models(wh, market, staged.rows, keep, staged.folder)
        wh.execute("COMMIT")
        return stats
    except Exception:
        wh.execute("ROLLBACK")
        raise


def stage_and_write(cfg: dict, con, run: dict, target, state: dict) -> None:
    """Stage the market in a temporary folder under work/warehouse/, then write it. Fills `run` (counts) and
    `state` (timings, page facts and counts, a skip reason, and the open warehouse connection under "wh" so
    that a failed run is still recorded on it)."""
    t0 = time.monotonic()
    staging = paths.ROOT / SUMMARY_DIR
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging, prefix=f"stage-{cfg['market']}-") as folder:
        counts = stage_tables(cfg, con, run["cutoff"], Path(folder))
        cutoff_time = datetime.fromisoformat(run["cutoff"])
        rows, invalid = build_rows(cfg, con, cutoff_time, state["source_commit"], run["started_at"].isoformat())
        state.update(page_facts(rows, invalid))
        run.update(tables=list(counts), table_rows=counts, rows=sum(counts.values()))
        run["read_models"] = sum(len(pages) for pages in rows.values())
        state["stage_s"] = round(time.monotonic() - t0, 2)
        t1 = time.monotonic()
        state["wh"] = connect_warehouse(read_only=False, target=target)
        state["connect_s"] = round(time.monotonic() - t1, 2)
        ensure_meta(state["wh"])
        rm_writer.ensure_read_model_tables(state["wh"])
        hours, ceiling = month_hours(state["wh"], run["started_at"]), state["ceiling"]
        if ceiling is not None and hours >= float(ceiling):
            state["skipped"] = MSG_OVER_CEILING.format(hours=hours, ceiling=ceiling)
            return
        t2 = time.monotonic()
        staged = Staged(Path(folder), counts, rows, invalid)
        state.update(write_market(state["wh"], cfg["market"], staged, run["mode"] == MODE_FULL))
        state["write_s"] = round(time.monotonic() - t2, 2)


def record_run(wh, run: dict) -> None:
    """Append the run to meta.sync_runs."""
    values = [json.dumps(run[k]) if k == "table_rows" else run[k] for k in SYNC_RUNS_COLUMNS]
    marks = ", ".join("?" for _ in SYNC_RUNS_COLUMNS)
    wh.execute(f"INSERT INTO {META_SCHEMA}.{SYNC_RUNS_TABLE} ({', '.join(SYNC_RUNS_COLUMNS)}) VALUES ({marks})", values)


def finish(run: dict, state: dict, kind: str) -> dict:
    """Record the run in meta.sync_runs and rm.builds (when connected) and close the connection; the build row."""
    run["finished_at"] = wall_now()
    build = {
        "build_id": run["run_id"],
        "market": run["market"],
        "kind": kind,
        "cutoff": run["cutoff"],
        "source_commit": state["source_commit"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "ok": bool(run["ok"] and not state.get("invalid_pages")),
        "pages_written": state.get("pages_written", 0),
        "pages_unchanged": state.get("pages_unchanged", 0),
        "error": run["error"] or "; ".join(state.get("invalid_pages") or []) or None,
    }
    wh = state.pop("wh", None)
    if wh is None:
        return build
    try:
        record_run(wh, run)
        rm_writer.record_build(wh, build)
    except Exception as exc:  # the sync's own error, if any, stays the one reported
        run["error"] = run["error"] or redact(f"sync_runs: {type(exc).__name__}: {exc}")
        run["ok"] = build["ok"] = False
    wh.close()
    return build


def write_summary(market: str, summary: dict) -> str:
    """work/warehouse/<market>-sync.json; returns its repo-relative path."""
    folder = paths.ROOT / SUMMARY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{market}-sync.json").write_text(json.dumps(summary, indent=2, default=str))
    return f"{SUMMARY_DIR}/{market}-sync.json"


def dry_run(cfg: dict, con, cutoff_time: datetime, commit: str) -> dict:
    """The row counts and pages a sync would write; nothing is written."""
    counts = count_tables(cfg, con, cutoff_time.isoformat())
    rows, invalid = build_rows(cfg, con, cutoff_time, commit, wall_now().isoformat())
    return {"tables": counts, "rows": sum(counts.values()), **page_facts(rows, invalid), "written": False}


def new_run(market: str, mode: str, started: datetime, cutoff: str, target_label: str) -> dict:
    """The meta.sync_runs row of a run before it starts."""
    run = {c: None for c in SYNC_RUNS_COLUMNS}
    run.update(run_id=f"{market}-{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}", market=market, mode=mode)
    run.update(started_at=started, cutoff=cutoff, target=target_label, ok=False)
    run.update(tables=[], table_rows={}, rows=0, read_models=0)
    return run


def sync_market(
    cfg: dict, full: bool = False, dry_run_only: bool = False, force_local: bool = False, kind: str = KIND_DAILY
) -> dict:
    """Sync one market; returns the step summary (and raises WarehouseError, after recording it, on failure).
    A skip (kill switch) returns ok true with `skipped` set; no data is written then."""
    market = cfg["market"]
    if not NAME_PATTERN.fullmatch(market):
        raise WarehouseError(MSG_BAD_NAME.format(name=market))
    wcfg = load_warehouse_config()
    mode = MODE_DRY_RUN if dry_run_only else (MODE_FULL if full else MODE_REPLACE)
    kind = KIND_FULL if full else kind
    target = select_target(wcfg, force_local=force_local, require_token=not dry_run_only)
    cutoff_time, started, t0 = clock(), wall_now(), time.monotonic()
    summary = {"step": WAREHOUSE_STEP, "market": market, "mode": mode, "kind": kind, "target": target.label()}
    summary["cutoff"] = cutoff_time.isoformat()
    if not wcfg.get("enabled", True) and not dry_run_only:
        summary.update(ok=True, skipped=MSG_DISABLED)
        return {**summary, "summary_file": write_summary(market, summary)}
    con, commit = database.connect(market), source_commit()
    summary["source_commit"] = commit
    if dry_run_only:
        return {**summary, **dry_run(cfg, con, cutoff_time, commit), "elapsed_s": round(time.monotonic() - t0, 2)}
    run = new_run(market, mode, started, summary["cutoff"], target.label())
    state: dict = {"source_commit": commit, "ceiling": wcfg.get("monthly_hours_ceiling")}
    try:
        stage_and_write(cfg, con, run, target, state)
        run["ok"], run["error"] = not state.get("skipped"), state.get("skipped")
    except Exception as exc:  # recorded (redacted) in sync_runs, rm.builds and the summary, then raised
        run["error"] = redact(f"{type(exc).__name__}: {exc}")
    build = finish(run, state, kind)
    summary.update({k: run[k] for k in ("run_id", "ok", "error", "rows", "read_models")}, tables=run["table_rows"])
    summary.update({k: v for k, v in state.items() if k not in ("source_commit", "ceiling")})
    summary.update(build_ok=build["ok"], elapsed_s=round(time.monotonic() - t0, 2))
    if state.get("skipped"):
        summary["ok"] = True
    summary["summary_file"] = write_summary(market, summary)
    if not summary["ok"]:
        raise WarehouseError(MSG_SYNC_FAILED.format(market=market, error=run["error"]))
    return summary
