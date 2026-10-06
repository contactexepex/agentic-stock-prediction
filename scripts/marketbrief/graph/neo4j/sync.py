"""Schema, watermarks, market deletion and the incremental sync of every kind."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from marketbrief.core.clock import utc_now
from marketbrief.sources.neo4j_client import Neo4jError
from marketbrief.constants.neo4j import (
    MSG_NEO4J_READ_FAILED,
    MSG_NEO4J_WATERMARK_FAILED,
    WATERMARK_STATEMENT,
    BATCH_SIZE,
    DELETE_BATCH,
    INDEXES,
    LABELS,
    OVERLAP_DAYS,
    REL_ID_TYPES,
    SCHEMA_VERSION,
)
from marketbrief.graph.neo4j.connection import DryRunSink, add_counters, run_stmt
from marketbrief.graph.neo4j.kinds import KINDS, Kind


def schema_statements() -> list[str]:
    """The constraints and indexes of the projection."""
    out = [f"CREATE CONSTRAINT {lab.lower()}_id IF NOT EXISTS FOR (n:{lab}) REQUIRE n.id IS UNIQUE" for lab in LABELS]
    out += [f"CREATE INDEX {lab.lower()}_{prop} IF NOT EXISTS FOR (n:{lab}) ON (n.{prop})" for lab, prop in INDEXES]
    out += [
        f"CREATE INDEX {relation_type.lower()}_id IF NOT EXISTS FOR ()-[r:{relation_type}]-() ON (r.id)"
        for relation_type in REL_ID_TYPES
    ]
    return out


def read_rows(kind: Kind, cfg: dict, con, since: str | None) -> list[dict]:
    """The rows of a kind (all, or since the watermark), shaped and sorted by id."""
    market = cfg["market"]
    if kind.rows_fn:
        return kind.rows_fn(cfg, con, since)
    sql, params = f"SELECT * FROM ({kind.sql}) q", []
    if kind.incremental and since:
        sql += f" WHERE q._ts IS NULL OR q._ts >= CAST(? AS TIMESTAMPTZ) - INTERVAL {OVERLAP_DAYS} DAY"
        params = [since]
    cur = con.execute(sql, params)
    cols = [column[0] for column in cur.description]
    rows = [kind.shape(market, dict(zip(cols, row))) for row in cur.fetchall()]
    return sorted(rows, key=lambda row: (str(row["id"]), str(row.get("source_id"))))


def watermarks(client, market: str) -> dict[str, str]:
    """The stored watermark of each kind of a market."""
    res = client.run(
        "MATCH (s:SyncState) WHERE s.market = $market AND s.kind IS NOT NULL "
        "RETURN s.kind AS kind, s.watermark AS watermark",
        {"market": market},
    )
    data = res.get("data") or {}
    return {key: watermark for key, watermark in (data.get("values") or []) if watermark}


def ensure_schema(sink) -> None:
    """Create the schema unless the stored schema version is current."""
    if not isinstance(sink, DryRunSink):
        res = sink.run("MATCH (s:SyncState {id: $id}) RETURN s.version AS version", {"id": "_schema"})
        values = (res.get("data") or {}).get("values") or []
        if values and values[0] and values[0][0] == SCHEMA_VERSION:
            return
    for stmt in schema_statements():
        run_stmt(sink, stmt, {}, "schema")
    run_stmt(
        sink,
        "MERGE (s:SyncState {id: $id}) SET s.version = $version",
        {"id": "_schema", "version": SCHEMA_VERSION},
        "schema",
    )


def delete_market(sink, market: str) -> int:
    """Delete every node of the market in batches; return how many were deleted."""
    stmt = "MATCH (n) WHERE n.market = $market WITH n LIMIT $limit DETACH DELETE n RETURN count(*) AS deleted"
    total = 0
    while True:
        res = run_stmt(sink, stmt, {"market": market, "limit": DELETE_BATCH}, "full-delete")
        values = (res.get("data") or {}).get("values") or []
        deleted = int(values[0][0]) if values and values[0] else 0
        total += deleted
        if deleted < DELETE_BATCH:
            return total


@dataclass
class SyncRun:
    """What one sync run shares across its kinds: market, config, connection, sink and counters."""

    cfg: dict
    con: object
    sink: object
    batch_size: int
    synced_at: str
    counters: dict = field(default_factory=dict)

    @property
    def market(self) -> str:
        """The market being synced."""
        return self.cfg["market"]

    @property
    def dry(self) -> bool:
        """True when the sink only writes the statements to files."""
        return isinstance(self.sink, DryRunSink)


def upsert_batches(run: SyncRun, kind: Kind, rows: list[dict], record: dict) -> list[str]:
    """Run the kind's statements over the rows in batches; count upserted and failed rows, return the errors."""
    errors = []
    for index in range(0, len(rows), run.batch_size):
        batch, batch_ok = rows[index : index + run.batch_size], True
        for inner_index, (stmt, keep) in enumerate(kind.statements):
            part = [row for row in batch if keep is None or keep(row)]
            if not part:
                continue
            params = {"market": run.market, "kind": kind.name, "synced_at": run.synced_at, "rows": part}
            name = f"{kind.name}-{inner_index}-b{index // run.batch_size}"
            try:
                add_counters(run.counters, run_stmt(run.sink, stmt, params, name))
            except Neo4jError as exc:
                batch_ok = False
                errors.append(str(exc))
        record["upserted" if batch_ok else "failed"] += len(batch)
    return errors


