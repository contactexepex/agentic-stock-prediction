"""DuckDB query rows as dicts, shared by the EOD analyst's and the research director's facts."""
from __future__ import annotations


def records(con, sql: str, params: list) -> list[dict]:
    """Rows as dicts (DuckDB types: dates, timestamps, lists)."""
    cursor = con.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
