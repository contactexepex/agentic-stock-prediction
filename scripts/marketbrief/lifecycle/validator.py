"""The F8 lifecycle validator: checks one requested watchlist event against the stored events and builds its row.

A request is a dict: market, ticker, event, idempotency_key, requested_by, channel, and as the event needs: amount
(add, set_amount; `amount_given` true for set_amount, where None means "back to the default"), reason, confirm
(delete: the typed ticker), identity fields and onboarding checks (add), command_id, supersedes. Nothing is stored
here; the commands store the row only when `check` returns no error."""
from __future__ import annotations

import math
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from marketbrief.contracts.watchlist import CHANNELS, CURRENCY, EVENTS, EXCHANGES
from marketbrief.core import calendar
from marketbrief.lifecycle import constants as text
from marketbrief.lifecycle.constants import (
    EVENT_ADD,
    EVENT_DELETE,
    EVENT_ID_PREFIX,
    EVENT_SET_AMOUNT,
    IDENTITY_FIELDS,
    KEY_PATTERN,
    STAMP_FORMAT,
    STATE_DELETED,
    TICKER_PATTERN,
    TRANSITIONS,
    VALIDATOR_VERSION,
)
from marketbrief.lifecycle.events import parse_time
from marketbrief.lifecycle.store import iso

DELETE_CHANNELS = ("dashboard", "cli")   # decisions 15, 20; mcp/tools.yaml delete_company
IMMEDIATE_EVENTS = (EVENT_ADD, EVENT_DELETE)


def next_pre_open(cfg: dict, now: datetime, lifecycle_cfg: dict) -> datetime:
    """The start of the next pre-open run after `now`: pre_open_local on the next session of the market."""
    zone = ZoneInfo(cfg["timezone"])
    hour, minute = (int(part) for part in lifecycle_cfg["pre_open_local"][cfg["market"]].split(":"))
    day = now.astimezone(zone).date()
    for _ in range(30):
        day = calendar.next_session(cfg, day)
        start = datetime.combine(day, time(hour, minute), zone)
        if start > now:
            return start.astimezone(now.tzinfo)
        day += timedelta(days=1)
    raise ValueError("no session in the next 30 days")


def effective_time(request: dict, cfg: dict, now: datetime, lifecycle_cfg: dict, newest: datetime | None) -> datetime:
    """When the event counts: now for add and delete, else the next pre-open run; never before the company's newest
    stored event (so a later request never takes effect earlier)."""
    effective = now if request["event"] in IMMEDIATE_EVENTS else next_pre_open(cfg, now, lifecycle_cfg)
    return max(effective, newest) if newest else effective


def amount_problem(amount) -> bool:
    """True unless amount is None or a finite number >= 1."""
    if amount is None:
        return False
    return isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 1


def field_errors(request: dict) -> list[str]:
    """Checks that need no stored data."""
    errors = []
    market, ticker, event = request.get("market"), request.get("ticker") or "", request.get("event")
    if market not in CURRENCY:
        errors.append(text.ERR_MARKET.format(market=market, allowed=", ".join(CURRENCY)))
    if not re.match(TICKER_PATTERN, ticker):
        errors.append(text.ERR_TICKER.format(ticker=ticker))
    if event not in EVENTS:
        errors.append(text.ERR_EVENT.format(event=event, allowed=", ".join(EVENTS)))
    if not re.match(KEY_PATTERN, request.get("idempotency_key") or ""):
        errors.append(text.ERR_KEY.format(key=request.get("idempotency_key")))
    if request.get("channel") not in CHANNELS:
        errors.append(text.ERR_CHANNEL.format(channel=request.get("channel"), allowed=", ".join(CHANNELS)))
    if not (request.get("requested_by") or "").strip():
        errors.append(text.ERR_REQUESTED_BY)
    if len(request.get("reason") or "") > text.REASON_LIMIT:
        errors.append(text.ERR_REASON.format(limit=text.REASON_LIMIT))
    return errors + event_errors(request)