def store_watermark(run: SyncRun, kind: Kind, rows: list[dict], record: dict) -> None:
    """Remember the newest recorded_at of the synced rows as the kind's watermark in Neo4j."""
    marks_ts = [row["recorded_at"] for row in rows if row.get("recorded_at")]
    if not marks_ts:
        return
    newest = max(marks_ts, key=lambda timestamp: datetime.fromisoformat(timestamp))
    params = {
        "id": f"{run.market}:{kind.name}",
        "market": run.market,
        "kind": kind.name,
        "watermark": newest,
        "n": len(rows),
        "synced_at": run.synced_at,
    }
    try:
        run.sink.run(WATERMARK_STATEMENT, params)
        record["watermark"] = newest
    except Neo4jError as exc:
        record["error"] = MSG_NEO4J_WATERMARK_FAILED.format(error=exc)[:300]
        record["failed"] += 1


def sync_kind(run: SyncRun, kind: Kind, start: str | None) -> dict:
    """Read, upsert and mark the watermark of one kind; return its record (rows read, upserted, failed)."""
    record = {"rows_read": 0, "upserted": 0, "failed": 0}
    if kind.incremental and start:
        record["since"] = start
    try:
        rows = read_rows(kind, run.cfg, run.con, start if kind.incremental else None)
    except Exception as exc:  # a view that cannot be read fails this kind only
        record.update(error=MSG_NEO4J_READ_FAILED.format(error=exc)[:300])
        record["failed"] = 1
        return record
    record["rows_read"] = len(rows)
    errors = upsert_batches(run, kind, rows, record)
    if errors:
        record["error"] = errors[0][:300]
    elif kind.incremental and rows and not run.dry:
        store_watermark(run, kind, rows, record)
    return record


def sync(  # noqa: PLR0913  (the public options: config, connection, sink, full, since, batch size, kinds)
    cfg: dict,
    con,
    sink,
    full: bool = False,
    since: str | None = None,
    batch_size: int = BATCH_SIZE,
    only: list[str] | None = None,
) -> dict:
    """Project the market's data into Neo4j (or the dry-run sink): schema, optional full delete, every kind."""
    run = SyncRun(cfg, con, sink, batch_size, utc_now())
    out = {
        "step": "neo4j_sync",
        "market": run.market,
        "mode": "full" if full else "incremental",
        "dry_run": run.dry,
        "host": None if run.dry else sink.host,
        "database": None if run.dry else sink.database,
        "synced_at": run.synced_at,
        "kinds": {},
        "counters": run.counters,
    }
    try:
        ensure_schema(sink)
        if full:
            out["deleted_nodes"] = delete_market(sink, run.market)
        marks = {} if (full or run.dry) else watermarks(sink, run.market)
    except Neo4jError as exc:
        out.update(ok=False, error=str(exc))
        return out
    for kind in KINDS:
        if only and kind.name not in only:
            continue
        start = None if full else (since or marks.get(kind.name))
        out["kinds"][kind.name] = sync_kind(run, kind, start)
    out["ok"] = all(not record["failed"] for record in out["kinds"].values())
    return out
