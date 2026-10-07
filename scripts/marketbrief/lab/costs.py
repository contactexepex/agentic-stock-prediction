"""F1.6 costs of one paper trade in the market currency, in the two views of owner decision 50, from
config/costs.yaml: the statutory rates (`india`, `us`) plus the broker charges (`broker`, owner-provided, each
marked verify).

market view (what any investor pays; strategies are ranked on it), on entry value B and exit value S:
  India (Axis Direct): brokerage = max(rate x value, min per order) on each side; stt = rate x (B + S); exchange =
    rate x (B + S); sebi = rate x (B + S); stamp_duty = rate x B; gst = gst_rate x (brokerage + exchange + sebi);
    slippage = rate x (B + S).
  US (BUX): order_fee = order_fee_eur x the EUR/USD close of each side's session (two orders); sec_fee = rate x S;
    finra_taf = min(per share x quantity, max per trade); commission and slippage x (B + S).
your view = market + the owner-specific items:
  India: nri_reporting = Rs per trade date, once on the purchase date and once on the sale date; dp_charge =
    max(dp_charge_min, dp_charge_rate x S) on the sale.
  US: fx_markup = fx_fee_rate x (B + S) (EUR->USD on the buy, USD->EUR on the sale); portfolio_fee =
    portfolio_fee_per_year x B x holding days / 365.
Each line is rounded to cents and a view's total is the sum of its rounded lines. A trade with only one side
(exit value 0) gets that side's lines only."""
from __future__ import annotations

from marketbrief.lab.constants import MONEY_DIGITS
from marketbrief.model.settings import read_config

FILE_COSTS = "costs.yaml"
KEY_BROKER = "broker"
VIEW_MARKET, VIEW_YOUR = "market", "your"
DAYS_PER_YEAR = 365.0


class MissingEurUsdError(ValueError):
    """No EUR/USD close is stored to convert the BUX order fee."""


def rates(market: str, config: dict | None = None) -> dict:
    """The market's statutory rates merged with its broker charges (broker values win)."""
    config = config or read_config(FILE_COSTS)
    return {**config[market], **(config.get(KEY_BROKER) or {}).get(market, {})}


def _money(lines: dict[str, float]) -> dict:
    """{total, lines} with each non-zero line rounded to cents."""
    rounded = {key: round(value, MONEY_DIGITS) + 0.0 for key, value in lines.items() if value}
    return {"total": round(sum(rounded.values()), MONEY_DIGITS) + 0.0, "lines": rounded}


def brokerage(rate: dict, value: float) -> float:
    """One order's brokerage: rate x value, at least the minimum per order (0 for no order)."""
    if not value:
        return 0.0
    return max(rate.get("brokerage_each_side", 0.0) * value, rate.get("brokerage_min_per_order", 0.0))


def india_lines(rate: dict, entry_value: float, exit_value: float) -> dict[str, float]:
    """The unrounded market-view lines of an NSE delivery trade (exit_value 0: buy side only)."""
    both = entry_value + exit_value
    fee = brokerage(rate, entry_value) + brokerage(rate, exit_value)
    exchange = rate["exchange_txn_each_side"] * both
    sebi = rate["sebi_fee_each_side"] * both
    return {"brokerage": fee, "stt": rate["stt_each_side"] * both, "exchange": exchange, "sebi": sebi,
            "stamp_duty": rate["stamp_duty_buy"] * entry_value, "gst": rate["gst_rate"] * (fee + exchange + sebi),
            "slippage": rate.get("slippage_each_side", 0.0) * both}


def india_your_lines(rate: dict, entry_value: float, exit_value: float) -> dict[str, float]:
    """The owner-specific India lines: the NRI reporting charge per trade date and the DP charge on the sale."""
    reporting = rate.get("nri_reporting_per_trade_date", 0.0)
    out = {"nri_reporting_buy": reporting if entry_value else 0.0,
           "nri_reporting_sell": reporting if exit_value else 0.0}
    if exit_value:
        out["dp_charge"] = max(rate.get("dp_charge_min", 0.0), rate.get("dp_charge_rate", 0.0) * exit_value)
    return out


