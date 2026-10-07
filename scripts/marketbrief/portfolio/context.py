"""The run context every portfolio function takes, and the input of one paper trade."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from marketbrief.core.clock import clock as run_clock
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.portfolio.settings import load_portfolio_config, market_costs


@dataclass
class Context:
    """What every portfolio function needs, all fixed at the start of a run (con is reopened after a write)."""
    market: str
    cfg: dict
    con: object
    clock: datetime
    settings: dict
    costs: dict


@dataclass
class TradeInput:
    """One paper trade as asked for (validated by service.add_trade before anything is stored)."""
    ticker: str
    side: str
    quantity: float
    trade_date: date
    price_basis: str
    source: str
    price: float | None = None
    note: str | None = None
    supersedes: str | None = None
    idempotency_key: str | None = None
    submitted_by: str | None = None    # the channel identity (inbox import); never typed in
    command_id: str | None = None      # the web tier's command id of the inbox row


def context(market: str) -> Context:
    """The live context of `market` (MB_NOW freezes the clock)."""
    return Context(market, load_market(market), connect(market), run_clock(), load_portfolio_config(),
                   market_costs(market))
