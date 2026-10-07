"""F1.2-F1.4: which predictions trade, the amount per trade and the quantity bought at D's raw open."""
from __future__ import annotations

import math
from datetime import datetime

from marketbrief.contracts import watchlist as watchlist_contract
from marketbrief.contracts.protocol import QUANTITY_DECIMALS
from marketbrief.contracts.watchlist import DEFAULT_AMOUNT
from marketbrief.lab.constants import UP

KEY_AMOUNT = "amount"   # optional per-ticker override in the market config until B1's watchlist events exist


def qualifies(prediction: dict) -> bool:
    """F1.2: direction up and prob_up >= threshold (no probability, i.e. always-up and momentum: direction up)."""
    if prediction.get("direction") != UP:
        return False
    prob, threshold = prediction.get("prob_up"), prediction.get("threshold")
    return prob is None or threshold is None or float(prob) >= float(threshold)


def trade_amount(market: str, ticker: str, as_of: datetime, cfg: dict | None = None) -> float:
    """F1.3: the company's paper amount at `as_of` through B1's accessor (contracts/watchlist.trade_amount);
    until B1 has built it, the market config's per-ticker `amount` when set, else the market default."""
    try:
        return float(watchlist_contract.trade_amount(market, ticker, as_of))
    except NotImplementedError:
        meta = ((cfg or {}).get("tickers") or {}).get(ticker) or {}
        override = meta.get(KEY_AMOUNT)
        return float(override) if override else DEFAULT_AMOUNT[market]


def quantity(market: str, amount: float, entry_open: float) -> float:
    """F1.4: India floor(amount / open) whole shares (0 = skipped_price_above_amount); US amount / open to 6
    decimals (fractional: exactly the amount is invested)."""
    if market == "india":
        return float(math.floor(amount / entry_open))
    return round(amount / entry_open, QUANTITY_DECIMALS[market])
