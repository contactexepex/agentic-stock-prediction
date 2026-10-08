"""Writing the read models (docs/ARCHITECTURE.md 4.4), inside the sync's transaction: per table, a page whose
payload_sha256 equals the stored one is left alone (built_at unchanged, counted unchanged), a changed or new
page replaces its row, and a stored page_key the build no longer produces (a ticker that left the watchlist)
is deleted. A page that failed validation is neither written nor deleted: its old row stays. The build itself
is appended to rm.builds."""

from __future__ import annotations

import json
from pathlib import Path

from marketbrief.constants.warehouse import BUILDS_TABLE, READ_MODEL_SCHEMA
from marketbrief.core.database import column_spec
from marketbrief.warehouse.read_models import READ_MODEL_COLUMNS
from marketbrief.warehouse.rm_registry import tables
from marketbrief.warehouse.sql_statements import column_definitions, insert_row, quoted

BUILDS_COLUMNS = {
    "build_id": "VARCHAR",
    "market": "VARCHAR",
    "kind": "VARCHAR",
    "cutoff": "TIMESTAMPTZ",
    "source_commit": "VARCHAR",
    "started_at": "TIMESTAMPTZ",
    "finished_at": "TIMESTAMPTZ",
    "ok": "BOOLEAN",
    "pages_written": "INTEGER",
    "pages_unchanged": "INTEGER",
    "error": "VARCHAR",
}
STAGED_COLUMNS = {**READ_MODEL_COLUMNS, "payload": "VARCHAR"}


def ensure_read_model_tables(warehouse) -> None:
    """Schema rm with one table per page type (primary key market, page_key) and rm.builds."""
    warehouse.execute(f"CREATE SCHEMA IF NOT EXISTS {READ_MODEL_SCHEMA}")
    for table in tables():
        warehouse.execute(
            f"CREATE TABLE IF NOT EXISTS {READ_MODEL_SCHEMA}.{table} "
            f"({column_definitions(READ_MODEL_COLUMNS)}, PRIMARY KEY (market, page_key))"
        )
    warehouse.execute(
        f"CREATE TABLE IF NOT EXISTS {READ_MODEL_SCHEMA}.{BUILDS_TABLE} ({column_definitions(BUILDS_COLUMNS)})"
    )


def stored_hashes(warehouse, market: str) -> dict[str, dict[str, str]]:
    """table -> page_key -> payload_sha256 of the market's stored pages (one query)."""
    union = " UNION ALL ".join(
        f"SELECT '{table}' AS page_table, page_key, payload_sha256 FROM {READ_MODEL_SCHEMA}.{table} "
        "WHERE market = $market"
        for table in tables()
    )
    hashes: dict[str, dict[str, str]] = {table: {} for table in tables()}
    for table, page_key, payload_sha256 in warehouse.execute(union, {"market": market}).fetchall():
        hashes[table][page_key] = payload_sha256
    return hashes


def insert_staged_pages(warehouse, table: str, pages: list[dict], folder: Path) -> None:
    """Insert pages through a JSON-lines file (payload read as text and cast to JSON, so it stays verbatim)."""
    path = folder / f"rm_{table}.jsonl"
    path.write_text("".join(json.dumps(page, ensure_ascii=False) + "\n" for page in pages))
    selected = ", ".join("CAST(payload AS JSON)" if column == "payload" else column for column in READ_MODEL_COLUMNS)
    warehouse.execute(
        f"INSERT INTO {READ_MODEL_SCHEMA}.{table} SELECT {selected} FROM read_json({quoted(path.as_posix())}, "
        f"format='newline_delimited', columns={column_spec(STAGED_COLUMNS)})"
    )


def write_read_models(
    warehouse, market: str, rows: dict, keep: set[tuple[str, str]], folder: Path, wiped: dict | None = None
) -> dict:
    """Upsert the market's pages by hash; `keep` = (table, page_key) of pages that failed validation (their
    stored rows are neither replaced nor deleted). `wiped` = the stored hashes read before a --full rebuild deleted
    every row of the market: a page in it that is no longer built counts as deleted. Returns pages_written,
    pages_unchanged, pages_deleted and changed_keys (table, market, page_key of every written or deleted page: the
    app's cache tags to revalidate)."""
    stored = stored_hashes(warehouse, market)
    counts = {"pages_written": 0, "pages_unchanged": 0, "pages_deleted": 0, "changed_keys": []}
    for table in tables():
        built = rows.get(table, {})
        changed = [key for key, row in built.items() if stored[table].get(key) != row["payload_sha256"]]
        departed = [key for key in stored[table] if key not in built and (table, key) not in keep]
        gone = [key for key in sorted((wiped or {}).get(table, {})) if key not in built and key not in departed]
        counts["pages_deleted"] += len(gone)
        counts["changed_keys"] += [{"table": table, "market": market, "page_key": key} for key in gone]
        counts["pages_written"] += len(changed)
        counts["pages_unchanged"] += len(built) - len(changed)
        counts["pages_deleted"] += len(departed)
        counts["changed_keys"] += [{"table": table, "market": market, "page_key": key} for key in changed + departed]
        if changed or departed:
            warehouse.execute(
                f"DELETE FROM {READ_MODEL_SCHEMA}.{table} WHERE market = ? AND list_contains(?, page_key)",
                [market, changed + departed],
            )
        if changed:
            insert_staged_pages(warehouse, table, [built[key] for key in changed], folder)
    return counts


def record_build(warehouse, build: dict) -> None:
    """Append the build to rm.builds."""
    insert_row(warehouse, f"{READ_MODEL_SCHEMA}.{BUILDS_TABLE}", BUILDS_COLUMNS, build)
