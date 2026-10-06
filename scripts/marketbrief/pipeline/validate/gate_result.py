"""The result of a gate run (failures, warnings, info) and the run's shared lookups."""

from __future__ import annotations

from pathlib import Path
from marketbrief.pipeline import market_status
from marketbrief.core.settings import load_validate_config
from marketbrief.core import clock, paths


def load_config() -> dict:
    """The gate's thresholds from config/validate.yaml."""
    return load_validate_config()


class Result:
    """Failures, warnings and info collected while the gate runs."""
    def __init__(self):
        """Start with no failures, warnings or info."""
        self.failures, self.warnings, self.info = [], [], {}

    def add(self, severity: str, code: str, detail: str, tickers=()):
        """Record one problem as a failure (`block`) or a warning."""
        entry = {"code": code, "detail": detail, "tickers": sorted(set(tickers))}
        (self.failures if severity == "block" else self.warnings).append(entry)

    def block(self, code, detail, tickers=()):
        """Record a failure that blocks the stage."""
        self.add("block", code, detail, tickers)

    def warn(self, code, detail, tickers=()):
        """Record a warning that does not block the stage."""
        self.add("warning", code, detail, tickers)


def run_status(cfg: dict) -> dict:
    """The market status (session, late run, in session) at the frozen clock."""
    return market_status.status(cfg, clock.clock())


def work_dir() -> Path:
    """The work/ folder of the data root."""
    return paths.ROOT / "work"
