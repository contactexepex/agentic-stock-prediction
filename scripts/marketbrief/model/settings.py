"""The signal model's settings (config/model.yaml) and round-trip trading costs (config/costs.yaml)."""
from __future__ import annotations

import numpy as np
import yaml

from marketbrief.constants.model import FILE_COSTS_CONFIG, FILE_MODEL_CONFIG, MSG_NO_MODEL_CONFIG
from marketbrief.core import paths


def read_config(name: str) -> dict:
    """config/<name> as parsed; exits with a message when it is missing."""
    path = paths.CONFIG / name
    if not path.exists():
        raise SystemExit(MSG_NO_MODEL_CONFIG.format(name=name))
    return yaml.safe_load(path.read_text())


def load_model_config() -> dict:
    """config/model.yaml (regularisation, warm-up, refit, news priors, backtest settings)."""
    return read_config(FILE_MODEL_CONFIG)


def load_costs(market: str) -> dict:
    """The market's section of config/costs.yaml."""
    return read_config(FILE_COSTS_CONFIG)[market]


def india_round_trip(costs: dict) -> float:
    """Buy plus sell cost of an equity delivery trade on NSE, as a fraction of traded value.
    Each side: brokerage + STT + exchange transaction + SEBI fee + GST on (brokerage + exchange + SEBI)
    + slippage; the buy side adds stamp duty."""
    taxable = costs["brokerage_each_side"] + costs["exchange_txn_each_side"] + costs["sebi_fee_each_side"]
    side = taxable + costs["stt_each_side"] + costs["gst_rate"] * taxable + costs["slippage_each_side"]
    return 2 * side + costs["stamp_duty_buy"]


def us_round_trip(costs: dict, price):
    """Buy plus sell cost of a US equity trade as a fraction of traded value: commissions, the SEC
    Section 31 fee and the FINRA TAF on the sale (per share, capped per trade, for notional_per_trade
    at `price`), and slippage on both sides. `price` may be a number or an array."""
    price = np.asarray(price, dtype=float)
    shares = costs["notional_per_trade"] / price
    taf = np.minimum(costs["finra_taf_per_share_sell"] * shares, costs["finra_taf_max_per_trade"])
    out = (2 * costs["commission_each_side"] + costs["sec_fee_sell"] + taf / costs["notional_per_trade"]
           + 2 * costs["slippage_each_side"])
    return float(out) if out.ndim == 0 else out


def round_trip_cost(market: str, costs: dict, price=100.0):
    """The round-trip cost fraction of one position in `market` entered at `price`."""
    if market == "india":
        cost = india_round_trip(costs)
        return cost if np.ndim(price) == 0 else np.full(np.shape(price), cost)
    return us_round_trip(costs, price)
