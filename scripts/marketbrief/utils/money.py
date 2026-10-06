"""Money formatting."""
from __future__ import annotations

import math

from marketbrief.constants.formatting import CURRENCY_SYMBOLS, MISSING_VALUE_DASH


def format_money(currency: str, amount) -> str:
    """'$1,234.50' / '₹1,234.50' for an amount in the currency; a dash for None and NaN."""
    if amount is None or (isinstance(amount, float) and math.isnan(amount)):
        return MISSING_VALUE_DASH
    return f"{CURRENCY_SYMBOLS.get(currency, '')}{amount:,.2f}"
