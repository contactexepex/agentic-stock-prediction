"""config/portfolio.yaml and the market's costs (config/costs.yaml, the signal model's rates)."""
from __future__ import annotations

from marketbrief.model.settings import load_costs, read_config
from marketbrief.portfolio.constants import FILE_PORTFOLIO_CONFIG


def load_portfolio_config() -> dict:
    """config/portfolio.yaml as parsed (trades, proof, tiers, paper_follow)."""
    return read_config(FILE_PORTFOLIO_CONFIG)


def market_costs(market: str) -> dict:
    """The market's section of config/costs.yaml."""
    return load_costs(market)
