"""The F1 paper-trading protocol: one engine for every strategy (docs/SPEC.md F1; W1 interface, session B2 builds
it in `marketbrief/lab/`). Research only: a paper trade is a record, never an order. The engine is the only place
P&L is computed. Stored rows: `strategy_predictions`, `head_to_head_picks`, `paper_trades_settled`
(core/schema_lab.py)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, TypedDict

View = Literal["accuracy", "head_to_head"]
VIEWS: tuple[str, ...] = ("accuracy", "head_to_head")
PickRule = Literal["best_expected_gain", "highest_probability"]
PICK_RULES: tuple[str, ...] = ("best_expected_gain", "highest_probability")
HEAD_TO_HEAD_FAMILIES: tuple[str, ...] = ("rule", "ai")   # baselines are the yardstick, never contenders
PICK_STATUSES: tuple[str, ...] = ("picked", "no_candidate")
STRONGEST_BASES: tuple[str, ...] = ("per_company", "all_companies")
MIN_TRADES_PER_COMPANY = 20   # decision 41: per-company ranking only from 20 settled trades on it
TRADE_STATUSES: tuple[str, ...] = ("settled", "no_entry", "skipped_price_above_amount")
TRADE_FLAGS: tuple[str, ...] = ("exit_delayed", "split_in_window", "resettled")
REASON_CODES: tuple[str, ...] = (
    "market_up", "market_down", "sector_lift", "sector_drag", "news_positive", "news_negative",
    "company_specific", "target_reached", "range_missed",
)
ABSTENTION_CODES: tuple[str, ...] = (
    "abstained", "gate_failed", "timeout", "blocked_quality", "earnings_window", "killed",
)
CHECK_FLAGS: tuple[str, ...] = ("outside_range", "far_from_target", "against_prediction")
AI_REASON_KINDS: tuple[str, ...] = ("head_to_head", "biggest_win", "biggest_miss")
QUANTITY_DECIMALS = {"india": 0, "us": 6}   # whole shares in India (decision 4), fractional in the US (decision 5)


class Costs(TypedDict):
    """Round-trip costs of one trade in the market currency (F1.6; rates in config/costs.yaml). lines: charge name
    -> amount, e.g. {"brokerage": 500.0, "stt": 200.0, "dp_charge": 30.0} (India) or {"order_fee": 2.31,
    "sec_fee": 0.02} (US; BUX's euro fee converted at the day's EUR/USD rate)."""

    total: float
    lines: dict[str, float]


class Candidate(TypedDict):
    """One candidate horizon of a head-to-head pick, computed pre-open from the latest stored close C (F1.7.3),
    all in percent of the amount: move_pct = (target / C - 1) x 100; loss_pct = (1 - lo80 / C) x 100; costs_pct =
    the round trip at C; expected_gain_pct = p x move - (1 - p) x loss - costs."""

    horizon_days: int
    prediction_id: str
    prob_up: float
    move_pct: float
    loss_pct: float
    costs_pct: float
    expected_gain_pct: float


def entry_session(cfg: dict, made_at: datetime) -> date:
    """D: the first session of the market calendar whose open is after `made_at` (special sessions count)."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def exit_session(cfg: dict, entry_date: date, horizon_days: int) -> date:
    """The k-th session after D for horizon N+k, skipping weekends and the market's holidays (decision 37):
    a Friday entry with k = 1 exits at Monday's close."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def is_locked(prediction: dict, cfg: dict, first_committed_at: datetime | None) -> bool:
    """F1.8: True when made_at and the commit that first stored the row (when git can tell) are before D's open;
    a prediction that is not locked is refused by the settlement."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def qualifies(prediction: dict) -> bool:
    """F1.2: direction up and prob_up >= threshold (baselines without a probability: direction up)."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def quantity(market: str, amount: float, entry_open: float) -> float:
    """F1.4, from D's raw open: India floor(amount / open) whole shares (0 = skipped_price_above_amount); US
    amount / open rounded to QUANTITY_DECIMALS. Stored with the trade and never recomputed."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def round_trip_costs(market: str, entry_value: float, exit_value: float, quantity: float,
                     on_date: date) -> Costs:
    """F1.6: the buy and sell charges of one trade in the market currency."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def settle(prediction: dict, view: View, pick: dict | None, cfg: dict, settled_at: datetime) -> dict:
    """F1.9-F1.10: one `paper_trades_settled` row from stored bars and adjustments as of `settled_at`
    (deterministic: the same stored bars give the same row). pick: the head_to_head_picks row (head-to-head view)."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def strongest(market: str, family: str, ticker: str, as_of: datetime) -> list[dict]:
    """Decision 41 / F1.7.2: the family's strategies ranked for this company (per_company from
    MIN_TRADES_PER_COMPANY settled accuracy-view trades on it, then all_companies; ties: more settled trades, then
    the lower id), as stored in head_to_head_picks.ranking."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")


def pick(candidates: list[Candidate], rule: PickRule) -> Candidate | None:
    """F1.7.3: best_expected_gain = the highest expected_gain_pct, highest_probability = the highest prob_up;
    ties: the shorter horizon. None when there is no candidate (status no_candidate)."""
    raise NotImplementedError("session B2 (marketbrief/lab/)")
