"""A company's identity as config meta and as the watchlist accessor's Company record."""
from __future__ import annotations

from marketbrief.constants.config_keys import META_NSE_SYMBOL, META_YAHOO
from marketbrief.contracts.watchlist import CURRENCY, DEFAULT_AMOUNT


def meta_from_identity(company: dict) -> dict:
    """The config meta of a company known only from its add event: name, Yahoo symbol, exchange, NSE symbol, CIK."""
    meta = {"name": company.get("name") or company["ticker"], META_YAHOO: company.get("yahoo") or company["ticker"]}
    if company.get("exchange"):
        meta["exchange"] = company["exchange"]
    if company.get("nse_symbol"):
        meta[META_NSE_SYMBOL] = company["nse_symbol"]
    if company.get("cik"):
        meta["cik"] = company["cik"]
    return meta


def company_record(company: dict) -> dict:
    """The contracts.watchlist.Company record of a folded company (amount and currency None for a market without a
    default, e.g. a test market)."""
    market = company["market"]
    override = company.get("amount")
    return {
        "market": market, "ticker": company["ticker"], "name": company.get("name") or company["ticker"],
        "exchange": company.get("exchange"), "sector": company.get("sector"), "state": company["state"],
        "amount": float(override) if override is not None else DEFAULT_AMOUNT.get(market),
        "amount_overridden": override is not None, "currency": CURRENCY.get(market),
        "yahoo": company.get("yahoo") or company["ticker"], "nse_symbol": company.get("nse_symbol"),
        "cik": company.get("cik"), "added_at": company["added_at"], "state_since": company["state_since"],
    }