def us_lines(rate: dict, values: tuple[float, float], quantity: float,
             eurusd: tuple[float | None, float | None]) -> dict[str, float]:
    """The unrounded market-view lines of a US trade (values = entry, exit value; eurusd per side). Raises
    MissingEurUsdError when an order's EUR/USD rate is missing."""
    entry_value, exit_value = values
    fee = rate.get("order_fee_eur", 0.0)
    orders = [rate_ for value, rate_ in zip(values, eurusd) if value]
    if fee and any(rate_ is None for rate_ in orders):
        raise MissingEurUsdError("EUR/USD rate missing for the BUX order fee")
    lines = {"order_fee": sum(fee * rate_ for rate_ in orders if rate_ is not None)}
    lines["sec_fee"] = rate["sec_fee_sell"] * exit_value
    if exit_value:
        lines["finra_taf"] = min(rate["finra_taf_per_share_sell"] * quantity, rate["finra_taf_max_per_trade"])
    both = entry_value + exit_value
    lines["commission"] = rate.get("commission_each_side", 0.0) * both
    lines["slippage"] = rate.get("slippage_each_side", 0.0) * both
    return lines


def us_your_lines(rate: dict, entry_value: float, exit_value: float, holding_days: int) -> dict[str, float]:
    """The owner-specific US lines: the FX markup each way and the pro-rated portfolio fee."""
    return {"fx_markup": rate.get("fx_fee_rate", 0.0) * (entry_value + exit_value),
            "portfolio_fee": rate.get("portfolio_fee_per_year", 0.0) * entry_value * holding_days / DAYS_PER_YEAR}


def cost_views(market: str, rate: dict, values: tuple[float, float], quantity: float,
               extra: dict | None = None) -> dict:
    """{market: {total, lines}, your: {total, lines}} of one trade. values = (entry, exit value); extra: eurusd =
    (entry rate, exit rate) for the US order fee, holding_days for the US portfolio fee."""
    extra = extra or {}
    entry_value, exit_value = values
    if market == "india":
        base, own = india_lines(rate, entry_value, exit_value), india_your_lines(rate, entry_value, exit_value)
    else:
        base = us_lines(rate, values, quantity, extra.get("eurusd", (None, None)))
        own = us_your_lines(rate, entry_value, exit_value, int(extra.get("holding_days", 0)))
    market_view = _money(base)
    own_view = _money(own)
    your_lines = {**market_view["lines"], **own_view["lines"]}
    return {VIEW_MARKET: market_view,
            VIEW_YOUR: {"total": round(market_view["total"] + own_view["total"], MONEY_DIGITS) + 0.0,
                        "lines": your_lines}}


def round_trip_costs(market: str, rate: dict, entry_value: float, exit_value: float, quantity: float,
                     eurusd: tuple[float | None, float | None] = (None, None)) -> dict:
    """F1.6 market view: {total, lines} of one trade (contracts/protocol.py `Costs`)."""
    return cost_views(market, rate, (entry_value, exit_value), quantity, {"eurusd": eurusd})[VIEW_MARKET]


def side_cost(market: str, rate: dict, side: str, quantity: float, price: float, extra: dict | None = None) -> float:
    """The unrounded cost of one buy or sell (the owner's portfolio ledger). extra: eurusd (the US order fee's
    rate), view (market or your). India's your view adds the reporting charge of that trade date and, on a sale,
    the DP charge; the US FX markup is left to the EUR view (portfolio/eur_view.py)."""
    extra = extra or {}
    eurusd, view = extra.get("eurusd"), extra.get("view", VIEW_MARKET)
    value = quantity * price
    values = (value, 0.0) if side == "buy" else (0.0, value)
    if market == "india":
        lines = india_lines(rate, *values)
        if view == VIEW_YOUR:
            lines.update(india_your_lines(rate, *values))
    else:
        lines = us_lines(rate, values, quantity, (eurusd, eurusd))
    return float(sum(lines.values()))
