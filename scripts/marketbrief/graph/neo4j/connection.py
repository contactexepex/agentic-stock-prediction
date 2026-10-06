"""Neo4j connection from the environment, the dry-run sink and statement execution."""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.parse
from pathlib import Path

from marketbrief.sources.neo4j_client import Neo4jClient


def default_database(uri: str | None) -> str:
    """NEO4J_DATABASE if set, else the first label of the URI host: on Aura the database is named
    after the instance id (neo4j+s://4132bc90.databases.neo4j.io -> 4132bc90), not `neo4j`.
    A host that is an IP address or localhost falls back to `neo4j`."""
    if os.environ.get("NEO4J_DATABASE"):
        return os.environ["NEO4J_DATABASE"]
    host = urllib.parse.urlparse(uri or "").hostname or ""
    if not host or host == "localhost" or re.fullmatch(r"[0-9.]+|[0-9a-f:]+", host) or "." not in host:
        return "neo4j"
    return host.split(".")[0]


def client_from_env() -> Neo4jClient | None:
    """The Neo4j HTTP client from the environment, or None when it is not configured."""
    uri = os.environ.get("NEO4J_URI")
    base = os.environ.get("NEO4J_QUERY_URL")
    if not uri and not base:
        return None
    if not base:
        parsed_uri = urllib.parse.urlparse(uri)
        secure = parsed_uri.scheme.endswith("+s") or parsed_uri.scheme.endswith("+ssc") or parsed_uri.scheme == "https"
        port = f":{parsed_uri.port}" if parsed_uri.port and parsed_uri.port != 7687 else ("" if secure else ":7474")
        base = f"{'https' if secure else 'http'}://{parsed_uri.hostname}{port}"
    return Neo4jClient(
        base,
        default_database(uri or base),
        (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")),
    )


class DryRunSink:
    """Writes each statement and its parameters to work/neo4j_dryrun/<market>/NNNN-<name>.json."""

    def __init__(self, out_dir: Path):
        """Write the dry-run statements into an empty output folder."""
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        self.dir, self.n = out_dir, 0

    def run(self, statement: str, parameters: dict | None = None, name: str = "statement") -> dict:
        """Save one statement and its parameters instead of sending them."""
        self.n += 1
        path = self.dir / f"{self.n:04d}-{name}.json"
        path.write_text(
            json.dumps({"statement": statement, "parameters": parameters or {}}, indent=1, ensure_ascii=False)
        )
        return {"data": {"fields": [], "values": []}, "counters": {}}


def add_counters(total: dict, res: dict) -> None:
    """Add the counters of one response to the run's totals."""
    for key, value in (res.get("counters") or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value


def run_stmt(sink, statement: str, params: dict, name: str) -> dict:
    """Run one statement on the sink (real client or dry-run files)."""
    return sink.run(statement, params, name=name) if isinstance(sink, DryRunSink) else sink.run(statement, params)
