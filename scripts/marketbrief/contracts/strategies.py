"""The format of config/strategies.yaml (docs/SPEC.md F2.1, F2.7; W1). Values only: the registry is validated by
tests/test_w1_catalogue.py; the loader that the lab and the traders use is session B2's (`marketbrief/lab/`)."""
from __future__ import annotations

from typing import Literal, TypedDict

STRATEGIES_FILE = "strategies.yaml"   # under config/

Family = Literal["rule", "baseline", "ai"]
FAMILIES: tuple[str, ...] = ("rule", "baseline", "ai")
SIGNALS: tuple[str, ...] = ("model", "always_up", "momentum")   # rule and baseline `parameters.signal`
SIGNALS_WITHOUT_PROBABILITY: tuple[str, ...] = ("always_up", "momentum")   # threshold null
NEWS_WEIGHTS: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)
NEWS_STATUSES: tuple[str, ...] = ("confirmed_primary", "corroborated", "single_source")   # rumour, promotional,
# unverified and contradicted never carry weight (DESIGN.md 3b), so they cannot be switched on
MATERIALITY_LEVELS: tuple[str, ...] = ("high", "medium", "low")
AI_MODELS: tuple[str, ...] = ("sonnet", "opus")
AI_INPUTS: tuple[str, ...] = (
    "news", "results", "filings", "events", "prices", "indicators", "regime", "cues", "sectors", "model_score",
)
RULE_PARAMETERS: tuple[str, ...] = (
    "signal", "news_weight", "news_statuses", "news_materiality", "cross_market", "regime_filter",
)
AI_PARAMETERS: tuple[str, ...] = ("model", "sees_model_score", "inputs")
ID_PATTERN = r"^(rule|base|ai)\.[a-z0-9_]+(\.[a-z0-9_]+)?\.v[0-9]+$"   # family prefix ... .v<version>
ID_PREFIX: dict[str, str] = {"rule": "rule", "baseline": "base", "ai": "ai"}
MAX_HORIZON = 21   # about a month (decision 37); the list may grow up to this without a redesign


class StrategySpec(TypedDict):
    """One entry of `strategies:`. `parameters` holds RULE_PARAMETERS (rule, baseline) or AI_PARAMETERS (ai).
    threshold: the minimum prob_up for an "up" prediction to trade (null for always_up and momentum).
    horizons: a subset of the top-level `horizons` (AI traders: of `ai_horizons`). live_from: ISO date of the
    first session it trades, or null while not live. compared_to / differs_in: the strategy it is compared with
    and the one parameter that differs (F2.5)."""

    id: str
    family: Family
    name: str
    description: str
    compared_to: str | None
    differs_in: str | None
    parameters: dict
    threshold: float | None
    horizons: list[int]
    live_from: str | None


class StrategyRegistry(TypedDict):
    """The whole file: version, horizons (N+k list, decision 37), ai_horizons (decision 38), reference (the
    documented default parameter set) and strategies."""

    version: int
    horizons: list[int]
    ai_horizons: list[int]
    reference: dict
    strategies: list[StrategySpec]
