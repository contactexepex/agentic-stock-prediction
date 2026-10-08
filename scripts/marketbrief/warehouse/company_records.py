"""Lifecycle-event and command records as the Companies page shows them (catalogue entities "Lifecycle event" and
"Command", docs/DATA_CATALOGUE.md; selection of design/mockups/10-companies/notes.md). Everything is as of the
cut-off: B1's watchlist accessor folds the events recorded and effective by then, and events and commands count from
`recorded_at` / `received_at`. The Company records themselves are B4's (warehouse/rm_common.py). A deleted company is
never shown (decision 12): its records are left out and every echo of it in a command is masked."""

from __future__ import annotations

import json
import re
from datetime import datetime

import pandas as pd

from marketbrief.constants.market_pages import (
    COMMAND_ARGUMENT_FIELDS,
    COMPANY_COMMAND_TOOLS,
    MASKED,
    MASKED_COMPANY,
    MASKED_MESSAGE,
)
from marketbrief.lifecycle import accessor
from marketbrief.lifecycle.constants import STATE_ACTIVE, STATE_DELETED
from marketbrief.warehouse.news_items import iso

EVENTS_SQL = """SELECT * FROM watchlist_events WHERE recorded_at <= $cutoff::TIMESTAMPTZ
                ORDER BY recorded_at DESC, id"""
COMMANDS_SQL = """SELECT * FROM command_log WHERE received_at <= $cutoff::TIMESTAMPTZ AND list_contains($tools, tool)
                  ORDER BY received_at DESC, id"""
LIFECYCLE_FIELDS = ("id", "event", "ticker", "market", "effective_from", "recorded_at", "name", "exchange", "sector",
                    "amount", "reason", "requested_by", "channel", "command_id", "idempotency_key", "onboarding",
                    "supersedes")
COMMAND_FIELDS = ("id", "market", "received_at", "channel", "actor", "agent", "tool", "kind", "arguments",
                  "idempotency_key", "result", "refusal_code", "message", "record_ids", "budget_left", "completed_at")


def shown_companies(market: str, cutoff: datetime) -> tuple[list[dict], set[str]]:
    """(the Company identity records of every active and inactive company, the deleted tickers) as of the cut-off."""
    records = accessor.records(market, cutoff)
    deleted = {record["ticker"] for record in records if record["state"] == STATE_DELETED}
    return [record for record in records if record["state"] != STATE_DELETED], deleted


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


def names(text, ticker: str) -> bool:
    """Whether a text names a ticker as a whole word (any case; `PGR` in "del-pgr-1", not `GE` in "merge")."""
    pattern = rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])"
    return isinstance(text, str) and re.search(pattern, text, re.IGNORECASE) is not None


def lifecycle_rows(con, cutoff: datetime, shown: set[str], deleted: set[str] = frozenset()) -> list[dict]:
    """The lifecycle events recorded by the cut-off of the companies shown, newest first; a reason that names a
    deleted company is masked (decision 12)."""
    frame = con.execute(EVENTS_SQL, {"cutoff": cutoff.isoformat()}).df()
    rows = []
    for row in frame.to_dict("records"):
        if row["ticker"] not in shown:
            continue
        event = {field: plain(row[field]) for field in LIFECYCLE_FIELDS}
        if any(names(event["reason"], ticker) for ticker in deleted):
            event["reason"] = MASKED_MESSAGE
        rows.append(event)
    return rows


def mentions(command: dict, ticker: str) -> bool:
    """Whether a command names a ticker anywhere: an argument value, its message, idempotency key or record ids."""
    texts = [*(command["arguments"] or {}).values(), command["message"], command["idempotency_key"],
             *(command["record_ids"] or [])]
    return any(names(text, ticker) for text in texts)


def masked(command: dict, deleted: set[str]) -> dict:
    """The command with the mockup's argument keys (`market`, `symbol`, `ticker`, whichever it has) and every echo of
    a deleted company masked (decision 12): its argument values, message, idempotency key and record ids."""
    arguments = command["arguments"] or {}
    command = {**command, "arguments": {key: arguments[key] for key in COMMAND_ARGUMENT_FIELDS if key in arguments}}
    for ticker in sorted(deleted):
        if mentions({**command, "arguments": arguments}, ticker):
            command = {**command,
                       "arguments": {k: MASKED_COMPANY if names(v, ticker) else v
                                     for k, v in command["arguments"].items()},
                       "message": MASKED_MESSAGE, "idempotency_key": MASKED if command["idempotency_key"] else None,
                       "record_ids": [MASKED] * len(command["record_ids"] or [])}
    return command


def command_rows(con, cutoff: datetime, deleted: set[str]) -> list[dict]:
    """The company commands received by the cut-off, newest first, deleted companies masked."""
    frame = con.execute(COMMANDS_SQL, {"cutoff": cutoff.isoformat(), "tools": list(COMPANY_COMMAND_TOOLS)}).df()
    return [masked({field: plain(row[field]) for field in COMMAND_FIELDS}, deleted)
            for row in frame.to_dict("records")]


def inactive_news(items: list[dict], companies: list[dict]) -> list[dict]:
    """News items tagged with an inactive company and first seen since it went inactive (B1's `state_since`, a time
    or ISO text), in the items' order."""
    since = {row["ticker"]: pd.Timestamp(row["state_since"]) for row in companies if row["state"] != STATE_ACTIVE}
    return [item for item in items if any(ticker in since and pd.Timestamp(item["first_seen_at"]) >= since[ticker]
                                          for ticker in item["tickers"])]
