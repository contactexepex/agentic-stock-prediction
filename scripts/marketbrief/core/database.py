"""The DuckDB connection: one view per data kind over the stored files, plus the derived views."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

from marketbrief.constants.columns import COL_ACCEPTED_AT, COL_ACCESSION, COL_CHECKED_AT
from marketbrief.constants.config_keys import CFG_SYMBOLS, CFG_TICKERS, META_ROLE
from marketbrief.constants.environment import ENV_NOW
from marketbrief.constants.files import DIR_CONFIG_MARKETS, DIR_SQL, FILE_VIEWS_SQL, JSONL_GLOB, YAML_SUFFIX
from marketbrief.constants.kinds import (
    FILE_FORMAT_JSONL,
    KIND_NEWS,
    KIND_SEC_TIMES,
    NEWS_STORED_VIEW,
)
from marketbrief.constants.news import NEWS_ID_MAP_TABLE
from marketbrief.constants.prices import MSG_NO_MARKET_CONFIG_CLOSED_DAYS, OWN_EXCHANGE_ROLES
from marketbrief.core import paths
from marketbrief.core.calendar import is_session
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
    latest_check = (
        f"(SELECT DISTINCT ON ({COL_ACCESSION}) {COL_ACCESSION} AS _acc, {COL_ACCEPTED_AT} AS _true FROM "
        f"read_json('{times_pattern}', format='newline_delimited', columns={times_columns}) "
        f"WHERE {COL_ACCEPTED_AT} IS NOT NULL ORDER BY {COL_ACCESSION}, {COL_CHECKED_AT} DESC)"
    )
    return (
        f"CREATE VIEW {name} AS SELECT s.* REPLACE (coalesce(f._true, s.{COL_ACCEPTED_AT}) AS {COL_ACCEPTED_AT}) "
        f"FROM {source_sql} s LEFT JOIN {latest_check} f ON f._acc = s.{ACCEPTED_KEYS[name]}"
    )


def unretagged_news_function(
    _feed,
    _title,
    tickers,
    primary,
    mentioned,
    confidence,
    _tag_version,
):
    """Stand-in for the news re-tagger when there is no market config: tags stay as stored.
    DuckDB checks the seven parameters against NEWS_RETAG_ARGUMENT_TYPES."""
    return {
        "tickers": list(tickers or []),
        "primary_tickers": list(primary or []),
        "mentioned_tickers": list(mentioned or []),
        "tag_confidence": confidence,
    }


def register_news_retag(con: duckdb.DuckDBPyConnection, market: str) -> None:
    """Register `news_retag`, which the `news` view uses to re-tag rows from before the current tagger."""
    from marketbrief.analytics.news_tags import RETAG_TYPE, Tagger

    try:
        retag = Tagger(load_market(market)).retag_stored
    except SystemExit:  # no market config (some tests): tags stay as stored
        retag = unretagged_news_function
    con.create_function(
        "news_retag",
        retag,
        NEWS_RETAG_ARGUMENT_TYPES,
        duckdb.struct_type(RETAG_TYPE),
        null_handling="special",
        side_effects=False,
    )


def register_news_id_map(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `news_id_map` table (id, canonical_id, match, first_seen_at) the `news` view and the news alias
    views read: every stored news id with the item it belongs to (itself, or the earlier stored item it duplicates;
    match = link | title | null) and when the id was first seen, assigned in (first_seen_at, id) order by
    analytics/news_dedup.py, so no row stored later changes an earlier assignment."""
    from marketbrief.analytics.news_dedup import assign, load_outlet_keys

    rows = con.execute(
        f"SELECT id, title, source, source_domain, url, first_seen_at FROM {NEWS_STORED_VIEW} "
        "ORDER BY first_seen_at, id"
    ).fetchall()
    con.execute(
        f"CREATE TABLE {NEWS_ID_MAP_TABLE} (id VARCHAR, canonical_id VARCHAR, match VARCHAR, first_seen_at TIMESTAMPTZ)"
    )
    pairs = assign(rows, load_outlet_keys()) if rows else []
    if pairs:
        first_seen: dict = {}
        for row in rows:  # (first_seen_at, id) order: the first row of an id is its earliest
            first_seen.setdefault(row[0], row[5])
        frame = pd.DataFrame(
            [(*pair, first_seen[pair[0]]) for pair in pairs], columns=["id", "canonical_id", "match", "first_seen_at"]
        )
        con.register("news_id_map_rows", frame)
        con.execute(f"INSERT INTO {NEWS_ID_MAP_TABLE} SELECT * FROM news_id_map_rows")
        con.unregister("news_id_map_rows")


def own_exchange_keys(cfg: dict) -> list[str]:
    """The config's stocks and own-exchange indices (cues and factors trade on other calendars)."""
    return list(cfg[CFG_TICKERS]) + [
        key for key, meta in cfg[CFG_SYMBOLS].items() if meta.get(META_ROLE) in OWN_EXCHANGE_ROLES
    ]


def register_own_closed_days(con: duckdb.DuckDBPyConnection, market: str) -> None:
    """Create the `own_closed_days` table (ticker, date) the ohlc_raw view reads (issue #40): every stored price
    date that is no session of the market's own exchange, for each stock and own-exchange index of the config.
    Built set-based from the distinct stored dates. No market config file (some tests): the table is empty and
    a warning goes to stderr; any other config error raises."""
    con.execute("CREATE TABLE own_closed_days (ticker VARCHAR, date DATE)")
    if not (paths.CONFIG / DIR_CONFIG_MARKETS / f"{market}{YAML_SUFFIX}").exists():
        print(MSG_NO_MARKET_CONFIG_CLOSED_DAYS.format(market=market), file=sys.stderr)  # issue #41: never silent
        return
    cfg = load_market(market)
    stored = [row[0] for row in con.execute("SELECT DISTINCT date FROM prices").fetchall()]
    closed = [day for day in stored if not is_session(cfg, day)]
    if closed:
        con.execute(
            "INSERT INTO own_closed_days SELECT k.ticker, d.day FROM (SELECT unnest(?) AS ticker) k "
            "CROSS JOIN (SELECT unnest(?) AS day) d",
            [own_exchange_keys(cfg), closed],
        )


def connect(market: str) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with one view per data kind plus the derived views in sql/views.sql.
    With MB_NOW set, the connection's SQL sees that time as now (FrozenClockConnection).
    News is the exception: the stored rows are `news_stored`, and the `news` view (views.sql)
    re-tags rows from before the current tagger with `news_retag` (marketbrief/analytics/news_tags.py), leaves
    out stored duplicates (`news_id_map`, analytics/news_dedup.py) and shows each item's latest headline."""
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
            column_sql = ", ".join(f"{column_name} {column_type}" for column_name, column_type in columns.items())
            con.execute(f"CREATE TABLE {name} ({column_sql})")
    register_own_closed_days(con, market)
    register_news_id_map(con)
    con.execute((paths.CODE / DIR_SQL / FILE_VIEWS_SQL).read_text())
    return con
