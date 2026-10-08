"""Per-trade costs of the owner's paper portfolio in the market's currency: the same charges as the paper-trading
engine (marketbrief/lab/costs.py, F1.11: "reads costs from the same place"): config/costs.yaml's statutory rates
plus the broker charges under `broker` (provisional, marked verify). With the statutory rates alone (no `broker`
keys) a buy and a sell of the same value add up to the signal model's round_trip_cost (tested).

India ("your cost" view, owner decision 50): brokerage (at least the minimum per order), STT, exchange, SEBI, GST
on (brokerage + exchange + SEBI), slippage, the NRI reporting charge of the trade date; the buy adds stamp duty,
the sell the DP charge. US: the BUX order fee in EUR converted at `eurusd` (USD per EUR), commission and slippage;
the sell adds the SEC fee and the FINRA TAF; the FX markup is applied in the EUR view; the portfolio fee (per lot
and day held) is charged in ledger.py."""
from __future__ import annotations

from marketbrief.lab.costs import VIEW_YOUR, side_cost


def trade_cost(market: str, costs: dict, side: str, quantity: float, price: float, eurusd: float | None = None,
               ) -> float:
    """The cost in the market's currency of one buy or sell of `quantity` at `price`, in the "your cost" view
    (owner decision 50: the owner's money uses it; the US FX markup is in the EUR view)."""
    return side_cost(market, costs, side, quantity, price, {"eurusd": eurusd, "view": VIEW_YOUR})
