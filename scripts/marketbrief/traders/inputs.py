"""What the traders' gate checks a record against, as of the run's clock (MB_NOW-aware): the active companies, each
one's latest indicator snapshot (as-of date, quality, days to earnings) and regime, the citable ids with the time each
became public, their verification status (DESIGN.md 3b), the published range and the model score of every ticker x
horizon (session B10's `contracts.horizons.ranges_asof` / `scores_asof`), the traders' own track records and the ids
already stored. Tests build a GateInputs by hand from W1's example records; `load_inputs` reads stored data."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache

import pandas as pd

from marketbrief.constants.config_keys import CFG_TICKERS
from marketbrief.contracts import horizons, watchlist
from marketbrief.core.database import connect
from marketbrief.pipeline.evidence_status import EvidenceStatuses
from marketbrief.pipeline.forecast_gate import evidence_times
from marketbrief.traders import track_record
from marketbrief.traders.constants import MSG_INPUTS

FEATURES_SQL = """
SELECT DISTINCT ON (ticker) ticker, as_of_date, quality, days_to_earnings, computed_at FROM features
WHERE computed_at <= ?::TIMESTAMPTZ ORDER BY ticker, as_of_date DESC, computed_at DESC"""
REGIME_SQL = """
SELECT DISTINCT ON (as_of_date) as_of_date, regime, computed_at FROM regime
WHERE computed_at <= ?::TIMESTAMPTZ ORDER BY as_of_date, computed_at DESC"""


class InputsUnavailableError(RuntimeError):
    """The per-horizon ranges or model scores cannot be read yet (session B10 has not merged)."""


class AllUnverified:
    """A status lookup with no status rows: every id is unverified and the feature counts as not running."""

    def active(self, when) -> bool:  # noqa: ARG002 - the EvidenceStatuses interface
        """No status row exists."""
        return False

    def of(self, evidence_id: str, ticker: str, when) -> str:  # noqa: ARG002 - the EvidenceStatuses interface
        """Unverified."""
        return "unverified"


@dataclass
class GateInputs:
    """Everything the gate reads. features: ticker -> {as_of_date (date), quality, days_to_earnings (int or None)};
    regimes: as_of_date -> (regime, computed_at); evidence: citable id -> when it became public (None = unknown);
    statuses: EvidenceStatuses-like (`active(when)`, `of(id, ticker, when)`); ranges / scores: id
    (<as_of_date>-<ticker>-<k>d) -> HorizonRange / HorizonScore dict; track: strategy -> band -> cell;
    amounts: ticker -> the paper amount of a trade made now."""

    cfg: dict
    now: datetime
    active: set[str]
    features: dict[str, dict]
    regimes: dict[date, tuple[str, datetime | None]]
    evidence: dict[str, datetime | None]
    statuses: object = field(default_factory=AllUnverified)
    ranges: dict[str, dict] = field(default_factory=dict)
    scores: dict[str, dict] = field(default_factory=dict)
    track: dict[str, dict] = field(default_factory=dict)
    stored_predictions: set[str] = field(default_factory=set)
    stored_abstentions: set[str] = field(default_factory=set)
    amounts: dict[str, float | None] = field(default_factory=dict)
    ranges_at: Callable[[datetime], dict[str, dict]] | None = None   # ranges as of a time (load_inputs: B10's
    scores_at: Callable[[datetime], dict[str, dict]] | None = None   # ranges_asof / scores_asof at made_at)

    def range_for(self, range_id: str, made: datetime) -> dict | None:
        """The published range of the id as of made_at (a range published later does not exist yet)."""
        return (self.ranges_at(made) if self.ranges_at else self.ranges).get(range_id)

    def score_for(self, score_id: str, made: datetime) -> dict | None:
        """The newest model score of the id computed by made_at (a later rescore is not used)."""
        return (self.scores_at(made) if self.scores_at else self.scores).get(score_id)

    @property
    def market(self) -> str:
        """The market name."""
        return self.cfg["market"]

    @property
    def currency(self) -> str | None:
        """INR or USD (None for a test market)."""
        return watchlist.CURRENCY.get(self.market)


def active_tickers(cfg: dict) -> list[str]:
    """Active companies: the loader key `active_tickers` once session B1 builds it, else every configured ticker."""
    found = cfg.get(watchlist.CFG_ACTIVE_TICKERS)
    return sorted(found if found is not None else cfg[CFG_TICKERS])


def amount_of(market: str, ticker: str, now: datetime) -> float | None:
    """The company's paper amount (B1's override when built; until then no override exists: the market default)."""
    try:
        return float(watchlist.trade_amount(market, ticker, now))
    except NotImplementedError:
        return watchlist.DEFAULT_AMOUNT.get(market)


def per_horizon(market: str, now: datetime) -> tuple[dict[str, dict], dict[str, dict]]:
    """(ranges, scores) by id from B10's contract; InputsUnavailableError until it is built."""
    try:
        ranges = horizons.ranges_asof(market, now)
        scores = horizons.scores_asof(market, now)
    except NotImplementedError as error:
        raise InputsUnavailableError(MSG_INPUTS.format(detail=error)) from error
    return {row["id"]: dict(row) for row in ranges}, {row["id"]: dict(row) for row in scores}


def as_date(value) -> date:
    """A DuckDB date or timestamp as a date."""
    return pd.Timestamp(value).date()


def stored_features(con, now: datetime) -> dict[str, dict]:
    """Each ticker's newest indicator snapshot computed by `now`."""
    out = {}
    for ticker, as_of, quality, days, computed in con.execute(FEATURES_SQL, [now.isoformat()]).fetchall():
        out[ticker] = {"as_of_date": as_date(as_of), "quality": quality,
                       "days_to_earnings": None if days is None or pd.isna(days) else int(days),
                       "computed_at": pd.Timestamp(computed).to_pydatetime()}
    return out


def stored_regimes(con, now: datetime) -> dict[date, tuple[str, datetime | None]]:
    """The regime of each as-of date known by `now`."""
    return {as_date(as_of): (regime, pd.Timestamp(computed).to_pydatetime())
            for as_of, regime, computed in con.execute(REGIME_SQL, [now.isoformat()]).fetchall()}


def load_inputs(cfg: dict, now: datetime, con=None) -> GateInputs:
    """GateInputs from stored data as of `now` (raises InputsUnavailableError without B10's per-horizon records)."""
    market = cfg["market"]
    con = con or connect(market)
    ranges, scores = per_horizon(market, now)
    tickers = active_tickers(cfg)
    return GateInputs(
        cfg=cfg, now=now, active=set(tickers), features=stored_features(con, now), regimes=stored_regimes(con, now),
        evidence=evidence_times(con), statuses=EvidenceStatuses(con), ranges=ranges, scores=scores,
        track=track_record.load(con, now),
        stored_predictions={row[0] for row in con.execute("SELECT id FROM strategy_predictions").fetchall()},
        stored_abstentions={row[0] for row in con.execute("SELECT id FROM strategy_abstentions").fetchall()},
        amounts={ticker: amount_of(market, ticker, now) for ticker in tickers},
        ranges_at=as_of_lookup(market, horizons.ranges_asof), scores_at=as_of_lookup(market, horizons.scores_asof),
    )


def as_of_lookup(market: str, read) -> Callable[[datetime], dict[str, dict]]:
    """id -> record as of a time from one of B10's contract readers, cached per time (records share a made_at)."""
    @lru_cache(maxsize=16)
    def at(when: datetime) -> dict[str, dict]:
        return {row["id"]: dict(row) for row in read(market, when)}
    return at
