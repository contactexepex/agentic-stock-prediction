"""The result of a gate run (failures, warnings, info) and the run's shared lookups."""
from __future__ import annotations

from pathlib import Path
from marketbrief.pipeline import market_status
from marketbrief.core.settings import load_validate_config
from marketbrief.core import clock, paths


def load_config() -> dict:
    return load_validate_config()


class Result:
    def __init__(self):
        self.failures, self.warnings, self.info = [], [], {}

    def add(self, severity: str, code: str, detail: str, tickers=()):
        item = {"code": code, "detail": detail, "tickers": sorted(set(tickers))}
        (self.failures if severity == "block" else self.warnings).append(item)

    def block(self, code, detail, tickers=()):
        self.add("block", code, detail, tickers)

    def warn(self, code, detail, tickers=()):
        self.add("warning", code, detail, tickers)


def run_status(cfg: dict) -> dict:
    return market_status.status(cfg, clock.clock())


def work_dir() -> Path:
    return paths.ROOT / "work"
