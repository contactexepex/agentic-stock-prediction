"""Shared paths, schemas and DuckDB setup for the market-brief pipeline.

Raw data lives in append-only, date-partitioned files under data/<kind>/YYYY/MM/.
DuckDB reads those files directly, so any time window is just a SQL query.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

CODE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("MB_ROOT", CODE))
DATA = ROOT / "data"
CONFIG = Path(os.environ.get("MB_CONFIG", CODE / "config"))

# kind -> (file extension, column types). This is the single source of truth for schemas.
SCHEMAS: dict[str, tuple[str, dict[str, str]]] = {
    "news": ("jsonl", {
        "id": "VARCHAR", "title": "VARCHAR", "url": "VARCHAR", "source": "VARCHAR",
        "published_at": "TIMESTAMPTZ", "first_seen_at": "TIMESTAMPTZ",
        "feed": "VARCHAR", "category": "VARCHAR", "tickers": "VARCHAR[]",
    }),
    "news_enriched": ("jsonl", {
        "id": "VARCHAR", "analyzed_at": "TIMESTAMPTZ", "relevance": "DOUBLE",
        "sentiment": "DOUBLE", "materiality": "VARCHAR", "summary": "VARCHAR",
        "prompt_version": "VARCHAR",
    }),
    "filings": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "cik": "VARCHAR", "form": "VARCHAR",
        "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ", "description": "VARCHAR",
        "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "predictions": ("jsonl", {
        "id": "VARCHAR", "made_at": "TIMESTAMPTZ", "as_of_date": "DATE", "ticker": "VARCHAR",
        "horizon_days": "INTEGER", "direction": "VARCHAR", "confidence": "DOUBLE",
        "rationale": "VARCHAR", "evidence_ids": "VARCHAR[]", "prompt_version": "VARCHAR",
    }),
    "outcomes": ("jsonl", {
        "prediction_id": "VARCHAR", "scored_at": "TIMESTAMPTZ", "base_date": "DATE",
        "base_close": "DOUBLE", "target_date": "DATE", "target_close": "DOUBLE",
        "actual_return": "DOUBLE", "hit": "BOOLEAN",
    }),
    "prices": ("csv", {
        "date": "DATE", "ticker": "VARCHAR", "open": "DOUBLE", "high": "DOUBLE",
        "low": "DOUBLE", "close": "DOUBLE", "adj_close": "DOUBLE", "volume": "BIGINT",
        "collected_at": "TIMESTAMPTZ",
    }),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def day_file(kind: str, day: date, ext: str | None = None) -> Path:
    ext = ext or SCHEMAS[kind][0]
    path = DATA / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, rows) -> int:
    """Append rows; never rewrites existing lines."""
    rows = list(rows)
    if rows:
        with path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def recent_ids(kind: str, days: int, key: str = "id") -> set[str]:
    """Ids seen in the last `days` daily files of a kind (for de-duplication)."""
    ids: set[str] = set()
    files = sorted((DATA / kind).glob("**/*.jsonl"))[-days:]
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)[key])
    return ids


def connect() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with one view per data kind plus the derived views in sql/views.sql."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for name, (ext, cols) in SCHEMAS.items():
        has_files = any((DATA / name).glob(f"**/*.{ext}"))
        col_spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"
        if has_files:
            pattern = (DATA / name).as_posix() + f"/**/*.{ext}"
            if ext == "jsonl":
                src = f"read_json('{pattern}', format='newline_delimited', columns={col_spec})"
            else:
                src = f"read_csv('{pattern}', header=true, columns={col_spec})"
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM {src}")
        else:
            con.execute(f"CREATE TABLE {name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
    con.execute((CODE / "sql" / "views.sql").read_text())
    return con


def md_table(cursor) -> str:
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out) + "\n"
