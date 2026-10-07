"""The lifecycle commands (the CLI, the inbox import and later the governed tools call these): submit one validated
watchlist event, and list the watchlist. Every command is logged in command_log (accepted, refused or duplicate);
a refused command stores no event. Research only: an event is a record, never an order."""
from __future__ import annotations

from marketbrief.constants.kinds import KIND_WATCHLIST_EVENTS
from marketbrief.contracts.watchlist import CURRENCY
from marketbrief.core.clock import clock
from marketbrief.core.market_config import load_market
from marketbrief.lifecycle import accessor
from marketbrief.lifecycle import constants as text
from marketbrief.lifecycle.constants import (
    RESULT_ACCEPTED,
    RESULT_DUPLICATE,
    RESULT_FAILED,
    RESULT_REFUSED,
    TOOL_OF_EVENT,
)
from marketbrief.lifecycle.events import stored_events
from marketbrief.lifecycle.loader import companies_as_of
from marketbrief.lifecycle.store import command_row, iso, load_lifecycle_config, log_command, store_rows
from marketbrief.lifecycle.validator import (
    effective_time,
    event_row,
    field_errors,
    newest_effective,
    state_errors,
    supersedes_errors,
)

ARGUMENT_FIELDS = ("market", "ticker", "event", "amount", "reason", "supersedes")


def arguments(request: dict) -> dict:
    """The command's arguments as logged (nothing secret is ever part of a request)."""
    return {field: request.get(field) for field in ARGUMENT_FIELDS if request.get(field) is not None}


def finish(request: dict, received, result: dict, outcome: str, refusal: str | None = None,
           record_ids: list[str] | None = None) -> dict:
    """Log the command (when the market is known) and return the result with its command id."""
    if request.get("market") not in CURRENCY or request.get("log_command") is False:
        return result
    logged = {**request, "tool": request.get("tool") or TOOL_OF_EVENT.get(request.get("event")),
              "arguments": arguments(request)}
    message = "; ".join(result.get("errors") or []) or None
    row = command_row(request["market"], received, logged, outcome, refusal_code=refusal, message=message,
                      record_ids=record_ids, completed=clock())
    stored = log_command(request["market"], row)
    return {**result, "command_id": stored["id"], "command_record": stored}


def refused(request: dict, received, errors: list[str], code: str) -> dict:
    """A refused command: nothing stored but its command_log row."""
    return finish(request, received, {"ok": False, "refusal_code": code, "errors": errors}, RESULT_REFUSED, code)


def submit(request: dict) -> dict:
    """Validate one request and append its event. Returns {"ok", "event", "path"} on success, {"ok": True,
    "duplicate": True, "event"} for a key already used (nothing new stored), else {"ok": False, "refusal_code",
    "errors"}."""
    received = clock()
    errors = field_errors(request)
    if errors:
        return refused(request, received, errors, text.REFUSE_VALIDATION)
    market, ticker = request["market"], request["ticker"]
    stored = stored_events(market)
    existing = next((row for row in stored if row.get("idempotency_key") == request["idempotency_key"]), None)
    if existing:
        result = {"ok": True, "duplicate": True, "event": strip(existing),
                  "message": text.ERR_DUPLICATE.format(key=request["idempotency_key"], existing=existing["id"])}
        return finish(request, received, result, RESULT_DUPLICATE, record_ids=[existing["id"]])
    company = pending_company(market, ticker, stored, received)
    errors, code = state_errors(request, company)
    errors += supersedes_errors(request, stored)
    if errors:
        return refused(request, received, errors, code or text.REFUSE_VALIDATION)
    cfg = load_market(market)
    effective = effective_time(request, cfg, received, load_lifecycle_config(), newest_effective(stored, ticker))
    row = event_row(request, received, effective, {stored_row["id"] for stored_row in stored})
    path = store_rows([row], KIND_WATCHLIST_EVENTS, market, received)
    return finish(request, received, {"ok": True, "event": row, "path": path}, RESULT_ACCEPTED, record_ids=[row["id"]])


def pending_company(market: str, ticker: str, stored: list[dict], received) -> dict | None:
    """The company after every stored event, including those not in effect yet (a deactivate waiting for the next
    pre-open run): a request is checked against that state, so a reactivate can cancel a pending deactivate and a
    second deactivate is refused. The new event never takes effect before the newest stored one (effective_time)."""
    tickers, sectors = accessor.config_lists(market)
    newest = newest_effective(stored, ticker)
    return companies_as_of(market, tickers, sectors, max(received, newest) if newest else received).get(ticker)


def strip(row: dict) -> dict:
    """A stored row without the reader's bookkeeping."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def list_watchlist(market: str) -> dict:
    """Every company as of the clock with its state and amount (deleted ones only counted, never shown)."""
    now = clock()
    records = accessor.records(market, now)
    shown = [record for record in records if record["state"] != "deleted"]
    shown.sort(key=lambda record: (record["state"] != "active", record["sector"] or "", record["ticker"]))
    return {"ok": True, "market": market, "as_of": iso(now), "paper_only": True,
            "companies": [{**record, "added_at": iso(record["added_at"]), "state_since": iso(record["state_since"])}
                          for record in shown],
            "counts": {state: sum(record["state"] == state for record in records)
                       for state in ("active", "inactive", "deleted")}}


def precheck_add(request: dict) -> dict | None:
    """The checks of an add that need no onboarding (fields, key, state), run before the backfill: a result to
    return (refused or duplicate), or None when onboarding may start."""
    received = clock()
    errors = [error for error in field_errors(request) if not error.startswith("the add event needs")]
    if errors:
        return refused(request, received, errors, text.REFUSE_VALIDATION)
    stored = stored_events(request["market"])
    existing = next((row for row in stored if row.get("idempotency_key") == request["idempotency_key"]), None)
    if existing:
        result = {"ok": True, "duplicate": True, "event": strip(existing),
                  "message": text.ERR_DUPLICATE.format(key=request["idempotency_key"], existing=existing["id"])}
        return finish(request, received, result, RESULT_DUPLICATE, record_ids=[existing["id"]])
    company = pending_company(request["market"], request["ticker"], stored, received)
    errors, code = state_errors(request, company)
    return refused(request, received, errors, code) if errors else None


def add_company(request: dict, sources, skip_backfill: bool = False) -> dict:
    """add: pre-check, onboarding (identifiers, sector, backfill, collect gate), then the add event."""
    from marketbrief.lifecycle.onboarding import onboard

    early = precheck_add(request)
    if early:
        return early
    result = onboard(request["market"], request["ticker"], sources, load_market(request["market"]),
                     sector=request.get("sector"), name=request.get("name"), skip_backfill=skip_backfill)
    if result.get("failed"):
        failed = {"ok": False, "failed": True, "errors": result["errors"]}
        return finish(request, clock(), failed, RESULT_FAILED)
    if not result["ok"]:
        return {**refused(request, clock(), result["errors"], result["refusal_code"]),
                **{key: result[key] for key in ("company", "onboarding", "details") if key in result}}
    company = result["company"]
    submitted = submit({**request, **{field: company.get(field) for field in
                                      ("name", "exchange", "sector", "yahoo", "nse_symbol", "cik")},
                        "onboarding": result["onboarding"]})
    return {**submitted, "onboarding": result["onboarding"], "details": result["details"]}
