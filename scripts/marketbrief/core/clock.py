"""The run's clock (MB_NOW freezes it) and the frozen-clock DuckDB connection."""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone

import duckdb

from marketbrief.constants.environment import ENV_NOW
from marketbrief.constants.messages import MSG_MB_NOW_NEEDS_OFFSET

_CLOCK_SQL = [(re.compile(r"\bcurrent_date\b(\s*\(\s*\))?", re.I), "DATE '{d}'"),
              (re.compile(r"\b(?:now|get_current_timestamp|current_timestamp)\s*\(\s*\)|\bcurrent_timestamp\b", re.I),
               "TIMESTAMPTZ '{t}'")]


def clock() -> datetime:
    """Now as an aware UTC datetime. MB_NOW (ISO 8601 with a UTC offset) freezes it, so an as-of
    replay (scripts/ai_replay.py) runs features, calibrate, context and ranges as of that time;
    connect() then also freezes DuckDB's current_date. Unset in live runs."""
    fixed = os.environ.get(ENV_NOW)
    if not fixed:
        return datetime.now(timezone.utc)
    frozen = datetime.fromisoformat(fixed.replace("Z", "+00:00"))
    if frozen.tzinfo is None:
        raise SystemExit(MSG_MB_NOW_NEEDS_OFFSET.format(value=fixed))
    return frozen.astimezone(timezone.utc)


def utc_now() -> str:
    """The clock as an ISO 8601 UTC string without microseconds."""
    return clock().replace(microsecond=0).isoformat()


def utc_today() -> date:
    """The clock's UTC date."""
    return clock().date()


def freeze_sql(sql: str, at: datetime) -> str:
    """SQL with DuckDB's clock functions replaced by the literal time `at` (UTC)."""
    for pattern, literal in _CLOCK_SQL:
        sql = pattern.sub(literal.format(d=at.date().isoformat(), t=at.isoformat()), sql)
    return sql


class FrozenClockConnection:
    """A DuckDB connection whose SQL sees `at` as the current date and time (MB_NOW). Every other
    attribute is the wrapped connection's; execute() returns that connection, as DuckDB's does."""

    def __init__(self, con: duckdb.DuckDBPyConnection, at: datetime):
        """Wrap the connection and the frozen time."""
        self._con, self._at = con, at

    def execute(self, query: str, *args, **kwargs):
        """Run the query with the clock frozen."""
        return self._con.execute(freeze_sql(query, self._at), *args, **kwargs)

    def sql(self, query: str, *args, **kwargs):
        """Build a relation from the query with the clock frozen."""
        return self._con.sql(freeze_sql(query, self._at), *args, **kwargs)

    def __getattr__(self, name):
        """Every other attribute comes from the wrapped connection."""
        return getattr(self._con, name)
