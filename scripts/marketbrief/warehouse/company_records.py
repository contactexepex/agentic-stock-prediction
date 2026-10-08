"""Company, lifecycle-event and command records as the market pages show them (catalogue entities "Company",
"Lifecycle event" and "Command", docs/DATA_CATALOGUE.md; selection of design/mockups/10-companies/notes.md).
Everything is as of the cut-off: B1's watchlist accessor folds the events recorded and effective by then, the
latest close is the newest raw bar collected by then, and events and commands count from `recorded_at` /
`received_at`. A deleted company is never shown (decision 12): its records are left out and every echo of it in a
command is masked."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from marketbrief.lifecycle import accessor
from marketbrief.lifecycle.constants import STATE_ACTIVE, STATE_DELETED
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse.news_items import iso

COMPANY_COMMAND_TOOLS = ("add_company", "deactivate_company", "reactivate_company", "set_paper_amount",
                         "delete_company")
MASKED = "(masked)"
MASKED_COMPANY = "(deleted company)"
MASKED_MESSAGE = "(this company was deleted later; its records are excluded on read)"
# each ticker's two newest raw closes collected by the cut-off, on sessions of the market (own_closed_days left out)
CLOSES_SQL = """
WITH p AS (SELECT DISTINCT ON (ticker, date) ticker, date, close FROM prices
           WHERE collected_at <= $cutoff::TIMESTAMPTZ ORDER BY ticker, date, collected_at DESC),
r AS (SELECT * FROM p WHERE NOT EXISTS (SELECT 1 FROM own_closed_days c WHERE c.ticker = p.ticker AND c.date = p.date)),
k AS (SELECT *, row_number() OVER (PARTITION BY ticker ORDER BY date DESC) AS n FROM r
      WHERE list_contains($tickers, ticker))
SELECT ticker, date, close, n FROM k WHERE n <= 2 ORDER BY ticker, n"""
EVENTS_SQL = """SELECT * FROM watchlist_events WHERE recorded_at <= $cutoff::TIMESTAMPTZ
                ORDER BY recorded_at DESC, id"""
COMMANDS_SQL = """SELECT * FROM command_log WHERE received_at <= $cutoff::TIMESTAMPTZ AND list_contains($tools, tool)
                  ORDER BY received_at DESC, id"""
LIFECYCLE_FIELDS = ("id", "event", "ticker", "market", "effective_from", "recorded_at", "name", "exchange", "sector",
                    "amount", "reason", "requested_by", "channel", "command_id", "idempotency_key", "onboarding",
                    "supersedes")
COMMAND_FIELDS = ("id", "market", "received_at", "channel", "actor", "agent", "tool", "kind", "arguments",
                  "idempotency_key", "result", "refusal_code", "message", "record_ids", "budget_left", "completed_at")
TIME_FIELDS = ("effective_from", "recorded_at", "received_at", "completed_at")


def latest_closes(con, tickers: list[str], cutoff: str) -> dict[str, dict]:
    """ticker -> {last_close, last_close_date, change_pct} from the newest two raw closes by the cut-off."""
    closes: dict[str, list] = {}
    for ticker, day, close, _rank in con.execute(CLOSES_SQL, {"cutoff": cutoff, "tickers": tickers}).fetchall():
        closes.setdefault(ticker, []).append((day, close))
    out = {}
    for ticker, rows in closes.items():
        (day, close), previous = rows[0], rows[1] if len(rows) > 1 else None
        change = round((close / previous[1] - 1) * 100, 2) if previous and previous[1] else None
        out[ticker] = {"last_close": json_safe_float(close), "last_close_date": str(pd.Timestamp(day).date()),
                       "change_pct": change}
    return out


def shown_companies(market: str, cutoff: datetime) -> tuple[list[dict], set[str]]:
    """(the Company identity records of every active and inactive company, the deleted tickers) as of the cut-off."""
    records = accessor.records(market, cutoff)
    deleted = {record["ticker"] for record in records if record["state"] == STATE_DELETED}
    return [record for record in records if record["state"] != STATE_DELETED], deleted


def company_rows(con, market: str, cutoff: datetime, agreement_n1: dict, open_counts: dict) -> list[dict]:
    """The Company records of a market, active first, then by ticker. `agreement_n1` maps a ticker to its N+1
    {buy, of} (absent: no prediction), `open_counts` to its open paper trades."""
    identities, _deleted = shown_companies(market, cutoff)
    closes = latest_closes(con, [record["ticker"] for record in identities], cutoff.isoformat())
    rows = []
    for record in identities:
        ticker = record["ticker"]
        price = closes.get(ticker, {"last_close": None, "last_close_date": None, "change_pct": None})
        rows.append({**record, "added_at": iso(record["added_at"]), "state_since": iso(record["state_since"]),
                     **price, "agreement_n1": agreement_n1.get(ticker), "open_trades": open_counts.get(ticker, 0)})
    return sorted(rows, key=lambda row: (row["state"] != STATE_ACTIVE, row["ticker"]))


def plain(value):
    """A stored value as JSON: times as ISO UTC, JSON text parsed, missing as None."""
    if isinstance(value, (pd.Timestamp, datetime)):
        return iso(value)
    if isinstance(value, str) and value[:1] in "{[":
        return json.loads(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def lifecycle_rows(con, cutoff: datetime, shown: set[str]) -> list[dict]:
    """The lifecycle events recorded by the cut-off of the companies shown, newest first."""
    frame = con.execute(EVENTS_SQL, {"cutoff": cutoff.isoformat()}).df()
    return [{field: plain(row[field]) for field in LIFECYCLE_FIELDS}
            for row in frame.to_dict("records") if row["ticker"] in shown]


def mentions(command: dict, ticker: str) -> bool:
    """Whether a command echoes a ticker in its arguments, message, idempotency key or record ids."""
    arguments = command["arguments"] or {}
    return (ticker in (arguments.get("symbol"), arguments.get("ticker")) or ticker in (command["message"] or "")
            or ticker.lower() in (command["idempotency_key"] or "").lower()
            or any(ticker in record_id for record_id in command["record_ids"] or []))


def masked(command: dict, deleted: set[str]) -> dict:
    """The command with every echo of a deleted company masked (decision 12)."""
    for ticker in sorted(deleted):
        if mentions(command, ticker):
            arguments = command["arguments"] or {}
            command = {**command, "arguments": {k: MASKED_COMPANY if v == ticker else v for k, v in arguments.items()},
                       "message": MASKED_MESSAGE, "idempotency_key": MASKED if command["idempotency_key"] else None,
                       "record_ids": [MASKED] * len(command["record_ids"] or [])}
    return command


def command_rows(con, cutoff: datetime, deleted: set[str]) -> list[dict]:
    """The company commands received by the cut-off, newest first, deleted companies masked."""
    frame = con.execute(COMMANDS_SQL, {"cutoff": cutoff.isoformat(), "tools": list(COMPANY_COMMAND_TOOLS)}).df()
    return [masked({field: plain(row[field]) for field in COMMAND_FIELDS}, deleted)
            for row in frame.to_dict("records")]


def inactive_news(items: list[dict], companies: list[dict]) -> list[dict]:
    """News items tagged with an inactive company and first seen since it went inactive, newest first."""
    since = {row["ticker"]: row["state_since"] for row in companies if row["state"] != STATE_ACTIVE}
    return [item for item in items
            if any(ticker in since and item["first_seen_at"] >= since[ticker] for ticker in item["tickers"])]
