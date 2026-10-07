"""The open paper trades a check monitors (B9; docs/ws/b9.md), as of the check time: every qualifying strategy
prediction (accuracy view, trade id acc:<prediction_id>) and every head-to-head pick (h2h:<pick_rule>:
<prediction_id>) whose holding window D..exit_date contains this session, or that is past exit_date without a
paper_trades_settled row (exit_delayed, issue #93; at most max_past_exit sessions), with the stored bars and split/bonus
factors behind its measures. A trade is a record of the F1 protocol (docs/SPEC.md F1); nothing is ever traded.
Only rows stored by check_at are read (no look-ahead), and a prediction or pick made after D's open is refused
as the settlement refuses it (F1.8)."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.core.calendar import session_open_utc
from marketbrief.intraday.constants import PICK_PICKED, VIEW_ACCURACY, VIEW_HEAD_TO_HEAD
from marketbrief.intraday.inputs import ADJUSTMENTS_ASOF, CALENDAR_DAYS_PER_SESSION, records, sessions_between

PREDICTION_COLUMNS = (
    "id, strategy_id, family, ticker, made_at, as_of_date, session_date, exit_date, horizon_days, direction, "
    "prob_up, qualifies, target_price, lo50, hi50, lo80, hi80, amount, currency"
)


def open_trades(con, cfg: dict, session_date: date, check_at: datetime,
                max_past_exit: int = 0) -> tuple[dict[str, list[dict]], dict]:
    """({ticker: trades sorted by trade_id}, {"not_locked": n, "delayed_too_long": [trade ids]}). A prediction id's
    first stored row wins (ids are skipped once they exist), as does a pick id's. A trade with a paper_trades_settled
    row stored by check_at is closed, whatever its status (B2: no_entry and skipped trades get a row too). Issue #93:
    a trade past its exit date without such a row (exit_delayed: no exit close yet) stays open for at most
    `max_past_exit` sessions after the exit date; later ones are listed as delayed_too_long."""
    preds = records(con.execute(
        f"SELECT DISTINCT ON (id) {PREDICTION_COLUMNS} FROM strategy_predictions WHERE made_at <= ? "
        "AND session_date <= ? AND exit_date >= ? ORDER BY id, made_at",
        [check_at, session_date, session_date - timedelta(days=CALENDAR_DAYS_PER_SESSION * (max_past_exit + 1) + 7)],
    ).df())
    preds = {row["id"]: row for row in preds if row.get("session_date") is not None
             and row.get("exit_date") is not None}
    settled = {row[0] for row in con.execute(
        "SELECT DISTINCT trade_id FROM paper_trades_settled WHERE settled_at <= ?", [check_at]).fetchall()}
    picks = records(con.execute(
        "SELECT DISTINCT ON (id) id, made_at, family, pick_rule, status, prediction_id FROM head_to_head_picks "
        "WHERE made_at <= ? ORDER BY id, made_at", [check_at]).df())
    candidates = [(pred, VIEW_ACCURACY, None, pred["made_at"]) for pred in preds.values()
                  if pred["qualifies"] and pred["direction"] == "up"]
    for pick in picks:
        pred = preds.get(pick["prediction_id"])
        if pick["status"] == PICK_PICKED and pred is not None:
            made_at = max(pd.Timestamp(pick["made_at"]), pd.Timestamp(pred["made_at"]))
            candidates.append((pred, VIEW_HEAD_TO_HEAD, pick, made_at))
    out: dict[str, list[dict]] = {}
    refused, too_long = 0, []
    for pred, view, pick, made_at in candidates:
        trade = _trade(cfg, pred, view, pick, made_at, session_date)
        if trade is None:
            refused += _day(pred["exit_date"]) >= session_date   # counted while it would still be open
            continue
        if trade["trade_id"] in settled:
            continue
        if trade["exit_date"] < session_date:
            past = len(sessions_between(cfg, trade["exit_date"] + timedelta(days=1), session_date))
            if past > max_past_exit:
                too_long.append(trade["trade_id"])
                continue
            trade["exit_delayed"] = True
        out.setdefault(trade["ticker"], []).append(trade)
    return {ticker: sorted(trades, key=lambda t: t["trade_id"]) for ticker, trades in sorted(out.items())}, {
        "not_locked": refused, "delayed_too_long": sorted(too_long)}


def _trade(cfg: dict, pred: dict, view: str, pick: dict | None, made_at, session_date: date) -> dict | None:
    """One open trade, or None when the record was made after D's open (not locked, F1.8)."""
    entry_date, exit_date = _day(pred["session_date"]), _day(pred["exit_date"])
    if pd.Timestamp(made_at) >= pd.Timestamp(session_open_utc(cfg, entry_date)):
        return None
    pick_rule = pick["pick_rule"] if pick else None
    trade_id = f"acc:{pred['id']}" if view == VIEW_ACCURACY else f"h2h:{pick_rule}:{pred['id']}"
    return {
        "trade_id": trade_id, "view": view, "pick_rule": pick_rule, "prediction_id": pred["id"],
        "strategy_id": pred["strategy_id"], "family": pred["family"], "ticker": pred["ticker"],
        "horizon_days": int(pred["horizon_days"]), "as_of_date": _day(pred["as_of_date"]),
        "entry_date": entry_date, "exit_date": exit_date, "direction": pred["direction"],
        "target_price": pred["target_price"], "lo50": pred["lo50"], "hi50": pred["hi50"], "lo80": pred["lo80"],
        "hi80": pred["hi80"], "amount": pred["amount"],
        "session_number": len(sessions_between(cfg, entry_date, session_date)),
        "exit_session_number": len(sessions_between(cfg, entry_date, exit_date)), "exit_delayed": False,
    }


