"""Per-trade costs in the market's currency, from the rates of config/costs.yaml (the signal model's paper
strategy uses the same rates as a round-trip fraction: model/settings.py round_trip_cost).

India (equity delivery), each side: value x (brokerage + exchange txn + SEBI fee) x (1 + GST) + value x STT
+ value x slippage; the buy side adds stamp duty. US: each side commission + slippage; the sell side adds the
SEC Section 31 fee and the FINRA TAF (per share, capped per trade). A buy and a sell of the same value add up
to round_trip_cost (tested)."""
from __future__ import annotations

from marketbrief.portfolio.constants import SIDE_BUY


def india_side_rate(costs: dict, side: str) -> float:
    """The cost fraction of one side of an NSE delivery trade."""
    taxable = costs["brokerage_each_side"] + costs["exchange_txn_each_side"] + costs["sebi_fee_each_side"]
    rate = taxable * (1 + costs["gst_rate"]) + costs["stt_each_side"] + costs["slippage_each_side"]
    return rate + (costs["stamp_duty_buy"] if side == SIDE_BUY else 0.0)


def us_side_cost(costs: dict, side: str, quantity: float, price: float) -> float:
    """The cost in USD of one side of a US equity trade of `quantity` shares at `price`."""
    value = quantity * price
    cost = value * (costs["commission_each_side"] + costs["slippage_each_side"])
    if side != SIDE_BUY:
        taf = min(costs["finra_taf_per_share_sell"] * quantity, costs["finra_taf_max_per_trade"])
        cost += value * costs["sec_fee_sell"] + taf
    return cost


def trade_cost(market: str, costs: dict, side: str, quantity: float, price: float) -> float:
    """The cost in the market's currency of one buy or sell of `quantity` at `price`."""
    if market == "india":
        return quantity * price * india_side_rate(costs, side)
    return us_side_cost(costs, side, quantity, price)
