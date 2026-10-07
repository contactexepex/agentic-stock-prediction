"""The paper-trade inbox import (issue #112; F10 write path, ARCHITECTURE.md section 9): the owner's paper trades
that the web tier (session B5) wrote to `market_brief_inbox.inbox.requests` (`tool = add_paper_trade`, schema in
mcp/inbox.sql) are validated by the same code as `scripts/portfolio.py add-trade` (service.add_trade: watchlist
ticker, session, price basis and stored bar, unused idempotency key, no short selling) and appended to
data/<market>/portfolio_trades/. Research only: a paper trade is a record, never an order.

- Identity and channel come from the inbox row (`submitted_by`, `channel`), never from its arguments; the
  idempotency key is the row's `inbox_id`. A channel other than dashboard, slack, claude_code or claude_app is
  refused (`not_allowed_in_channel`).
- Every imported row gets one command_log row (B1's format and helper, lifecycle/store.py): accepted, refused
  (validation_failed, not_allowed_in_channel) or duplicate (its key is already a stored trade's).
- Idempotent: an inbox_id with a command_log row that settled it (any result but failed) is skipped, so a rerun
  imports nothing twice; the inbox is read only, never changed. Token: MOTHERDUCK_INBOX_TOKEN only (B1's
  open_inbox); offline tests pass a local DuckDB file."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

from marketbrief.constants.kinds import KIND_COMMAND_LOG
from marketbrief.lifecycle.constants import (REFUSE_VALIDATION, RESULT_ACCEPTED, RESULT_DUPLICATE, RESULT_FAILED,
                                             RESULT_REFUSED)
from marketbrief.lifecycle.inbox import INBOX_CHANNELS, open_inbox
from marketbrief.lifecycle.store import command_row, log_command, stored_rows
from marketbrief.portfolio import trades
from marketbrief.portfolio.context import Context, TradeInput

TOOL = "add_paper_trade"
REQUESTS_TABLE = "inbox.requests"
REQUEST_COLUMNS = ("inbox_id", "kind", "tool", "market", "arguments", "channel", "submitted_by", "agent", "command_id",
                   "submitted_at")
REFUSE_CHANNEL = "not_allowed_in_channel"
ERR_CHANNEL = "channel {channel!r} may not record paper trades through the inbox (allowed: {allowed})"
ERR_FIELDS = "the request needs {missing}"
NEEDED = ("ticker", "side", "quantity", "trade_date", "price_basis")


def pending_requests(con, market: str) -> list[dict]:
    """The market's add_paper_trade rows, oldest first, minus those a command_log row already settled."""
    done = {row.get("idempotency_key") for row in stored_rows(market, KIND_COMMAND_LOG)
            if row.get("tool") == TOOL and row.get("result") != RESULT_FAILED}
    rows = con.execute(f"SELECT {', '.join(REQUEST_COLUMNS)} FROM {REQUESTS_TABLE} WHERE market = ? AND tool = ? "
                       "ORDER BY submitted_at, inbox_id", [market, TOOL]).fetchall()
    return [dict(zip(REQUEST_COLUMNS, row)) for row in rows if row[0] not in done]


def arguments_of(row: dict) -> dict:
    """The row's arguments as a dict."""
    value = row["arguments"]
    return json.loads(value) if isinstance(value, str) else dict(value or {})


def trade_input(row: dict, args: dict) -> TradeInput:
    """The TradeInput of one inbox row (identity, channel and key from the row)."""
    when = args["trade_date"]
    return TradeInput(ticker=str(args["ticker"]).strip().upper(), side=str(args["side"]).strip().lower(),
                      quantity=float(args["quantity"]),
                      trade_date=when if isinstance(when, date) else date.fromisoformat(str(when)[:10]),
                      price_basis=str(args["price_basis"]).strip().lower(), source=row["channel"],
                      price=None if args.get("price") is None else float(args["price"]), note=args.get("note"),
                      idempotency_key=row["inbox_id"], submitted_by=row["submitted_by"])


def log_request(ctx: Context, row: dict, args: dict, outcome: dict) -> str:
    """Append the command_log row of one imported request; returns its id."""
    request = {"idempotency_key": row["inbox_id"], "channel": row["channel"], "requested_by": row["submitted_by"],
               "agent": row.get("agent"), "tool": TOOL, "arguments": args}
    logged = command_row(ctx.market, ctx.clock, request, outcome["result"], refusal_code=outcome.get("refusal_code"),
                         message="; ".join(outcome.get("errors") or []) or None,
                         record_ids=outcome.get("record_ids"))
    return log_command(ctx.market, logged)


def precheck(ctx: Context, row: dict, args: dict) -> dict | None:
    """A refusal or duplicate decided before validation, or None."""
    if row["channel"] not in INBOX_CHANNELS:
        return {"result": RESULT_REFUSED, "refusal_code": REFUSE_CHANNEL,
                "errors": [ERR_CHANNEL.format(channel=row["channel"], allowed=", ".join(INBOX_CHANNELS))]}
    missing = [field for field in NEEDED if args.get(field) in (None, "")]
    if missing:
        return {"result": RESULT_REFUSED, "refusal_code": REFUSE_VALIDATION,
                "errors": [ERR_FIELDS.format(missing=", ".join(missing))]}
    existing = trades.used_keys(ctx.con, ctx.clock).get(row["inbox_id"])
    if existing:
        return {"result": RESULT_DUPLICATE, "record_ids": [existing]}
    return None


def import_one(ctx: Context, row: dict, add_trade) -> dict:
    """Validate, store and log one request; returns its result line."""
    args = arguments_of(row)
    outcome = precheck(ctx, row, args)
    if outcome is None:
        try:
            entry = trade_input(row, args)
        except (TypeError, ValueError) as error:
            outcome = {"result": RESULT_REFUSED, "refusal_code": REFUSE_VALIDATION, "errors": [str(error)]}
        else:
            stored = add_trade(ctx, replace(entry, command_id=row.get("command_id")))
            outcome = ({"result": RESULT_ACCEPTED, "record_ids": [stored["trade"]["id"]]} if stored.get("ok") else
                       {"result": RESULT_REFUSED, "refusal_code": REFUSE_VALIDATION, "errors": stored["errors"]})
    command = log_request(ctx, row, args, outcome)
    return {"inbox_id": row["inbox_id"], "ok": outcome["result"] != RESULT_REFUSED,
            "result": outcome["result"], "refusal_code": outcome.get("refusal_code"),
            "errors": outcome.get("errors"), "trade_ids": outcome.get("record_ids") or [], "command_log_id": command}


def import_inbox(ctx: Context, path: str | None, add_trade) -> dict:
    """Import every pending paper-trade request of ctx.market. add_trade: service.add_trade."""
    con = open_inbox(path)
    try:
        pending = pending_requests(con, ctx.market)
    finally:
        con.close()
    results = [import_one(ctx, row, add_trade) for row in pending]
    return {"ok": True, "market": ctx.market, "imported": len(results), "results": results}
