"""Shared fixtures of the B3 trader tests: GateInputs built from W1's example records (design/catalogue) for NVDA on
2026-10-06 (US; D = 2026-10-07, open 13:30 UTC, trader deadline 13:15 UTC), with per-horizon ranges taken from the
rule strategy's unwidened example ranges and model scores from the combined traders' example model_prob."""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.traders.inputs import GateInputs  # noqa: E402

CATALOGUE = REPO / "design" / "catalogue"
AS_OF = date(2026, 10, 6)
NEWS_ID = "a41c9e07b2d35f18"            # corroborated in news_item.json
MADE_AT = "2026-10-07T11:45:00Z"
NOW = datetime(2026, 10, 7, 11, 50, tzinfo=timezone.utc)
AGENT_KEYS = ("strategy_id", "ticker", "horizon_days", "direction", "prob_up", "target_price", "range_widen",
              "evidence_ids", "reason", "made_at", "model_prob", "agent_adjustment", "adjustment_reason")
PROMPTS = {"ai.news_results.sonnet.v1": "trader-news-v1", "ai.pattern_mood.sonnet.v1": "trader-pattern-v1",
           "ai.combined.sonnet.v1": "trader-combined-v1", "ai.combined.opus.v1": "forecast-v14"}


def catalogue(name: str) -> list[dict]:
    """The records of one example file."""
    return json.loads((CATALOGUE / f"{name}.json").read_text())["records"]


def example(strategy_id: str, ticker: str = "NVDA", horizon: int = 1) -> dict:
    """One example prediction of the catalogue."""
    return next(r for r in catalogue("prediction") if r["strategy_id"] == strategy_id and r["ticker"] == ticker
                and r["horizon_days"] == horizon)


def agent_record(strategy_id: str, horizon: int = 1, **changes) -> dict:
    """The fields a trader writes, from the catalogue's AI example (anchor fields only for the combined traders)."""
    rec = {k: v for k, v in example(strategy_id, horizon=horizon).items() if k in AGENT_KEYS and v is not None}
    rec["prompt_version"] = PROMPTS[strategy_id]
    rec["made_at"] = MADE_AT
    if strategy_id.startswith("ai.combined"):
        rec["prob_up"] = round(rec["model_prob"] + rec["agent_adjustment"], 4)
        rec["evidence_ids"] = [NEWS_ID]
    rec.pop("range_widen", None)
    rec.update(changes)
    return {k: v for k, v in rec.items() if v is not None}


def published_range(horizon: int) -> dict:
    """The unwidened example range of NVDA N+k (the rule strategy's range_widen 0 record) as a HorizonRange."""
    rule = example("rule.model_news.v1", horizon=horizon)
    return {"id": f"{AS_OF}-NVDA-{horizon}d", "made_at": "2026-10-07T11:40:00Z", "as_of_date": str(AS_OF),
            "session_date": "2026-10-07", "target_date": rule["exit_date"], "ticker": "NVDA", "horizon_days": horizon,
            "base_close": rule["base_close"], "center": math.log(rule["target_price"] / rule["base_close"]),
            "lo50": rule["lo50"], "hi50": rule["hi50"], "lo80": rule["lo80"], "hi80": rule["hi80"],
            "horizon_label": "n_plus_k", "entry_date": "2026-10-07", "exit_date": rule["exit_date"]}


def score(horizon: int) -> dict:
    """The example model score of NVDA N+k (the combined Sonnet trader's model_prob)."""
    rec = example("ai.combined.sonnet.v1", horizon=horizon)
    return {"id": f"{AS_OF}-NVDA-{horizon}d", "prob_up": rec["model_prob"], "computed_at": "2026-10-07T11:30:00Z",
            "horizon_days": horizon, "horizon_label": "n_plus_k"}


