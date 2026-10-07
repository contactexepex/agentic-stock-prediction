"""Column types of the company-lifecycle kinds and the command log (W1; docs/SPEC.md F8, F10 and section 4;
field meanings and examples in docs/DATA_CATALOGUE.md). Research only: nothing here places or routes an order."""
from __future__ import annotations

from marketbrief.constants.kinds import KIND_COMMAND_LOG, KIND_WATCHLIST_EVENTS
from marketbrief.core.schema_base import Schemas

LIFECYCLE_SCHEMAS: Schemas = {
    # One row per company lifecycle event (F8), in the day file of recorded_at (UTC), appended by the F8
    # validator (company CLI, inbox import, seeding). id = we-<market>-<ticker>-<event>-<recorded_at as
    # YYYYMMDDTHHMMSSZ>. event add | deactivate | reactivate | delete | set_amount. effective_from: when the
    # event counts (the next pre-open run; the seeded add events: the start of stored history); recorded_at:
    # when the row was written (seed: the seeding time, so the record is honest about when it was written).
    # The company's identity (name, exchange, sector, yahoo, nse_symbol, cik) is set on its add event and
    # carried by no other event. amount: the per-trade paper amount in the market currency (null = market
    # default; set on add and set_amount only). requested_by: the identity the channel's auth gave (never taken
    # from arguments); channel dashboard | slack | claude_code | claude_app | cli | seed; command_id: the
    # command_log row that asked. onboarding: JSON of the add pipeline's checks {check: ok | failed | skipped}.
    # supersedes: a row id this one corrects (append-only corrections).
    KIND_WATCHLIST_EVENTS: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "ticker": "VARCHAR", "event": "VARCHAR",
        "effective_from": "TIMESTAMPTZ", "recorded_at": "TIMESTAMPTZ", "name": "VARCHAR", "exchange": "VARCHAR",
        "sector": "VARCHAR", "yahoo": "VARCHAR", "nse_symbol": "VARCHAR", "cik": "VARCHAR",
        "amount": "DOUBLE", "currency": "VARCHAR", "reason": "VARCHAR", "requested_by": "VARCHAR",
        "channel": "VARCHAR", "command_id": "VARCHAR", "idempotency_key": "VARCHAR", "onboarding": "JSON",
        "supersedes": "VARCHAR", "validator_version": "VARCHAR",
    }),
    # One row per command from any channel (F10), in the day file of received_at, written by the tool layer
    # (MCP server, Slack handler, CLI, inbox import). id = cmd-<received_at as YYYYMMDDTHHMMSSZ>-<first 8 hex
    # of sha256(idempotency_key)>. tool: the mcp/tools.yaml name; arguments: JSON as received, minus anything
    # secret; actor: the channel identity (e.g. slack:U0123ABCD, github:<login>, dashboard:owner, cli:session).
    # result accepted | pending | refused | duplicate | failed; refusal_code when refused (e.g. budget_exceeded,
    # kill_switch, not_allowed_in_channel, validation_failed); record_ids: the data rows the command wrote.
    KIND_COMMAND_LOG: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "received_at": "TIMESTAMPTZ", "channel": "VARCHAR",
        "actor": "VARCHAR", "agent": "VARCHAR", "tool": "VARCHAR", "kind": "VARCHAR", "arguments": "JSON",
        "idempotency_key": "VARCHAR", "result": "VARCHAR", "refusal_code": "VARCHAR", "message": "VARCHAR",
        "record_ids": "VARCHAR[]", "budget_left": "INTEGER", "completed_at": "TIMESTAMPTZ",
    }),
}
