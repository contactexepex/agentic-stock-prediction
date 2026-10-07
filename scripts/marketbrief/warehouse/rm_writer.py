"""Writing the read models (docs/ARCHITECTURE.md 4.4), inside the sync's transaction: per table, a page whose
payload_sha256 equals the stored one is left alone (built_at unchanged, counted unchanged), a changed or new
page replaces its row, and a stored page_key the build no longer produces (a ticker that left the watchlist)
is deleted. A page that failed validation is neither written nor deleted: its old row stays. The build itself
is appended to rm.builds."""

from __future__ import annotations

import json
from pathlib import Path

from marketbrief.constants.warehouse import BUILDS_TABLE, READ_MODEL_SCHEMA, READ_MODEL_TABLES
from marketbrief.warehouse.read_models import READ_MODEL_COLUMNS

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
STAGED_COLUMNS = {**READ_MODEL_COLUMNS, "payload": "VARCHAR"}  # cast to JSON on insert: the text stays verbatim


def column_sql(columns: dict[str, str]) -> str:
    """name TYPE, ... for CREATE TABLE."""
    return ", ".join(f"{name} {sql_type}" for name, sql_type in columns.items())


def sql_text(value: str) -> str:
    """A string literal for SQL."""
    return "'" + str(value).replace("'", "''") + "'"


def ensure_read_model_tables(wh) -> None:
    """Schema rm with one table per page type (primary key market, page_key) and rm.builds."""
    wh.execute(f"CREATE SCHEMA IF NOT EXISTS {READ_MODEL_SCHEMA}")
    for table in READ_MODEL_TABLES:
        wh.execute(
            f"CREATE TABLE IF NOT EXISTS {READ_MODEL_SCHEMA}.{table} "
            f"({column_sql(READ_MODEL_COLUMNS)}, PRIMARY KEY (market, page_key))"
        )
    wh.execute(f"CREATE TABLE IF NOT EXISTS {READ_MODEL_SCHEMA}.{BUILDS_TABLE} ({column_sql(BUILDS_COLUMNS)})")


def stored_hashes(wh, market: str) -> dict[str, dict[str, str]]:
    """table -> page_key -> payload_sha256 of the market's stored pages (one query)."""
    union = " UNION ALL ".join(
        f"SELECT '{t}' AS t, page_key, payload_sha256 FROM {READ_MODEL_SCHEMA}.{t} WHERE market = $market"
        for t in READ_MODEL_TABLES
    )
    out: dict[str, dict[str, str]] = {t: {} for t in READ_MODEL_TABLES}
    for table, page_key, sha in wh.execute(union, {"market": market}).fetchall():
        out[table][page_key] = sha
    return out


def write_read_models(wh, market: str, rows: dict, keep: set[tuple[str, str]], folder: Path) -> dict:
    """Upsert the market's pages by hash; `keep` = (table, page_key) of pages that failed validation (their
    stored rows are neither replaced nor deleted). Returns pages_written, pages_unchanged and pages_deleted."""
    stored = stored_hashes(wh, market)
    stats = {"pages_written": 0, "pages_unchanged": 0, "pages_deleted": 0}
    for table in READ_MODEL_TABLES:
        new = rows.get(table, {})
        changed = [k for k, row in new.items() if stored[table].get(k) != row["payload_sha256"]]
        gone = [k for k in stored[table] if k not in new and (table, k) not in keep]
        stats["pages_written"] += len(changed)
        stats["pages_unchanged"] += len(new) - len(changed)
        stats["pages_deleted"] += len(gone)
        name = f"{READ_MODEL_SCHEMA}.{table}"
        if changed or gone:
            wh.execute(f"DELETE FROM {name} WHERE market = ? AND list_contains(?, page_key)", [market, changed + gone])
        if changed:
            path = folder / f"rm_{table}.jsonl"
            path.write_text("".join(json.dumps(new[k], ensure_ascii=False) + "\n" for k in changed))
            columns = ", ".join("CAST(payload AS JSON)" if c == "payload" else c for c in READ_MODEL_COLUMNS)
            struct = "{" + ", ".join(f"'{c}': '{t}'" for c, t in STAGED_COLUMNS.items()) + "}"
            wh.execute(
                f"INSERT INTO {name} SELECT {columns} FROM "
                f"read_json({sql_text(path.as_posix())}, format='newline_delimited', columns={struct})"
            )
    return stats


def record_build(wh, build: dict) -> None:
    """Append the build to rm.builds."""
    marks = ", ".join("?" for _ in BUILDS_COLUMNS)
    names = ", ".join(BUILDS_COLUMNS)
    wh.execute(
        f"INSERT INTO {READ_MODEL_SCHEMA}.{BUILDS_TABLE} ({names}) VALUES ({marks})",
        [build.get(c) for c in BUILDS_COLUMNS],
    )
