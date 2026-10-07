"""The inbox import (F10 write path; ARCHITECTURE.md section 9): company commands the web tier wrote to the MotherDuck
database `market_brief_inbox` are validated by the same lifecycle code as the CLI and appended to data/.

Inbox table read (written by session B5's tool layer): `inbox.company_commands` with inbox_id (the client's
idempotency key), market, tool (add_company | deactivate_company | reactivate_company | set_paper_amount |
delete_company), arguments (JSON: symbol or ticker, amount, reason, confirm), actor (the channel's sign-in identity,
never from the arguments), channel, submitted_at, command_id (optional), and optionally slack_channel and slack_ts
(the channel and ts of the Slack message the command produced, written by B5): with --slack-reply (onboard.yml) and
both set, the import replies
in that thread with the command's result through B6's `alerts.onboarding.post_onboarding_confirmation` (once per
command and result; a Slack failure is reported in the import's result and never stops the import).
The import never deletes inbox rows: an inbox_id with a command_log row that settled it (accepted, refused or
duplicate) is skipped, so a rerun imports nothing twice; an inbox_id whose rows are all `failed` (a source did not
answer, nothing was stored) is tried again by the next import (onboard.yml or the routine's). Token: the env
MOTHERDUCK_INBOX_TOKEN only, handed to DuckDB as a connection setting (never in SQL, a URL or the output); offline
tests pass a local DuckDB file."""
from __future__ import annotations

import json
import os

import duckdb

from marketbrief.constants.kinds import KIND_COMMAND_LOG
from marketbrief.lifecycle import commands
from marketbrief.lifecycle.constants import ENV_INBOX_TOKEN, EVENT_ADD, EVENT_OF_TOOL, INBOX_DATABASE, RESULT_FAILED
from marketbrief.lifecycle.store import stored_rows

INBOX_TABLE = "inbox.company_commands"
INBOX_COLUMNS = "inbox_id, market, tool, arguments, actor, channel, submitted_at, command_id"
SLACK_COLUMNS = ("slack_channel", "slack_ts")   # optional (B5); read when the table has them
MOTHERDUCK_SETTING = "motherduck_token"


def masked(text: str) -> str:
    """The text with the inbox token replaced by ***."""
    secret = os.environ.get(ENV_INBOX_TOKEN, "").strip()
    return str(text).replace(secret, "***") if secret else str(text)


def open_inbox(path: str | None):
    """A read-only connection with the inbox attached as market_brief_inbox and in use: the local file, else
    MotherDuck."""
    if path:
        con = duckdb.connect()
        con.execute(f"ATTACH '{str(path).replace(chr(39), chr(39) * 2)}' AS {INBOX_DATABASE} (READ_ONLY)")
        con.execute(f"USE {INBOX_DATABASE}")
        return con
    token = os.environ.get(ENV_INBOX_TOKEN, "").strip()
    if not token:
        raise SystemExit(f"{ENV_INBOX_TOKEN} is not set and no --inbox file was given")
    try:
        con = duckdb.connect(config={MOTHERDUCK_SETTING: token})
        con.execute("INSTALL motherduck")
        con.execute("LOAD motherduck")
        con.execute(f"ATTACH 'md:{INBOX_DATABASE}' AS {INBOX_DATABASE} (READ_ONLY)")
        con.execute(f"USE {INBOX_DATABASE}")
        return con
    except duckdb.Error as exc:
        raise SystemExit(masked(f"inbox: {type(exc).__name__}: {exc}")) from None


def pending_rows(con, market: str) -> list[dict]:
    """The market's company commands, oldest first, minus those already imported."""
    done = {row.get("idempotency_key") for row in stored_rows(market, KIND_COMMAND_LOG)
            if row.get("result") != RESULT_FAILED}
    present = {row[0] for row in con.execute(f"DESCRIBE {INBOX_TABLE}").fetchall()}
    slack = [column for column in SLACK_COLUMNS if column in present]
    columns = INBOX_COLUMNS + "".join(f", {column}" for column in slack)
    rows = con.execute(f"SELECT {columns} FROM {INBOX_TABLE} WHERE market = ? AND tool IN "
                       f"({', '.join('?' * len(EVENT_OF_TOOL))}) ORDER BY submitted_at, inbox_id",
                       [market, *EVENT_OF_TOOL]).fetchall()
    names = [column.strip() for column in columns.split(",")]
    return [dict(zip(names, row)) for row in rows if row[0] not in done]


INBOX_CHANNELS = ("dashboard", "slack", "claude_code", "claude_app")   # never cli or seed (docs/ws/b1.md)


def request_of(row: dict) -> dict:
    """The lifecycle request of one inbox row (identity and channel from the row, never from its arguments)."""
    arguments = row["arguments"]
    arguments = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    event = EVENT_OF_TOOL[row["tool"]]
    ticker = arguments.get("symbol") if event == EVENT_ADD else arguments.get("ticker")
    request = {"market": row["market"], "ticker": str(ticker or "").strip().upper(), "event": event,
               "idempotency_key": row["inbox_id"], "requested_by": row["actor"],
               "channel": row["channel"] if row["channel"] in INBOX_CHANNELS else f"not-allowed:{row['channel']}",
               "command_id": row.get("command_id"), "reason": arguments.get("reason"), "tool": row["tool"]}
    if "amount" in arguments:
        request["amount"] = arguments["amount"]
    if event == "delete":
        request["confirm"] = str(arguments.get("confirm") or "").strip().upper()
    return request


def slack_reply(market: str, command_id: str | None, row: dict, reply) -> dict | None:
    """Reply to the command's Slack message with its command_log record (None when replies are off or the row names
    no message)."""
    if reply is None or not (command_id and row.get("slack_channel") and row.get("slack_ts")):
        return None
    record = next((stored for stored in stored_rows(market, KIND_COMMAND_LOG) if stored["id"] == command_id), None)
    if record is None:
        return {"error": f"command_log row {command_id} not found"}
    try:
        return reply(record, row["slack_channel"], row["slack_ts"])
    except Exception as exc:  # Slack is a notice, never part of the record: report and go on
        return {"error": masked(f"{type(exc).__name__}: {str(exc)[:200]}")}


def default_reply(record: dict, channel: str, thread_ts: str) -> dict:
    """B6's onboarding confirmation (marketbrief/alerts/onboarding.py)."""
    from marketbrief.alerts.onboarding import post_onboarding_confirmation

    return post_onboarding_confirmation(record, channel, thread_ts)


def import_inbox(market: str, path: str | None, sources, skip_backfill: bool = False, reply=None) -> dict:
    """Import every pending company command of the market; returns one result per inbox row. With `reply` (the CLI's
    --slack-reply passes default_reply, B6's confirmation) each row naming a Slack message gets a threaded reply and
    its summary in `slack_reply`; without it nothing is posted (tests, local runs)."""
    con = open_inbox(path)
    try:
        pending = pending_rows(con, market)
    finally:
        con.close()
    results = []
    for row in pending:
        request = request_of(row)
        if request["event"] == EVENT_ADD:
            result = commands.add_company(request, sources, skip_backfill)
        else:
            result = commands.submit(request)
        results.append({"inbox_id": row["inbox_id"], "tool": row["tool"], "ok": result.get("ok"),
                        "duplicate": bool(result.get("duplicate")), "refusal_code": result.get("refusal_code"),
                        "errors": result.get("errors"), "event_id": (result.get("event") or {}).get("id"),
                        "command_id": result.get("command_id"),
                        "slack_reply": slack_reply(market, result.get("command_id"), row, reply)})
    return {"ok": True, "market": market, "imported": len(results), "results": results}
