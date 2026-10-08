"""Reading the stored watchlist events and folding them into each company's state as of a time (F8.2).

Visibility (no look-ahead): an event counts as of T when effective_from <= T and recorded_at <= T. The one exception
is the seed (channel `seed`): its add events restate the config's `tickers:` list that every run before the seeding
already used, so they count from their effective_from (the start of stored history) even before their recorded_at;
without it a replay dated before the seeding would see an empty watchlist once Wave 5 removes `tickers:`.
A row whose id a visible row `supersedes` is dropped. Per company the events apply in order of effective_from,
then recorded_at, then id (contracts/watchlist.py); an event the state does not allow is skipped (the validator
refuses those before they are stored). Implicit seed (test fixtures and markets not yet seeded keep working
unchanged): companies of a legacy `tickers:` config without any stored add event act as adds from the start of time;
`company_meta:` entries (Wave 5) do so only while the market has no stored seed event (channel `seed`, whatever its
visibility as of T), so in a seeded market membership comes from the events alone and a company_meta entry never
adds a company."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.constants.kinds import KIND_WATCHLIST_EVENTS
from marketbrief.core import paths
from marketbrief.lifecycle.constants import (
    CHANNEL_SEED,
    EVENT_ADD,
    EVENT_SET_AMOUNT,
    IDENTITY_FIELDS,
    STATE_DELETED,
    TRANSITIONS,
)

BEGINNING = datetime(1900, 1, 1, tzinfo=timezone.utc)


def parse_time(value) -> datetime:
    """An ISO 8601 time (or datetime) as an aware UTC datetime."""
    if isinstance(value, datetime):
        stamp = value
    else:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def stored_events(market: str) -> list[dict]:
    """Every stored event of the market in file order (day files sorted, lines in order); `_order` keeps it."""
    rows = []
    for path in sorted((paths.data_dir(market) / KIND_WATCHLIST_EVENTS).glob(JSONL_GLOB)):
        for line in path.read_text(encoding=ENCODING_UTF8).splitlines():
            if line.strip():
                rows.append({**json.loads(line), "_order": len(rows)})
    return rows


def is_visible(row: dict, as_of: datetime) -> bool:
    """True when the event counts as of `as_of` (see the module docstring)."""
    if parse_time(row["effective_from"]) > as_of:
        return False
    return row.get("channel") == CHANNEL_SEED or parse_time(row["recorded_at"]) <= as_of


def visible_events(rows: list[dict], as_of: datetime) -> list[dict]:
    """The rows that count as of `as_of`, minus those a counting row supersedes."""
    seen = [row for row in rows if is_visible(row, as_of)]
    superseded = {row["supersedes"] for row in seen if row.get("supersedes")}
    return [row for row in seen if row["id"] not in superseded]


def event_order(row: dict) -> tuple:
    """The order in which one company's events apply."""
    return parse_time(row["effective_from"]), parse_time(row["recorded_at"]), str(row["id"])


def apply_event(company: dict | None, row: dict) -> dict | None:
    """The company after one event, or unchanged when the event is not allowed in its state."""
    allowed, new_state = TRANSITIONS.get(row["event"], ((), None))
    state = company["state"] if company else None
    if state not in allowed:
        return company
    effective = parse_time(row["effective_from"])
    if row["event"] == EVENT_ADD:
        identity = {field: row.get(field) for field in IDENTITY_FIELDS}
        added_at = company["added_at"] if company else effective
        return {"market": row["market"], "ticker": row["ticker"], **identity, "state": new_state,
                "amount": row.get("amount"), "added_at": added_at, "state_since": effective,
                "first_order": company["first_order"] if company else row.get("_order", -1)}
    updated = dict(company)
    if row["event"] == EVENT_SET_AMOUNT:
        updated["amount"] = row.get("amount")
    else:
        updated["state"], updated["state_since"] = new_state, effective
    return updated


def fold(rows: list[dict], as_of: datetime) -> dict[str, dict]:
    """{ticker: company} as of `as_of`, deleted companies included (state "deleted"), in order of first add."""
    by_ticker: dict[str, list[dict]] = {}
    for row in visible_events(rows, as_of):
        by_ticker.setdefault(row["ticker"], []).append(row)
    companies = {}
    for ticker, events in by_ticker.items():
        company = None
        for row in sorted(events, key=event_order):
            company = apply_event(company, row)
        if company:
            companies[ticker] = company
    return dict(sorted(companies.items(), key=lambda item: item[1]["first_order"]))


def implicit_adds(market: str, config_tickers: dict, config_sectors: dict, stored: list[dict],
                  meta_only: bool = False) -> list[dict]:
    """Add rows for the config companies that have no stored add event (they act from the start of time); for
    `company_meta:` (meta_only) none once the market has a stored seed event (see the module docstring)."""
    if meta_only and any(row.get("channel") == CHANNEL_SEED for row in stored):
        return []
    added = {row["ticker"] for row in stored if row.get("event") == EVENT_ADD}
    sector_of = {ticker: sector for sector, members in (config_sectors or {}).items() for ticker in members or []}
    rows = []
    for order, (ticker, meta) in enumerate((config_tickers or {}).items()):
        if ticker in added:
            continue
        meta = meta or {}
        rows.append({"id": f"config-{market}-{ticker}", "market": market, "ticker": ticker, "event": EVENT_ADD,
                     "effective_from": BEGINNING, "recorded_at": BEGINNING, "channel": CHANNEL_SEED,
                     "name": meta.get("name"), "yahoo": meta.get("yahoo", ticker), "sector": sector_of.get(ticker),
                     "exchange": None, "nse_symbol": meta.get("nse"), "cik": None, "amount": None,
                     "_order": order - len(config_tickers)})   # before every stored row
    return rows


def not_deleted(companies: dict[str, dict]) -> dict[str, dict]:
    """The companies that are collected (active or inactive)."""
    return {ticker: company for ticker, company in companies.items() if company["state"] != STATE_DELETED}
