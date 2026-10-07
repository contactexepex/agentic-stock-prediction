"""config/portfolio.yaml and the market's costs (config/costs.yaml: the statutory rates plus the broker charges,
the same as the paper-trading engine's, marketbrief/lab/costs.py)."""
from __future__ import annotations

from marketbrief.lab.costs import rates
from marketbrief.model.settings import read_config
from marketbrief.portfolio.constants import FILE_PORTFOLIO_CONFIG


def load_portfolio_config() -> dict:
    """config/portfolio.yaml as parsed (trades, proof, tiers, paper_follow)."""
    return read_config(FILE_PORTFOLIO_CONFIG)


def market_costs(market: str) -> dict:
    """The market's statutory rates merged with its broker charges (config/costs.yaml)."""
    return rates(market)
