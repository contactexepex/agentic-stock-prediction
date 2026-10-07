"""F1.2-F1.4: which predictions trade, the amount per trade and the quantity bought at D's raw open."""
from __future__ import annotations

import math
from datetime import datetime

from marketbrief.contracts import watchlist as watchlist_contract
from marketbrief.contracts.protocol import QUANTITY_DECIMALS
from marketbrief.lab.constants import UP



def qualifies(prediction: dict) -> bool:
    """F1.2: direction up and prob_up >= threshold (no probability, i.e. always-up and momentum: direction up)."""
    if prediction.get("direction") != UP:
        return False
    prob, threshold = prediction.get("prob_up"), prediction.get("threshold")
    return prob is None or threshold is None or float(prob) >= float(threshold)


def trade_amount(market: str, ticker: str, as_of: datetime) -> float:
    """F1.3: the company's paper amount at `as_of` through B1's accessor (contracts/watchlist.trade_amount): the
    set_amount override in force (which may raise or lower it, decision 44), else the market default."""
    return float(watchlist_contract.trade_amount(market, ticker, as_of))


def quantity(market: str, amount: float, entry_open: float) -> float:
    """F1.4: India floor(amount / open) whole shares (0 = skipped_price_above_amount); US amount / open to 6
    decimals (fractional: exactly the amount is invested)."""
    if market == "india":
        return float(math.floor(amount / entry_open))
    return round(amount / entry_open, QUANTITY_DECIMALS[market])
