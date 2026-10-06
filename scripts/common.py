"""Shared paths, schemas and DuckDB setup for the market-brief pipeline: a re-export shim.

The code lives in the marketbrief package (core: paths, clock, schemas, market config, storage, database,
cli; utils: markdown tables). Every old `common.<name>` still works. ROOT, CONFIG and CODE are properties
of this module that read and write marketbrief.core.paths, the one lookup point: assigning `common.ROOT`
(tests, ai_replay) redirects every reader of the data root, in this module and in the package."""
from __future__ import annotations

import sys
import types

from marketbrief.constants.collection import STALE_DAYS
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import FrozenClockConnection, clock, freeze_sql, utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.market_config import (benchmark_key, load_market, load_ranges_config, market_names,
                                            sector_etf_map, sector_etf_problems, symbols_by_role, vol_index_key)
from marketbrief.core.paths import data_dir
from marketbrief.core.schemas import ACCEPTED_KEYS, FEATURE_COLS, RELATION_SCHEMAS, SCHEMAS
from marketbrief.core.storage import append_jsonl, day_file, recent_ids
from marketbrief.utils.markdown import cursor_markdown_table as md_table

__all__ = [
    "ACCEPTED_KEYS", "FEATURE_COLS", "RELATION_SCHEMAS", "SCHEMAS", "STALE_DAYS", "FrozenClockConnection",
    "append_jsonl", "benchmark_key", "clock", "connect", "data_dir", "day_file", "freeze_sql", "load_market",
    "load_ranges_config", "market_arg", "market_names", "md_table", "recent_ids", "require_market",
    "sector_etf_map", "sector_etf_problems", "symbols_by_role", "utc_now", "utc_today", "vol_index_key",
]


def _forward_to_paths(name: str) -> property:
    """A module property that reads and writes marketbrief.core.paths.<name>."""

    def read(_module):
        return getattr(paths, name)

    def write(_module, value):
        setattr(paths, name, value)

    return property(read, write)


class _CommonModule(types.ModuleType):
    """The module type of `common`: ROOT, CONFIG and CODE live in marketbrief.core.paths."""

    ROOT = _forward_to_paths("ROOT")
    CONFIG = _forward_to_paths("CONFIG")
    CODE = _forward_to_paths("CODE")


sys.modules[__name__].__class__ = _CommonModule
