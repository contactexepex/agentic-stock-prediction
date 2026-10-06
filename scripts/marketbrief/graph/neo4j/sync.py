"""Schema, watermarks, market deletion and the incremental sync of every kind."""
from __future__ import annotations

from datetime import datetime
from marketbrief.core.clock import utc_now
from marketbrief.sources.neo4j_client import Neo4jError
from marketbrief.constants.neo4j import BATCH_SIZE, DELETE_BATCH, INDEXES, LABELS, OVERLAP_DAYS, REL_ID_TYPES, SCHEMA_VERSION
from marketbrief.graph.neo4j.connection import DryRunSink, add_counters, run_stmt
from marketbrief.graph.neo4j.kinds import KINDS, Kind


def schema_statements() -> list[str]:
    out = [f"CREATE CONSTRAINT {lab.lower()}_id IF NOT EXISTS FOR (n:{lab}) REQUIRE n.id IS UNIQUE" for lab in LABELS]
    out += [f"CREATE INDEX {lab.lower()}_{prop} IF NOT EXISTS FOR (n:{lab}) ON (n.{prop})" for lab, prop in INDEXES]
    out += [f"CREATE INDEX {t.lower()}_id IF NOT EXISTS FOR ()-[r:{t}]-() ON (r.id)" for t in REL_ID_TYPES]
    return out


def read_rows(kind: Kind, cfg: dict, con, since: str | None) -> list[dict]:
    m = cfg["market"]
    if kind.rows_fn:
        return kind.rows_fn(cfg, con, since)
    sql, params = f"SELECT * FROM ({kind.sql}) q", []
    if kind.incremental and since:
        sql += f" WHERE q._ts IS NULL OR q._ts >= CAST(? AS TIMESTAMPTZ) - INTERVAL {OVERLAP_DAYS} DAY"
        params = [since]
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [kind.shape(m, dict(zip(cols, r))) for r in cur.fetchall()]
    return sorted(rows, key=lambda r: (str(r["id"]), str(r.get("source_id"))))


def watermarks(client, market: str) -> dict[str, str]:
    res = client.run("MATCH (s:SyncState) WHERE s.market = $market AND s.kind IS NOT NULL "
                     "RETURN s.kind AS kind, s.watermark AS watermark", {"market": market})
    data = res.get("data") or {}
    return {k: w for k, w in (data.get("values") or []) if w}


def ensure_schema(sink) -> None:
    if not isinstance(sink, DryRunSink):
        res = sink.run("MATCH (s:SyncState {id: $id}) RETURN s.version AS version", {"id": "_schema"})
        values = (res.get("data") or {}).get("values") or []
        if values and values[0] and values[0][0] == SCHEMA_VERSION:
            return
    for stmt in schema_statements():
        run_stmt(sink, stmt, {}, "schema")
    run_stmt(sink, "MERGE (s:SyncState {id: $id}) SET s.version = $version", {"id": "_schema", "version": SCHEMA_VERSION},
             "schema")


def delete_market(sink, market: str) -> int:
    stmt = ("MATCH (n) WHERE n.market = $market WITH n LIMIT $limit DETACH DELETE n RETURN count(*) AS deleted")
    total = 0
    while True:
        res = run_stmt(sink, stmt, {"market": market, "limit": DELETE_BATCH}, "full-delete")
        values = (res.get("data") or {}).get("values") or []
        n = int(values[0][0]) if values and values[0] else 0
        total += n
        if n < DELETE_BATCH:
            return total


def sync(cfg: dict, con, sink, full: bool = False, since: str | None = None, batch_size: int = BATCH_SIZE,
         only: list[str] | None = None) -> dict:
    market, synced_at = cfg["market"], utc_now()
    dry = isinstance(sink, DryRunSink)
    out = {"step": "neo4j_sync", "market": market, "mode": "full" if full else "incremental", "dry_run": dry,
           "host": None if dry else sink.host,
           "database": None if dry else sink.database, "synced_at": synced_at, "kinds": {}, "counters": {}}
    try:
        ensure_schema(sink)
        if full:
            out["deleted_nodes"] = delete_market(sink, market)
        marks = {} if (full or dry) else watermarks(sink, market)
    except Neo4jError as exc:
        out.update(ok=False, error=str(exc))
        return out
    for kind in KINDS:
        if only and kind.name not in only:
            continue
        start = None if full else (since or marks.get(kind.name))
        rec = {"rows_read": 0, "upserted": 0, "failed": 0}
        if kind.incremental and start:
            rec["since"] = start
        try:
            rows = read_rows(kind, cfg, con, start if kind.incremental else None)
        except Exception as exc:  # a view that cannot be read fails this kind only
            rec.update(error=f"read: {exc}"[:300])
            rec["failed"] = 1
            out["kinds"][kind.name] = rec
            continue
        rec["rows_read"] = len(rows)
        errors = []
        for i in range(0, len(rows), batch_size):
            batch, ok = rows[i:i + batch_size], True
            for j, (stmt, keep) in enumerate(kind.statements):
                part = [r for r in batch if keep is None or keep(r)]
                if not part:
                    continue
                params = {"market": market, "kind": kind.name, "synced_at": synced_at, "rows": part}
                try:
                    add_counters(out["counters"], run_stmt(sink, stmt, params, f"{kind.name}-{j}-b{i // batch_size}"))
                except Neo4jError as exc:
                    ok = False
                    errors.append(str(exc))
            rec["upserted" if ok else "failed"] += len(batch)
        if errors:
            rec["error"] = errors[0][:300]
        elif kind.incremental and rows and not dry:
            marks_ts = [r["recorded_at"] for r in rows if r.get("recorded_at")]
            if marks_ts:
                wm = max(marks_ts, key=lambda s: datetime.fromisoformat(s))
                try:
                    sink.run("MERGE (s:SyncState {id: $id}) SET s.market = $market, s.kind = $kind, "
                             "s.watermark = $watermark, s.rows = $n, s.synced_at = datetime($synced_at)",
                             {"id": f"{market}:{kind.name}", "market": market, "kind": kind.name, "watermark": wm,
                              "n": len(rows), "synced_at": synced_at})
                    rec["watermark"] = wm
                except Neo4jError as exc:
                    rec["error"] = f"watermark: {exc}"[:300]
                    rec["failed"] += 1
        out["kinds"][kind.name] = rec
    out["ok"] = all(not k["failed"] for k in out["kinds"].values())
    return out