def event_errors(request: dict) -> list[str]:
    """The checks of one event's own fields: amount, delete's typed confirmation and channel, add's identity."""
    errors, event, ticker = [], request.get("event"), request.get("ticker") or ""
    if amount_problem(request.get("amount")):
        errors.append(text.ERR_AMOUNT)
    if request.get("amount") is not None and event not in (EVENT_ADD, EVENT_SET_AMOUNT):
        errors.append(text.ERR_AMOUNT_ONLY)
    if event == EVENT_DELETE:
        if request.get("confirm") != ticker:
            errors.append(text.ERR_CONFIRM.format(ticker=ticker))
        if request.get("channel") not in DELETE_CHANNELS:
            errors.append(text.ERR_CONFIRM_CHANNEL)
    if event == EVENT_ADD:
        errors += identity_errors(request)
    return errors


def identity_errors(request: dict) -> list[str]:
    """An add event carries the company's identity: name, exchange, sector, Yahoo symbol; NSE symbol or CIK."""
    market = request.get("market")
    needed = ["name", "exchange", "sector", "yahoo"] + (["nse_symbol"] if market == "india" else ["cik"])
    errors = [text.ERR_IDENTITY.format(field=field) for field in needed if not request.get(field)]
    exchange, allowed = request.get("exchange"), EXCHANGES.get(market, ())
    if exchange and exchange not in allowed:
        errors.append(text.ERR_EXCHANGE.format(exchange=exchange, market=market, allowed=", ".join(allowed)))
    return errors


def state_errors(request: dict, company: dict | None) -> tuple[list[str], str | None]:
    """(errors, refusal code) of the event in the company's current state."""
    event, ticker, market = request["event"], request["ticker"], request["market"]
    state = company["state"] if company else None
    if state in TRANSITIONS[event][0]:
        return [], None
    if event == EVENT_ADD:
        return [text.ERR_ALREADY_ACTIVE.format(ticker=ticker, market=market, state=state)], text.REFUSE_ALREADY_ACTIVE
    if state == STATE_DELETED:
        return [text.ERR_DELETED_ONLY_ADD.format(ticker=ticker)], text.REFUSE_DELETED_NEEDS_ADD
    if state is None:
        return [text.ERR_NOT_ON_WATCHLIST.format(ticker=ticker, market=market)], text.REFUSE_VALIDATION
    return [text.ERR_TRANSITION.format(event=event, ticker=ticker, state=state)], text.REFUSE_VALIDATION


def supersedes_errors(request: dict, stored: list[dict]) -> list[str]:
    """A correction names a stored event of the same company."""
    target = request.get("supersedes")
    if target and not any(row["id"] == target and row["ticker"] == request["ticker"] for row in stored):
        return [text.ERR_SUPERSEDES.format(target=target, ticker=request["ticker"])]
    return []


def newest_effective(stored: list[dict], ticker: str) -> datetime | None:
    """effective_from of the company's newest stored event."""
    times = [parse_time(row["effective_from"]) for row in stored if row["ticker"] == ticker]
    return max(times) if times else None


def event_row(request: dict, recorded: datetime, effective: datetime, stored_ids: set[str]) -> dict:
    """The stored row (schema column order). The id's time moves on by a second while it collides."""
    while True:
        row_id = (f"{EVENT_ID_PREFIX}-{request['market']}-{request['ticker']}-{request['event']}-"
                  f"{recorded.strftime(STAMP_FORMAT)}")
        if row_id not in stored_ids:
            break
        recorded += timedelta(seconds=1)
        effective = max(effective, recorded)
    is_add = request["event"] == EVENT_ADD
    return {
        "id": row_id, "market": request["market"], "ticker": request["ticker"], "event": request["event"],
        "effective_from": iso(effective), "recorded_at": iso(recorded),
        **{field: (request.get(field) if is_add else None) for field in IDENTITY_FIELDS},
        "amount": float(request["amount"]) if request.get("amount") is not None else None,
        "currency": CURRENCY[request["market"]], "reason": request.get("reason"),
        "requested_by": request["requested_by"], "channel": request["channel"],
        "command_id": request.get("command_id"), "idempotency_key": request["idempotency_key"],
        "onboarding": request.get("onboarding") if is_add else None, "supersedes": request.get("supersedes"),
        "validator_version": VALIDATOR_VERSION,
    }
