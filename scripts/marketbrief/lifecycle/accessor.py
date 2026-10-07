"""The watchlist accessor (contracts/watchlist.py): companies by state as of a time, one company, a trade amount."""
from __future__ import annotations

from datetime import datetime

import yaml

from marketbrief.constants.config_keys import CFG_SECTORS, CFG_TICKERS
from marketbrief.constants.files import DIR_CONFIG_MARKETS, YAML_SUFFIX
from marketbrief.contracts.watchlist import DEFAULT_AMOUNT, EXCHANGES
from marketbrief.core import paths
from marketbrief.core.clock import clock
from marketbrief.lifecycle.constants import STATE_ACTIVE, STATE_COLLECTED, STATE_DELETED, STATE_INACTIVE
from marketbrief.lifecycle.events import parse_time
from marketbrief.lifecycle.identity import company_record
from marketbrief.lifecycle.loader import companies_as_of

STATES_OF = {STATE_COLLECTED: (STATE_ACTIVE, STATE_INACTIVE), STATE_ACTIVE: (STATE_ACTIVE,),
             STATE_INACTIVE: (STATE_INACTIVE,), STATE_DELETED: (STATE_DELETED,)}


def config_lists(market: str) -> tuple[dict, dict]:
    """The market config's raw `tickers:` and `sectors:` (the implicit seed of markets not yet seeded)."""
    path = paths.CONFIG / DIR_CONFIG_MARKETS / f"{market}{YAML_SUFFIX}"
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    return raw.get(CFG_TICKERS) or {}, raw.get(CFG_SECTORS) or {}


def records(market: str, as_of: datetime | None = None) -> list[dict]:
    """The Company record of every company ever added (deleted included) as of `as_of` (default: the clock)."""
    as_of = parse_time(as_of) if as_of is not None else clock()
    tickers, sectors = config_lists(market)
    out = []
    for company in companies_as_of(market, tickers, sectors, as_of).values():
        record = company_record(company)
        if record["exchange"] is None and len(EXCHANGES.get(market, ())) == 1:
            record["exchange"] = EXCHANGES[market][0]   # India: every config company is NSE-listed
        out.append(record)
    return out


def watchlist(market: str, as_of: datetime | None = None, state: str = STATE_ACTIVE) -> list[dict]:
    """The companies in `state` (active | inactive | deleted | collected) as of `as_of`, sorted by sector, ticker."""
    if state not in STATES_OF:
        raise ValueError(f"state must be one of {sorted(STATES_OF)}")
    wanted = STATES_OF[state]
    chosen = [record for record in records(market, as_of) if record["state"] in wanted]
    return sorted(chosen, key=lambda record: (record["sector"] or "", record["ticker"]))


def company(market: str, ticker: str, as_of: datetime | None = None) -> dict | None:
    """One company as of `as_of` (a deleted one with state "deleted"), or None when it was never added."""
    return next((record for record in records(market, as_of) if record["ticker"] == ticker), None)


def trade_amount(market: str, ticker: str, as_of: datetime) -> float:
    """The paper amount of one trade made at `as_of`: the override then in force, else the market default."""
    found = company(market, ticker, as_of)
    return found["amount"] if found else DEFAULT_AMOUNT.get(market)
