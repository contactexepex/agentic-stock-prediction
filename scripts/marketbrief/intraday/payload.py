"""The cockpit's read model of the intraday checks (like WS1's per-page read models): for one market and session,
as of a time, the checks run, each ticker's newest measures, the deviations with their notes, and the learning
loop's outcomes over recent sessions. B9: each open paper trade's newest check of the session and the session's
alerts. Only rows stored by `as_of` are used (MB_NOW-aware default)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.core.clock import clock
from marketbrief.intraday.constants import PAPER_ONLY
from marketbrief.intraday.inputs import records
from marketbrief.intraday.outcomes import explanation_outcomes, outcome_summary

TICKER_FIELDS = (
    "ticker", "check_id", "check_at", "quality", "last_price", "last_time", "open_price", "prev_close", "gap",
    "ret_since_open", "move_z", "band_1d", "band_5d", "lo80_1d", "lo50_1d", "hi50_1d", "hi80_1d", "lo80_5d",
    "hi80_5d", "bench_ret", "sector_ret", "sector_source", "beta", "residual", "residual_z", "flags", "flagged",
    "bands", "open_trades",
)
TRADE_FIELDS = (
    "trade_id", "check_id", "check_at", "ticker", "strategy_id", "family", "view", "pick_rule", "horizon_days",
    "entry_date", "exit_date", "session_number", "quality", "entry_price", "last_price", "ret_since_entry_pct",
    "target_price", "to_target_pct", "lo80", "lo50", "hi50", "hi80", "band", "target_z", "target_reached",
    "target_reached_session", "high_since_entry_pct", "low_since_entry_pct", "flags", "flagged",
)
ALERT_FIELDS = ("id", "check_id", "check_at", "ticker", "alert_type", "trade_ids", "trades", "flags", "repeat",
                "news_id", "news_title", "news_status", "news_materiality", "check_row_id")
JSON_FIELDS = ("candidates", "calls", "bands", "trades")
DEVIATION_FIELDS = (*TICKER_FIELDS, "id", "candidates", "calls", "explanation_id", "attribution", "explanation",
                    "cited_ids", "explained_at")
HISTORY_DAYS = 28


def plain(value):
    """A JSON-ready value (timestamps as ISO text, dates as YYYY-MM-DD, JSON text parsed, arrays as lists)."""
    if isinstance(value, pd.Timestamp | datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def pick(row: dict, fields: tuple) -> dict:
    """The listed fields of a row, JSON-ready (JSON columns parsed)."""
    out = {}
    for key in fields:
        value = row.get(key)
        if key in JSON_FIELDS and isinstance(value, str):
            value = json.loads(value)
        out[key] = plain(value)
    return out


def latest_session(con, as_of: datetime) -> date | None:
    """The newest session with a check by as_of."""
    found = con.execute("SELECT max(session_date) FROM intraday_runs WHERE check_at <= ?", [as_of]).fetchall()
    return found[0][0] if found and found[0][0] is not None else None


def intraday_payload(con, market: str, settings: dict, as_of: datetime | None = None,
                     session_date: date | None = None) -> dict:
    """{market, cutoff, session_date, label, runs, tickers, deviations, trades, alerts, history} for the cockpit (the
    payload of a planned `rm.intraday` read model; docs/ws/ws5.md "Contract" has the proposed api/openapi.yaml
    schema). Runs are newest first; tickers by ticker; deviations by check time; trades (B9: each open paper
    trade's newest check of the session) by trade id; alerts (B9) by check time. The alerts' explainer notes are
    in `deviations` (as of as_of)."""
    as_of = as_of or clock()
    session_date = session_date or latest_session(con, as_of)
    base = {"market": market, "cutoff": as_of.isoformat(), "label": PAPER_ONLY,
            "session_date": session_date.isoformat() if session_date else None}
    if session_date is None:
        return {**base, "runs": [], "tickers": [], "deviations": [], "trades": [], "alerts": [],
                "history": {**outcome_summary([]), "rows": []}}
    runs = con.execute(
        "SELECT id, check_at, status, tickers, written, flagged, stale FROM intraday_runs "
        "WHERE session_date = ? AND check_at <= ? ORDER BY check_at DESC, id", [session_date, as_of]).df()
    tickers = con.execute(
        "SELECT DISTINCT ON (ticker) * FROM intraday_checks WHERE session_date = ? AND check_at <= ? "
        "ORDER BY ticker, check_at DESC, id", [session_date, as_of]).df()
    deviations = con.execute(
        "SELECT * REPLACE (CASE WHEN explained_at <= ? THEN explanation END AS explanation, "
        "CASE WHEN explained_at <= ? THEN explanation_id END AS explanation_id, "
        "CASE WHEN explained_at <= ? THEN attribution END AS attribution, "
        "CASE WHEN explained_at <= ? THEN cited_ids END AS cited_ids, "
        "CASE WHEN explained_at <= ? THEN explained_at END AS explained_at) "
        "FROM intraday_deviations WHERE session_date = ? AND check_at <= ? ORDER BY check_at, ticker",
        [as_of] * 5 + [session_date, as_of]).df()
    trades = con.execute(
        "SELECT DISTINCT ON (trade_id) * FROM trade_check_rows WHERE session_date = ? AND check_at <= ? "
        "ORDER BY trade_id, check_at DESC, id", [session_date, as_of]).df()
    alerts = con.execute(
        "SELECT * FROM intraday_alerts_feed WHERE session_date = ? AND check_at <= ? ORDER BY check_at, ticker, id",
        [session_date, as_of]).df()
    history = explanation_outcomes(con, settings, session_date - timedelta(days=HISTORY_DAYS), session_date, as_of)
    return {
        **base,
        "runs": [{key: plain(value) for key, value in row.items()} for row in records(runs)],
        "tickers": [pick(row, TICKER_FIELDS) for row in records(tickers)],
        "deviations": [pick(row, DEVIATION_FIELDS) for row in records(deviations)],
        "trades": [pick(row, TRADE_FIELDS) for row in records(trades)],
        "alerts": [pick(row, ALERT_FIELDS) for row in records(alerts)],
        "history": {**outcome_summary(history), "rows": history},
    }
