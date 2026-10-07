"""SQL text the warehouse modules share: quoted literals, column definitions and one-row inserts."""

from __future__ import annotations


def quoted(value) -> str:
    """A SQL string literal (single quotes doubled)."""
    return "'" + str(value).replace("'", "''") + "'"


def column_definitions(columns: dict[str, str]) -> str:
    """`name TYPE, ...` for CREATE TABLE."""
    return ", ".join(f"{name} {sql_type}" for name, sql_type in columns.items())


def insert_row(warehouse, table: str, columns: dict[str, str], row: dict) -> None:
    """Append one row to `table`, its values taken from `row` by column name (missing ones NULL)."""
    names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    warehouse.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", [row.get(column) for column in columns])
