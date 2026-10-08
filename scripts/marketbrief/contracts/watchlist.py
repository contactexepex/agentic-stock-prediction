"""The watchlist accessor (docs/SPEC.md F8.2; W1 interface, session B1 builds it in `marketbrief/lifecycle/`).

The company list lives in the append-only kind `watchlist_events` (schema in core/schema_lifecycle.py);
config/markets/<market>.yaml keeps only per-company metadata under `company_meta:` (formerly `tickers:`). A
company's state as of a time is the newest event with effective_from <= as_of among those recorded by as_of
(recorded_at <= as_of), so a replay with MB_NOW sees only what was known then. "Newest" orders by effective_from,
then recorded_at, then id; the validator refuses an event whose effective_from is before the company's newest stored
event, so a later request can never take effect earlier. One exception (B1): the seed's add events (channel `seed`)
count from their effective_from even before their recorded_at, because they restate the config list every earlier
run used (marketbrief/lifecycle/events.py):

- add, reactivate -> active (collected, predicted, traded)
- deactivate      -> inactive (collected, not predicted or traded; shown only in the Companies page's Inactive part)
- delete          -> deleted (tombstone: not collected, never shown, excluded on read everywhere)
- set_amount      -> state unchanged; amount changed (null = the market default)

The loader `load_market` (core/market_config.py, B1) then sets cfg["tickers"] = every collected company (active and
inactive), cfg["sectors"] rebuilt from the add events' sectors, and cfg["active_tickers"] = active only."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

CompanyState = Literal["active", "inactive", "deleted"]
STATES: tuple[str, ...] = ("active", "inactive", "deleted")
EVENTS: tuple[str, ...] = ("add", "deactivate", "reactivate", "delete", "set_amount")
CHANNELS: tuple[str, ...] = ("dashboard", "slack", "claude_code", "claude_app", "cli", "seed")
EXCHANGES: dict[str, tuple[str, ...]] = {"india": ("NSE",), "us": ("NYSE", "NASDAQ")}   # decision 14
DEFAULT_AMOUNT: dict[str, float] = {"india": 100000.0, "us": 1000.0}   # decisions 26, 44
CURRENCY: dict[str, str] = {"india": "INR", "us": "USD"}
CFG_ACTIVE_TICKERS = "active_tickers"   # the new loader key (B1)


class Company(TypedDict):
    """One company as of a time. amount: the effective per-trade paper amount (the override, else the market
    default); amount_overridden tells which. yahoo/nse_symbol/cik: identifiers resolved at onboarding (nse_symbol
    India only, cik US only, else None). added_at: effective_from of its first add event; state_since:
    effective_from of the event that set the current state."""

    market: str
    ticker: str
    name: str
    exchange: str
    sector: str
    state: CompanyState
    amount: float
    amount_overridden: bool
    currency: str
    yahoo: str
    nse_symbol: str | None
    cik: str | None
    added_at: datetime
    state_since: datetime


def watchlist(market: str, as_of: datetime | None = None, state: CompanyState | Literal["collected"] = "active",
              ) -> list[Company]:
    """The market's companies in `state` as of `as_of` (default: the run's clock, MB_NOW-aware), sorted by sector
    then ticker. state "collected" = active and inactive (what the collectors read); "deleted" is only for the
    purge of derived stores, never for display."""
    from marketbrief.lifecycle import accessor  # imported here: lifecycle imports this module

    return accessor.watchlist(market, as_of, state)


def company(market: str, ticker: str, as_of: datetime | None = None) -> Company | None:
    """One company as of `as_of`, or None when it was never added (a deleted company is returned with state
    "deleted" so callers can refuse it explicitly)."""
    from marketbrief.lifecycle import accessor  # imported here: lifecycle imports this module

    return accessor.company(market, ticker, as_of)


def trade_amount(market: str, ticker: str, as_of: datetime) -> float:
    """The paper amount of one trade made at `as_of` (F1.3): the override active at as_of, else DEFAULT_AMOUNT."""
    from marketbrief.lifecycle import accessor  # imported here: lifecycle imports this module

    return accessor.trade_amount(market, ticker, as_of)
