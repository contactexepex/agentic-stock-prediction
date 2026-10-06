"""The DuckDB connection: one view per data kind over the stored files, plus the derived views."""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

from marketbrief.constants.columns import COL_ACCEPTED_AT, COL_ACCESSION, COL_CHECKED_AT
from marketbrief.constants.environment import ENV_NOW
from marketbrief.constants.files import DIR_SQL, FILE_VIEWS_SQL, JSONL_GLOB
from marketbrief.constants.kinds import FILE_FORMAT_JSONL, KIND_NEWS, KIND_SEC_TIMES, NEWS_STORED_VIEW
from marketbrief.core import paths
from marketbrief.core.clock import FrozenClockConnection, clock
from marketbrief.core.market_config import load_market
from marketbrief.core.schemas import ACCEPTED_KEYS, SCHEMAS

NEWS_RETAG_ARGUMENT_TYPES = ["VARCHAR", "VARCHAR", "VARCHAR[]", "VARCHAR[]", "VARCHAR[]", "VARCHAR", "INTEGER"]


def column_spec(columns: dict[str, str]) -> str:
    """DuckDB's `columns=` struct literal for a schema's column types."""
    return "{" + ", ".join(f"'{name}': '{sql_type}'" for name, sql_type in columns.items()) + "}"


def kind_source_sql(base: Path, kind: str, file_format: str, columns: dict[str, str]) -> str:
    """The read_json / read_csv expression over every stored file of a kind."""
    pattern = (base / kind).as_posix() + f"/**/*.{file_format}"
    if file_format == FILE_FORMAT_JSONL:
        return f"read_json('{pattern}', format='newline_delimited', columns={column_spec(columns)})"
    return f"read_csv('{pattern}', header=true, columns={column_spec(columns)})"


def corrected_accepted_at_view_sql(base: Path, name: str, source_sql: str) -> str:
    """A view of a SEC kind whose accepted_at is the SGML header's time where one was checked (sec_times)."""
    times_pattern = (base / KIND_SEC_TIMES).as_posix() + "/" + JSONL_GLOB
    times_columns = column_spec(SCHEMAS[KIND_SEC_TIMES][1])
    latest_check = (f"(SELECT DISTINCT ON ({COL_ACCESSION}) {COL_ACCESSION} AS _acc, {COL_ACCEPTED_AT} AS _true FROM "
                    f"read_json('{times_pattern}', format='newline_delimited', columns={times_columns}) "
                    f"WHERE {COL_ACCEPTED_AT} IS NOT NULL ORDER BY {COL_ACCESSION}, {COL_CHECKED_AT} DESC)")
    return (f"CREATE VIEW {name} AS SELECT s.* REPLACE (coalesce(f._true, s.{COL_ACCEPTED_AT}) AS {COL_ACCEPTED_AT}) "
            f"FROM {source_sql} s LEFT JOIN {latest_check} f ON f._acc = s.{ACCEPTED_KEYS[name]}")


def unretagged_news_function(_feed, _title, tickers, primary, mentioned, confidence,  # noqa: PLR0913
                             _tag_version):
    """Stand-in for the news re-tagger when there is no market config: tags stay as stored.
    DuckDB checks the seven parameters against NEWS_RETAG_ARGUMENT_TYPES."""
    return {"tickers": list(tickers or []), "primary_tickers": list(primary or []),
            "mentioned_tickers": list(mentioned or []), "tag_confidence": confidence}


def register_news_retag(con: duckdb.DuckDBPyConnection, market: str) -> None:
    """Register `news_retag`, which the `news` view uses to re-tag rows from before the current tagger."""
    from news_tags import RETAG_TYPE, Tagger
    try:
        retag = Tagger(load_market(market)).retag_stored
    except SystemExit:   # no market config (some tests): tags stay as stored
        retag = unretagged_news_function
    con.create_function("news_retag", retag, NEWS_RETAG_ARGUMENT_TYPES, duckdb.struct_type(RETAG_TYPE),
                        null_handling="special", side_effects=False)


def connect(market: str) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with one view per data kind plus the derived views in sql/views.sql.
    With MB_NOW set, the connection's SQL sees that time as now (FrozenClockConnection).
    News is the exception: the stored rows are `news_stored`, and the `news` view (views.sql)
    re-tags rows from before the current tagger with `news_retag` (scripts/news_tags.py)."""
    con = duckdb.connect()
    register_news_retag(con, market)
    if os.environ.get(ENV_NOW):
        con = FrozenClockConnection(con, clock())
    con.execute("SET TimeZone = 'UTC'")
    base = paths.data_dir(market)
    for kind, (file_format, columns) in SCHEMAS.items():
        name = NEWS_STORED_VIEW if kind == KIND_NEWS else kind
        if any((base / kind).glob(f"**/*.{file_format}")):
            source_sql = kind_source_sql(base, kind, file_format, columns)
            if name in ACCEPTED_KEYS and any((base / KIND_SEC_TIMES).glob(JSONL_GLOB)):
                con.execute(corrected_accepted_at_view_sql(base, name, source_sql))
            else:
                con.execute(f"CREATE VIEW {name} AS SELECT * FROM {source_sql}")
        else:
            con.execute(f"CREATE TABLE {name} ({', '.join(f'{k} {v}' for k, v in columns.items())})")
    con.execute((paths.CODE / DIR_SQL / FILE_VIEWS_SQL).read_text())
    return con
