"""The F1 protocol with exactly the signatures of marketbrief/contracts/protocol.py (W1), for callers that code
against the contract (B3's traders, B9's checks, B4's read models). Each delegates to the lab's modules; the
stored inputs are read as of the given time through lab/reads.py."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.contracts.protocol import Candidate, Costs, PickRule, View
from marketbrief.core.clock import clock
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.lab import costs as lab_costs
from marketbrief.lab import picks as lab_picks
from marketbrief.lab import reads, registry
from marketbrief.lab import settle as lab_settle
from marketbrief.lab import sizing, timing
from marketbrief.lab.market_data import MarketData
from marketbrief.portfolio.fx import EurUsd

entry_session = timing.entry_session
exit_session = timing.exit_session
is_locked = timing.is_locked
qualifies = sizing.qualifies
quantity = sizing.quantity
WINDOW_DAYS_BEFORE_D = 10


def round_trip_costs(market: str, entry_value: float, exit_value: float, quantity: float,  # noqa: A002
                     on_date: date) -> Costs:
    """F1.6 with config/costs.yaml's rates; US: both orders converted at the EUR/USD close on or before on_date."""
    rate = lab_costs.rates(market)
    eurusd = (None, None)
    if rate.get("order_fee_eur"):
        fx = EurUsd(connect(market), load_market(market), clock(), rate.get("eurusd_symbol"))
        eurusd = (fx.on(on_date), fx.on(on_date))
    return lab_costs.round_trip_costs(market, rate, entry_value, exit_value, quantity, eurusd)


def settle(prediction: dict, view: View, pick: dict | None, cfg: dict, settled_at: datetime) -> dict:
    """One paper_trades_settled row from the bars, splits, EUR/USD, beta and news stored by settled_at (None while
    not due)."""
    con = connect(cfg["market"])
    start = lab_settle.as_date(prediction["session_date"]) - timedelta(days=WINDOW_DAYS_BEFORE_D)
    data: MarketData = reads.market_data(con, cfg, settled_at, [prediction["ticker"]], start)
    beta = reads.betas_asof(con, settled_at).get((prediction["ticker"], str(prediction["as_of_date"])))
    data.betas = {} if beta is None else {prediction["ticker"]: beta}
    return lab_settle.settle(prediction, view, pick, data, settled_at)


def strongest(market: str, family: str, ticker: str, as_of: datetime) -> list[dict]:
    """The decision-41 ranking (corrected: no record ranks last) from the settlements stored by as_of."""
    ids = [spec["id"] for spec in registry.strategies(family=family)]
    return lab_picks.ranking(ids, ticker, reads.settlements(connect(market), as_of))


def pick(candidates: list[Candidate], rule: PickRule) -> Candidate | None:
    """F1.7.3 (corrected): best_expected_gain by gain per session held, highest_probability by prob_up."""
    return lab_picks.pick(candidates, rule)
