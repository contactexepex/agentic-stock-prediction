"""F1.6 costs of one paper trade in the market currency: the statutory rates of config/costs.yaml (`india`, `us`)
plus the owner's broker charges (`broker`, provisional, each marked verify). Every strategy and the owner's
portfolio pay the same charges, so strategies stay comparable before the owner confirms them.

India (Axis Direct, equity delivery), on entry value B and exit value S:
  brokerage = rate x (B + S); stt = rate x (B + S); exchange = rate x (B + S); sebi = rate x (B + S);
  stamp_duty = rate x B; dp_charge = max(dp_charge_min, dp_charge_rate x S) on the sale;
  gst = gst_rate x (brokerage + exchange + sebi + dp_charge); slippage = rate x (B + S).
US (BUX), in USD: order_fee = order_fee_eur x EUR/USD of each side's session (two orders);
  sec_fee = rate x S; finra_taf = min(per share x quantity, max per trade); commission and slippage x (B + S).
Each line is rounded to cents and the total is the sum of the rounded lines."""
from __future__ import annotations

from marketbrief.lab.constants import MONEY_DIGITS
from marketbrief.model.settings import read_config

FILE_COSTS = "costs.yaml"
KEY_BROKER = "broker"


def rates(market: str, config: dict | None = None) -> dict:
    """The market's statutory rates merged with its broker charges (broker values win)."""
    config = config or read_config(FILE_COSTS)
    return {**config[market], **(config.get(KEY_BROKER) or {}).get(market, {})}


def _money(lines: dict[str, float]) -> dict:
    """{total, lines} with each line rounded to cents."""
    rounded = {key: round(value, MONEY_DIGITS) + 0.0 for key, value in lines.items()}
    return {"total": round(sum(rounded.values()), MONEY_DIGITS) + 0.0, "lines": rounded}


def india_lines(rate: dict, entry_value: float, exit_value: float) -> dict[str, float]:
    """The unrounded cost lines of an NSE delivery round trip (exit_value 0: buy side only)."""
    both = entry_value + exit_value
    brokerage = rate.get("brokerage_each_side", 0.0) * both
    exchange = rate["exchange_txn_each_side"] * both
    sebi = rate["sebi_fee_each_side"] * both
    dp = max(rate.get("dp_charge_min", 0.0), rate.get("dp_charge_rate", 0.0) * exit_value) if exit_value else 0.0
    return {"brokerage": brokerage, "stt": rate["stt_each_side"] * both, "exchange": exchange, "sebi": sebi,
            "stamp_duty": rate["stamp_duty_buy"] * entry_value, "dp_charge": dp,
            "gst": rate["gst_rate"] * (brokerage + exchange + sebi + dp),
            "slippage": rate.get("slippage_each_side", 0.0) * both}


def us_lines(rate: dict, values: tuple[float, float], quantity: float,
             eurusd: tuple[float | None, float | None]) -> dict[str, float]:
    """The unrounded cost lines of a US round trip (values = entry, exit value; eurusd per side, None = no
    order on that side). Raises ValueError when an order's EUR/USD rate is missing."""
    entry_value, exit_value = values
    fee = rate.get("order_fee_eur", 0.0)
    orders = [rate_ for value, rate_ in zip(values, eurusd) if value]
    if fee and any(rate_ is None for rate_ in orders):
        raise ValueError("EUR/USD rate missing for the BUX order fee")
    lines = {"order_fee": sum(fee * rate_ for rate_ in orders if rate_ is not None)}
    lines["sec_fee"] = rate["sec_fee_sell"] * exit_value
    if exit_value:
        lines["finra_taf"] = min(rate["finra_taf_per_share_sell"] * quantity, rate["finra_taf_max_per_trade"])
    both = entry_value + exit_value
    lines["commission"] = rate.get("commission_each_side", 0.0) * both
    lines["slippage"] = rate.get("slippage_each_side", 0.0) * both
    return lines


def round_trip_costs(market: str, rate: dict, entry_value: float, exit_value: float, quantity: float,
                     eurusd: tuple[float | None, float | None] = (None, None)) -> dict:
    """F1.6: {total, lines} of one trade (contracts/protocol.py `Costs`); zero lines are dropped."""
    if market == "india":
        lines = india_lines(rate, entry_value, exit_value)
    else:
        lines = us_lines(rate, (entry_value, exit_value), quantity, eurusd)
    return _money({key: value for key, value in lines.items() if value})


def side_cost(market: str, rate: dict, side: str, quantity: float, price: float, eurusd: float | None = None) -> float:
    """The unrounded cost of one buy or sell (the owner's portfolio ledger), from the same lines."""
    value = quantity * price
    values = (value, 0.0) if side == "buy" else (0.0, value)
    if market == "india":
        lines = india_lines(rate, *values)
    else:
        lines = us_lines(rate, values, quantity, (eurusd, eurusd))
    return float(sum(lines.values()))
