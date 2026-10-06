"""The market config and the clock of one prices run, shared by the prices collector's modules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceRun:
    """cfg: the market config; today: the UTC date of the run; now: its ISO timestamp."""
    cfg: dict
    today: date
    now: str
