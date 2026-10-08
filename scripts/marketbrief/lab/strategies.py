"""F2 rule strategies and baselines: one prediction per strategy x active company x horizon from the per-horizon
model score and range (contracts/horizons.py, B10), the feature row, the regime and the company's news.

Probability by signal:
- model: p = sigmoid(logit(prob_model) + news_weight x coefficient x clip(sum of the item weights, +-score_cap)),
  prob_model = the score without news (calibrated); the items and weights are the signal model's news term
  (model/news_score.py item_weight), keeping only items whose status is in `news_statuses` and whose materiality
  is in `news_materiality` (rumour, promotional, unverified and contradicted always weigh 0). The reference
  strategy (weight 1, every status and materiality) reproduces the score's prob_up; news_weight 0 is model-only.
- always_up: direction up, no probability; momentum: up when the as-of close is above the previous close.
Rules (F2.6): no prediction (an abstention row) with quality BLOCKED or days_to_earnings <= 1; regime_filter:
written with qualifies false in UNSTABLE / EVENT_HEAVY; cross_market true: reads the cross_market model variant's
scores (B10's model_variant_scores) instead of the base scores, and abstains on a horizon without one.
target_price = the range's base_close x exp(center) (center is a log shift, not a price); the range as
ranges.py publishes it (never narrowed)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from marketbrief.constants.kinds import KIND_STRATEGY_ABSTENTIONS, KIND_STRATEGY_PREDICTIONS
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab.constants import (ABSTAIN_ABSTAINED, ABSTAIN_BLOCKED, ABSTAIN_EARNINGS, DOWN, EARNINGS_BLOCK_DAYS,
                                       FILTERED_REGIMES, LAB_VERSION, MSG_NO_CROSS_SCORE, MSG_NO_CROSS_SCORE_OR_RANGE,
                                       PRICE_DIGITS, PROB_DIGITS, QUALITY_BLOCKED, SIGNAL_ALWAYS_UP, SIGNAL_MOMENTUM,
                                       UP, VERIFIED_STATUSES)
from marketbrief.lab.registry import config_hash
from marketbrief.lab.sizing import qualifies
from marketbrief.model.news_score import item_weight

STATUS_ORDER = {"confirmed_primary": 0, "corroborated": 1, "single_source": 2}


@dataclass
class TickerInputs:
    """One company's inputs on one as-of day. scores / ranges: {k: HorizonScore / HorizonRange}; cross_scores:
    {k: HorizonScore} of the cross_market model variant; news: [{id, sentiment, relevance, materiality,
    event_type, status}] as of the score time."""
    market: str
    ticker: str
    as_of_date: str
    session_date: str
    exit_dates: dict[int, str]
    made_at: str
    base_close: float
    prev_close: float | None
    regime: str | None
    quality: str | None
    days_to_earnings: int | None
    amount: float
    currency: str
    scores: dict[int, dict] = field(default_factory=dict)
    cross_scores: dict[int, dict] = field(default_factory=dict)
    ranges: dict[int, dict] = field(default_factory=dict)
    news: list[dict] = field(default_factory=list)


def logit(p: float) -> float:
    """log(p / (1 - p)) clipped away from 0 and 1."""
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def counted_news(params: dict, news: list[dict], news_cfg: dict) -> list[tuple[dict, float]]:
    """(item, weight) of the items this strategy counts (non-zero weight)."""
    out = []
    for item in news:
        if item.get("status") not in params["news_statuses"] or item.get("materiality") not in params[
                "news_materiality"]:
            continue
        weight = item_weight(_Item(item), news_cfg, item.get("status"))
        if weight:
            out.append((item, weight))
    return out


class _Item:
    """Attribute access for item_weight."""

    def __init__(self, item: dict):
        """Wrap a news dict."""
        self.sentiment, self.relevance = item.get("sentiment"), item.get("relevance")
        self.materiality, self.event_type = item.get("materiality"), item.get("event_type")


def model_probability(params: dict, score: dict, news: list[dict], news_cfg: dict) -> tuple[float, list[str]]:
    """(p, the news ids counted) of a model-signal strategy."""
    items = counted_news(params, news, news_cfg) if params["news_weight"] else []
    cap = news_cfg["score_cap"]
    total = max(-cap, min(cap, sum(weight for _, weight in items)))
    shift = params["news_weight"] * news_cfg["coefficient"] * total
    prob = 1 / (1 + math.exp(-(logit(score["prob_model"]) + shift)))
    ranked = sorted(items, key=lambda pair: (STATUS_ORDER.get(pair[0]["status"], 9), pair[0]["id"]))
    return prob, [item["id"] for item, _ in ranked]


def target_price(rng: dict, inputs: TickerInputs) -> float:
    """The range's expected exit close: its base_close x exp(center); `center` is a log shift, not a price (B10's
    ranges rows; the as-of close when the row has no base_close)."""
    base = rng.get("base_close") or inputs.base_close
    return round(float(base) * math.exp(float(rng["center"])), PRICE_DIGITS)


def evidence(spec: dict, inputs: TickerInputs, horizon: int, news_ids: list[str], statuses: dict) -> list[str]:
    """The inputs used (F2.6: model score and feature snapshot ids), then the counted news ids when the first is
    confirmed_primary or corroborated (DESIGN.md 3b: otherwise no news id is cited)."""
    out = []
    if spec["parameters"]["signal"] not in (SIGNAL_ALWAYS_UP, SIGNAL_MOMENTUM):
        out.append(f"model_scores:{inputs.scores[horizon]['id']}")
    out.append(f"features:{inputs.as_of_date}-{inputs.ticker}")
    if news_ids and statuses.get(news_ids[0]) in VERIFIED_STATUSES:
        out += news_ids
    return out


def prediction(spec: dict, inputs: TickerInputs, horizon: int, news_cfg: dict) -> dict:
    """One strategy_predictions row."""
    params, score, rng = spec["parameters"], inputs.scores.get(horizon), inputs.ranges[horizon]
    news_ids, prob = [], None
    if params["signal"] == SIGNAL_ALWAYS_UP:
        direction = UP
    elif params["signal"] == SIGNAL_MOMENTUM:
        direction = UP if inputs.prev_close is not None and inputs.base_close > inputs.prev_close else DOWN
    else:
        prob, news_ids = model_probability(params, score, inputs.news, news_cfg)
        prob = round(prob, PROB_DIGITS)
        direction = UP if prob >= 0.5 else DOWN
    row = dict.fromkeys(SCHEMAS[KIND_STRATEGY_PREDICTIONS][1])
    row.update(id=f"{spec['id']}:{inputs.as_of_date}-{inputs.ticker}-{horizon}d", strategy_id=spec["id"],
               family=spec["family"], market=inputs.market, ticker=inputs.ticker, made_at=inputs.made_at,
               as_of_date=inputs.as_of_date, session_date=inputs.session_date, exit_date=inputs.exit_dates[horizon],
               horizon_days=horizon, direction=direction, prob_up=prob,
               confidence=None if prob is None else round(max(prob, 1 - prob), PROB_DIGITS),
               threshold=spec["threshold"], base_close=inputs.base_close, target_price=target_price(rng, inputs),
               range_id=rng["id"], lo50=rng["lo50"], hi50=rng["hi50"], lo80=rng["lo80"], hi80=rng["hi80"],
               range_widen=0.0, model_score_id=score["id"] if score and prob is not None else None,
               model_prob=score["prob_model"] if score and prob is not None else None,
               evidence_ids=evidence(spec, inputs, horizon, news_ids, {n["id"]: n["status"] for n in inputs.news}),
               regime=inputs.regime, quality=inputs.quality, amount=inputs.amount, currency=inputs.currency,
               config_hash=config_hash(spec), method_version=LAB_VERSION)
    row["qualifies"] = qualifies(row) and not (params.get("regime_filter") and inputs.regime in FILTERED_REGIMES)
    return row


def abstention(spec: dict, inputs: TickerInputs, code: str, reason: str | None, horizons: list[int]) -> dict:
    """One strategy_abstentions row (id <strategy_id>:<as_of_date>-<ticker>)."""
    row = dict.fromkeys(SCHEMAS[KIND_STRATEGY_ABSTENTIONS][1])
    row.update(id=f"{spec['id']}:{inputs.as_of_date}-{inputs.ticker}", strategy_id=spec["id"], family=spec["family"],
               market=inputs.market, ticker=inputs.ticker, made_at=inputs.made_at, as_of_date=inputs.as_of_date,
               session_date=inputs.session_date, horizons=horizons, reason_code=code, reason=reason, gate_codes=[],
               attempts=1)
    return row


def blocked(inputs: TickerInputs) -> str | None:
    """The F2.6 block of a company today, or None."""
    if inputs.quality == QUALITY_BLOCKED:
        return ABSTAIN_BLOCKED
    if inputs.days_to_earnings is not None and inputs.days_to_earnings <= EARNINGS_BLOCK_DAYS:
        return ABSTAIN_EARNINGS
    return None


def company_rows(specs: list[dict], inputs: TickerInputs, news_cfg: dict) -> tuple[list[dict], list[dict]]:
    """(predictions, abstentions) of every rule strategy and baseline for one company and day."""
    preds, skipped = [], []
    block = blocked(inputs)
    for spec in specs:
        wanted = [k for k in spec["horizons"] if k in inputs.ranges]
        if block:
            skipped.append(abstention(spec, inputs, block, None, list(spec["horizons"])))
            continue
        model_based = spec["parameters"]["signal"] not in (SIGNAL_ALWAYS_UP, SIGNAL_MOMENTUM)
        cross = bool(spec["parameters"].get("cross_market"))
        own = replace(inputs, scores=inputs.cross_scores) if cross else inputs
        usable = [k for k in wanted if not model_based or k in own.scores]
        missing = [k for k in spec["horizons"] if k not in usable]
        if missing:
            no_range = any(k not in inputs.ranges for k in missing)
            reason = ((MSG_NO_CROSS_SCORE_OR_RANGE if no_range else MSG_NO_CROSS_SCORE) if cross
                      else "no model score or range for these horizons")
            skipped.append(abstention(spec, own, ABSTAIN_ABSTAINED, reason, missing))
        preds += [prediction(spec, own, k, news_cfg) for k in usable]
    return preds, skipped