def window_bars(con, tickers: list[str], start: date, session_date: date, check_at: datetime) -> dict:
    """{(ticker, date): {open, high, low, close}} of the raw daily bars from start up to the day before the session,
    each the newest row collected by check_at, minus the exchange's closed days (as the ohlc_raw view)."""
    if not tickers:
        return {}
    frame = con.execute(
        "WITH p AS (SELECT DISTINCT ON (ticker, date) ticker, date, open, high, low, close FROM prices "
        "WHERE collected_at <= ? AND date >= ? AND date < ? AND list_contains(?, ticker) "
        "ORDER BY ticker, date, collected_at DESC) "
        "SELECT * FROM p WHERE NOT EXISTS (SELECT 1 FROM own_closed_days c WHERE c.ticker = p.ticker "
        "AND c.date = p.date) ORDER BY ticker, date",
        [check_at, start, session_date, tickers],
    ).df()
    return {(row["ticker"], _day(row["date"])): row for row in records(frame)}


def adjustment_factors(con, tickers: list[str], session_date: date, check_at: datetime) -> dict[str, list]:
    """{ticker: [(ex_date, factor)]} of the splits and bonus issues detected by check_at with an ex-date up to the
    session; a correction (`supersedes`) counts only once detected by check_at (inputs.ADJUSTMENTS_ASOF)."""
    if not tickers:
        return {}
    frame = con.execute(
        f"WITH {ADJUSTMENTS_ASOF} SELECT ticker, ex_date, factor FROM adj WHERE ex_date <= ? "
        "AND list_contains(?, ticker) ORDER BY ticker, ex_date, factor",
        [check_at, check_at, session_date, tickers],
    ).df()
    out: dict[str, list] = {}
    for row in records(frame):
        out.setdefault(row["ticker"], []).append((_day(row["ex_date"]), float(row["factor"])))
    return out


def factor_after(adjustments: list, after: date) -> float:
    """The product of the factors with an ex-date after `after`: a price of that day times it is on today's basis."""
    return math.prod(factor for ex_date, factor in sorted(adjustments) if ex_date > after)


def _day(value) -> date:
    """A stored date or timestamp as a date."""
    return value if type(value) is date else pd.Timestamp(value).date()
