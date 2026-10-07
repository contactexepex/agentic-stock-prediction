"""Per-horizon model-score and range records (docs/SPEC.md F2.7; W1 interface, session B10 builds them).

Today the signal model and ranges.py write horizons 1 and 5 only (`model_scores`, `ranges`), with windows that
differ from decision 37. B10 extends both to every horizon of config/strategies.yaml `horizons` with the N+k
definition: entry at the open of D (the first session after the as-of close), exit at the close of the k-th
session after D. The records below are the existing columns plus the new ones, so B2, B3 and B9 can build
against fixtures before B10's data exists. New columns only (additive): `horizon_label`, `entry_date`,
`exit_date`. Old rows read with `horizon_label` null are labelled on read by B10:

- n_plus_k      the decision-37 definition (every new row);
- legacy_cc     close-to-close calls and the old ranges (1d: as-of close -> D's close; 5d: -> D+4's close);
- legacy_5d_d4  open-to-close 5-day model labels and calls (open of D -> close of D+4).

Open-to-close 1-day rows equal N+1 and may be pooled with it; nothing else legacy is ever pooled with N+k."""
from __future__ import annotations

from datetime import date, datetime
from typing import TypedDict

from marketbrief.analytics import horizon_records as records
from marketbrief.core.horizons import horizons as horizon_list

HORIZON_LABELS: tuple[str, ...] = ("n_plus_k", "legacy_cc", "legacy_5d_d4")   # = constants/horizons.HORIZON_LABELS
HORIZON_LABEL_N_PLUS_K = "n_plus_k"


class HorizonScore(TypedDict):
    """One `model_scores` row per ticker x horizon x as-of date (id <as_of_date>-<ticker>-<k>d). prob_up = P(exit
    close of the k-th session after D > open of D), Platt-calibrated where `calibrated`. contributions: JSON of the
    explanation (points per feature group, top drivers)."""

    id: str
    as_of_date: date
    ticker: str
    horizon_days: int
    label_convention: str
    prob_up: float
    prob_model: float
    calibrated: bool
    base_rate: float
    news_score: float | None
    news_logit: float | None
    contributions: dict
    model_version: str
    model_id: str
    trained_until: date
    computed_at: datetime
    horizon_label: str        # new: n_plus_k
    entry_date: date          # new: D
    exit_date: date           # new: the k-th session after D
    model_variant: str | None  # new (B10): base (null on older rows) or cross_market


class HorizonRange(TypedDict):
    """One `ranges` row per ticker x horizon x as-of date (id <as_of_date>-<ticker>-<k>d): the 50% and 80% bands
    of the exit close (target_date = exit_date) around `center`, from base_close (the as-of close). A strategy's
    target price defaults to `center`; its range may only be wider (range_widen 0-0.5)."""

    id: str
    made_at: datetime
    as_of_date: date
    session_date: date
    target_date: date
    ticker: str
    horizon_days: int
    base_close: float
    center: float
    sigma_h: float
    lo50: float
    hi50: float
    lo80: float
    hi80: float
    naive_lo50: float
    naive_hi50: float
    naive_lo80: float
    naive_hi80: float
    direction: str | None
    confidence: float | None
    regime: str
    calibration_id: str | None
    notes: list[str]
    inputs: list[str]
    iv_sigma_h: float | None
    horizon_label: str        # new: n_plus_k
    entry_date: date          # new: D (= session_date)
    exit_date: date           # new: the k-th session after D (= target_date)


def horizons() -> tuple[int, ...]:
    """The horizon list of config/strategies.yaml (`horizons`), read by the model, ranges.py, the strategies and
    the scoreboard instead of the HORIZONS constants (core/horizons.py)."""
    return horizon_list()


def scores_asof(market: str, as_of: datetime, horizon_days: int | None = None,
                variant: str = "base") -> list[HorizonScore]:
    """The newest model score per ticker and horizon computed by `as_of` (no look-ahead; N+k rows only). variant:
    "base" (config/model.yaml as written; the default) or "cross_market" (every cross-market feature group on, for
    strategies with `cross_market: true`; ids end in -cross_market)."""
    return records.scores_asof(market, as_of, horizon_days, variant=variant)


def ranges_asof(market: str, as_of: datetime, horizon_days: int | None = None) -> list[HorizonRange]:
    """The first published range per ticker and horizon for the session after the newest as-of date made by
    `as_of` (the range a strategy prediction copies; N+k rows only)."""
    return records.ranges_asof(market, as_of, horizon_days)
