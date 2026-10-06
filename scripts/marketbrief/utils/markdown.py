"""Markdown table builders."""

from __future__ import annotations

NO_ROWS_MARKDOWN = "_none_\n"


def markdown_table(header: list[str], rows: list[list]) -> str:
    """A markdown table of already-formatted rows; '_none_' when there are no rows."""
    if not rows:
        return NO_ROWS_MARKDOWN
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def cursor_markdown_table(cursor) -> str:
    """A markdown table of a DuckDB cursor's rows (None shown empty); '_none_' when there are none."""
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return NO_ROWS_MARKDOWN
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out) + "\n"
