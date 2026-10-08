"""Stored inputs of the signal model's panel, read through DuckDB (never live APIs).

Each reader returns the rows with the time they became usable, so the panel can keep only what was
known before the session after an as-of date opened:
- bars: the adjusted daily bars (`ohlc`);
- company events: earnings and ex-dividend dates with first_seen_at (a date counts from the day it
  was first stored; before the first stored row of a type the feature is missing, not 0);
- India: NSE FII/DII provisional cash flows (published the evening of their date) and NSDL FPI equity
  net (published the next day, so only reporting dates before the as-of date are used);
- US: FINRA daily short-sale volume share (published the evening of its date) and Form 4 open-market
  purchases and sales (by acceptance time)."""
from __future__ import annotations

import duckdb
import pandas as pd

from marketbrief.analytics.features import load_bars

EVENTS_SQL = """
SELECT ticker, type, date, CAST(first_seen_at AS DATE) AS seen
FROM event_history WHERE type IN ('earnings', 'ex_dividend') ORDER BY ticker, type, date, seen"""
FLOWS_SQL = """
SELECT date, category, net_cr FROM flows_daily WHERE category IN ('FII/FPI', 'DII') ORDER BY date, category"""
FPI_SQL = """
SELECT reporting_date AS date, net_cr FROM fpi_daily
WHERE asset_class = 'Equity' AND route = 'Sub-total' ORDER BY reporting_date"""
SHORTS_SQL = "SELECT ticker, date, short_pct FROM shorts_daily ORDER BY ticker, date"
INSIDER_SQL = """
SELECT ticker, transaction_date, CAST(accepted_at AS DATE) AS seen,
       CASE code WHEN 'P' THEN 1 ELSE -1 END * TRY_CAST(value AS DOUBLE) AS signed_value
FROM insider_trades
WHERE NOT coalesce(derivative, false) AND code IN ('P', 'S') AND transaction_date IS NOT NULL
ORDER BY ticker, transaction_date, seen, signed_value"""


def safe_frame(con, sql: str, date_columns: tuple[str, ...] = ()) -> pd.DataFrame:
    """The query's rows (date_columns as pandas timestamps), or an empty frame when the kind has no
    stored rows (an empty table of the base schema lacks some columns)."""
    try:
        frame = con.execute(sql).df()
    except duckdb.Error:   # a kind never collected in this market has no such columns
        return pd.DataFrame()
    for column in date_columns:
        frame[column] = pd.to_datetime(frame[column])
    return frame


def read_inputs(con, market: str) -> dict:
    """{bars, events, flows, fpi, shorts, insiders} for one market."""
    out = {"bars": load_bars(con), "events": safe_frame(con, EVENTS_SQL, ("date", "seen"))}
    if market == "india":
        out["flows"], out["fpi"] = safe_frame(con, FLOWS_SQL), safe_frame(con, FPI_SQL)
    else:
        out["shorts"] = safe_frame(con, SHORTS_SQL)
        out["insiders"] = safe_frame(con, INSIDER_SQL, ("transaction_date", "seen"))
    return out


def inputs_until(inputs: dict, end) -> dict:
    """The inputs as known at the end of the day `end` (the weekly review's week end, issue #45.2): bars dated on or
    before it; rows with a `seen` time by their first-seen day (an event date after `end` known by then stays), the
    others by their date. Labels needing a later bar are then missing, as on that day."""
    cut = pd.Timestamp(end)
    cut_bars = {key: frame.loc[frame.index <= cut] for key, frame in inputs["bars"].items()}
    out = {"bars": {key: frame for key, frame in cut_bars.items() if len(frame)}}   # no bar by then: absent
    for name, frame in inputs.items():
        if name == "bars":
            continue
        column = "seen" if "seen" in frame.columns else "date" if "date" in frame.columns else None
        out[name] = frame if column is None else frame[frame[column] <= cut].reset_index(drop=True)
    return out
