"""Horizons of the portfolio's signals and proof (decision 37, W1 file list): the horizon list of
config/strategies.yaml, and which stored rows count as N+k. A row counts for N+k when its horizon_label is n_plus_k,
or when it has no label and is the open-to-close 1-day horizon (open of D to the close of D+1 = N+1). The old
open-to-close 5-day rows (exit at D+4, legacy_5d_d4) and close-to-close rows are never pooled with N+5."""
from __future__ import annotations

from marketbrief.contracts.horizons import HORIZON_LABEL_N_PLUS_K
from marketbrief.contracts.watchlist import CFG_ACTIVE_TICKERS
from marketbrief.lab.registry import horizons as registry_horizons

COL_HORIZON_LABEL = "horizon_label"


def horizons() -> tuple[int, ...]:
    """The N+k horizon list (config/strategies.yaml `horizons`)."""
    return registry_horizons()


def is_n_plus_k(horizon: int, label: str | None) -> bool:
    """True when a stored row of this horizon and label measures N+k."""
    return label == HORIZON_LABEL_N_PLUS_K or (label is None and int(horizon) == 1)


def label_sql(con, table: str, alias: str = "") -> str:
    """`<alias>horizon_label` when the table has the column (B10 adds it), else `NULL AS horizon_label`."""
    columns = {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}
    return f"{alias}{COL_HORIZON_LABEL}" if COL_HORIZON_LABEL in columns else f"NULL AS {COL_HORIZON_LABEL}"


def active_tickers(cfg: dict) -> list[str]:
    """The active companies (B1's loader key active_tickers; until then every config ticker), sorted."""
    return sorted(cfg.get(CFG_ACTIVE_TICKERS) or cfg["tickers"])