class Statuses:
    """A status lookup: id -> status (anything else unverified); `active` says whether status rows exist."""

    def __init__(self, table: dict[str, str] | None = None, active: bool = True):
        self.table, self.on = table if table is not None else {NEWS_ID: "corroborated"}, active

    def active(self, when) -> bool:  # noqa: ARG002 - the EvidenceStatuses interface
        return self.on

    def of(self, evidence_id: str, ticker: str, when) -> str:  # noqa: ARG002 - the EvidenceStatuses interface
        return self.table.get(evidence_id, "unverified")


def inputs(**changes) -> GateInputs:
    """GateInputs for NVDA as of 2026-10-06 at NOW; keyword arguments replace fields."""
    cfg = {**load_market("us"), "active_tickers": ["NVDA"]}
    base = {
        "cfg": cfg, "now": NOW, "active": {"NVDA"},
        "features": {"NVDA": {"as_of_date": AS_OF, "quality": "OK", "days_to_earnings": 30}},
        "regimes": {AS_OF: ("TRENDING", datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc))},
        "evidence": {NEWS_ID: datetime(2026, 9, 29, 21, 10, tzinfo=timezone.utc),
                     "late-news": datetime(2026, 10, 7, 12, 30, tzinfo=timezone.utc),
                     "rumour-news": datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc),
                     "single-news": datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)},
        "statuses": Statuses({NEWS_ID: "corroborated", "rumour-news": "rumour", "single-news": "single_source",
                              "late-news": "corroborated"}),
        "ranges": {f"{AS_OF}-NVDA-{h}d": published_range(h) for h in (1, 3, 5)},
        "scores": {f"{AS_OF}-NVDA-{h}d": score(h) for h in (1, 3, 5)},
        "amounts": {"NVDA": 1000.0},
    }
    base.update(changes)
    return GateInputs(**base)


def agent_record_for(strategy_id: str, ticker: str, horizon: int) -> dict:
    """agent_record for any example ticker (the catalogue's own made_at kept)."""
    rec = {k: v for k, v in example(strategy_id, ticker, horizon).items() if k in AGENT_KEYS and v is not None}
    rec["prompt_version"] = PROMPTS[strategy_id]
    rec.pop("range_widen", None)
    if strategy_id.startswith("ai.combined"):
        rec["prob_up"] = round(rec["model_prob"] + rec["agent_adjustment"], 4)
    return rec


def inputs_for(market: str, ticker: str, now: datetime, regime: str = "TRENDING") -> GateInputs:
    """GateInputs for one example ticker as of 2026-10-06 (ranges from the rule strategy's unwidened example
    records, scores from the combined Sonnet trader's model_prob, every example news id corroborated)."""
    news = {r["id"]: r for r in catalogue("news_item")}
    ranges, scores = {}, {}
    for horizon in (1, 3, 5):
        rule = example("rule.model_news.v1", ticker, horizon)
        rid = f"{AS_OF}-{ticker}-{horizon}d"
        ranges[rid] = {"id": rid, "made_at": "2026-10-07T00:00:00Z", "base_close": rule["base_close"],
                       "center": math.log(rule["target_price"] / rule["base_close"]), "lo50": rule["lo50"],
                       "hi50": rule["hi50"], "lo80": rule["lo80"], "hi80": rule["hi80"],
                       "entry_date": rule["session_date"], "exit_date": rule["exit_date"]}
        scores[rid] = {"id": rid, "prob_up": example("ai.combined.sonnet.v1", ticker, horizon)["model_prob"],
                       "computed_at": "2026-10-07T00:00:00Z"}
    return GateInputs(
        cfg={**load_market(market), "active_tickers": [ticker]}, now=now, active={ticker},
        features={ticker: {"as_of_date": AS_OF, "quality": "OK", "days_to_earnings": 30}},
        regimes={AS_OF: (regime, None)},
        evidence={i: datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) for i, r in news.items()},
        statuses=Statuses({i: "corroborated" for i in news}), ranges=ranges, scores=scores,
        amounts={ticker: 100000.0 if market == "india" else 1000.0})
