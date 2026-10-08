"""Horizons of the portfolio's signals and proof (decision 37, W1 file list; issue #94): the horizon list of
config/strategies.yaml, and the window of each stored row. A row's label is its stored horizon_label, else B10's
rule for that kind:
- a model score (score_label; core/horizons.legacy_label, as the model_scores_latest view and B10's
  horizon_records): an unlabelled 1-day score is n_plus_k (N+1, the same window), any other unlabelled score
  legacy_5d_d4 (sold at D+4's close), whatever its computed_at;
- a forecaster call (resolved_label; analytics/call_basis.horizon_label with config/settings.yaml
  call_scoring.n_plus_k_from): an open-to-close 5-day call made before n_plus_k_from is legacy_5d_d4, every other
  open-to-close call n_plus_k (sold at the close of D+k).
Only n_plus_k rows count for N+k; legacy rows are never pooled with N+5."""
from __future__ import annotations

from marketbrief.analytics import call_basis
from marketbrief.constants.model import LABEL_OPEN_TO_CLOSE
from marketbrief.contracts.horizons import HORIZON_LABEL_N_PLUS_K
from marketbrief.contracts.watchlist import CFG_ACTIVE_TICKERS
from marketbrief.core.horizons import legacy_label
from marketbrief.lab.registry import horizons as registry_horizons

COL_HORIZON_LABEL = "horizon_label"
KIND_MODEL_SCORES = "model_scores"   # core/horizons.legacy_label kind


def horizons() -> tuple[int, ...]:
    """The N+k horizon list (config/strategies.yaml `horizons`)."""
    return registry_horizons()


def resolved_label(horizon: int, label, made_at) -> str:
    """A call's stored horizon_label, else the label B10's rule gives an open-to-close call made at `made_at`."""
    if isinstance(label, str) and label:
        return label
    return call_basis.horizon_label(LABEL_OPEN_TO_CLOSE, int(horizon), made_at, call_basis.n_plus_k_from())


def score_label(horizon: int, label) -> str:
    """A model score's stored horizon_label, else B10's label of an unlabelled model_scores row."""
    if isinstance(label, str) and label:
        return label
    return legacy_label(KIND_MODEL_SCORES, int(horizon))


def is_n_plus_k(horizon: int, label, made_at) -> bool:
    """True when a stored row of this horizon, label and time measures N+k."""
    return resolved_label(horizon, label, made_at) == HORIZON_LABEL_N_PLUS_K


def sessions_after_d(horizon: int, label: str) -> int:
    """How many sessions after D the row's window closes: N+k k; legacy_5d_d4 4 (B10's call_basis.target_offset,
    which counts bars after the as-of bar)."""
    return call_basis.target_offset(LABEL_OPEN_TO_CLOSE, int(horizon), label) - 1


def label_sql(con, table: str, alias: str = "") -> str:
    """`<alias>horizon_label` when the table has the column (B10 adds it), else `NULL AS horizon_label`."""
    columns = {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}
    return f"{alias}{COL_HORIZON_LABEL}" if COL_HORIZON_LABEL in columns else f"NULL AS {COL_HORIZON_LABEL}"


def active_tickers(cfg: dict) -> list[str]:
    """The active companies (B1's loader key active_tickers; an empty list means none is active; without the key,
    every config ticker), sorted."""
    active = cfg.get(CFG_ACTIVE_TICKERS)
    return sorted(cfg["tickers"] if active is None else active)
