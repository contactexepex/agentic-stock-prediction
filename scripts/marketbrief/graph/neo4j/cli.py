"""Project one market's data and results into Neo4j (docs/DESIGN.md section 12).

The repo's append-only files under data/ stay the source of truth. Neo4j is a derived copy that
`--full` rebuilds from them at any time, so nothing is lost if the database is emptied. The script
only reads data/ (through the DuckDB views in core.database.connect) and never writes there.

  neo4j_sync.py --market us              incremental: rows recorded since the last sync (minus a
                                         3-day overlap), per kind
  neo4j_sync.py --market us --full       delete this market's nodes in Neo4j, then load everything
  neo4j_sync.py --market us --dry-run    write the Cypher and parameter batches to
                                         work/neo4j_dryrun/<market>/ instead of sending them
  neo4j_sync.py --market us --probe      run `RETURN 1` and report the result

Connection (environment): NEO4J_URI (neo4j+s://<id>.databases.neo4j.io; only the host is used),
NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE (default: the first label of the URI host, which is
the database name on Aura, e.g. 4132bc90; `neo4j` for localhost or an IP address). Statements go
to the HTTPS Query API v2 (POST https://<host>/db/<database>/query/v2, basic auth), not Bolt. NEO4J_QUERY_URL replaces
the base URL derived from NEO4J_URI (e.g. http://127.0.0.1:7474 for a local server or a test).
The password and the URI are never printed; the summary names the host only.

Every statement is static Cypher: values travel only as parameters (`UNWIND $rows AS row`), and
every write is a MERGE on an id, so a re-run changes nothing. Each node and relationship carries
`market`, `source_kind` (the data kind), `source_id` (the record id in the JSONL line),
`recorded_at` (the record's own timestamp) and `synced_at`. Incremental watermarks are stored
in Neo4j itself as (:SyncState {id: '<market>:<kind>'}) nodes, so they survive a fresh container,
and advance only after every batch of a kind succeeded.

Prints one JSON summary (rows read, upserted and failed per kind). Exit 0 = all synced,
1 = any failure, 2 = NEO4J_URI not set (nothing sent)."""

from __future__ import annotations

import json

from marketbrief.constants.neo4j import BATCH_SIZE, MSG_PROBE_NEEDS_A_SERVER_NOT_DRY
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.database import connect
from marketbrief.graph.neo4j.connection import DryRunSink, client_from_env
from marketbrief.graph.neo4j.sync import sync
from marketbrief.sources.neo4j_client import Neo4jError


def main() -> int:
    """Sync one market into Neo4j (or write the dry-run statements) and print the summary."""
    parser = market_arg(__doc__)
    parser.add_argument("--full", action="store_true", help="delete this market's projection and load everything")
    parser.add_argument("--dry-run", action="store_true", help="write statements to work/neo4j_dryrun/ instead")
    parser.add_argument("--probe", action="store_true", help="only run RETURN 1 against the server")
    parser.add_argument("--since", help="ISO timestamp: override the stored watermark of every incremental kind")
    parser.add_argument("--kinds", help="comma-separated subset of kinds (default: all)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    cfg = require_market(args)
    if args.dry_run:
        sink = DryRunSink(paths.ROOT / "work" / "neo4j_dryrun" / cfg["market"])
    else:
        sink = client_from_env()
        if sink is None:
            print(
                json.dumps(
                    {
                        "step": "neo4j_sync",
                        "market": cfg["market"],
                        "ok": False,
                        "skipped": True,
                        "reason": "NEO4J_URI not set",
                    }
                )
            )
            return 2
    if args.probe:
        if isinstance(sink, DryRunSink):
            raise SystemExit(MSG_PROBE_NEEDS_A_SERVER_NOT_DRY)
        try:
            res = sink.run("RETURN 1 AS ok")
            print(
                json.dumps(
                    {
                        "step": "neo4j_probe",
                        "host": sink.host,
                        "database": sink.database,
                        "ok": True,
                        "result": (res.get("data") or {}).get("values"),
                    }
                )
            )
            return 0
        except Neo4jError as exc:
            print(
                json.dumps(
                    {
                        "step": "neo4j_probe",
                        "host": sink.host,
                        "database": sink.database,
                        "ok": False,
                        "error": str(exc),
                    }
                )
            )
            return 1
    con = connect(cfg["market"])
    only = [key.strip() for key in args.kinds.split(",")] if args.kinds else None
    out = sync(cfg, con, sink, full=args.full, since=args.since, batch_size=args.batch_size, only=only)
    if args.dry_run:
        out["dry_run_dir"] = (
            str(sink.dir.relative_to(paths.ROOT)) if sink.dir.is_relative_to(paths.ROOT) else str(sink.dir)
        )
        out["statements"] = sink.n
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1
