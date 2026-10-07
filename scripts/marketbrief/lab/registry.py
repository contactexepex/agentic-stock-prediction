"""The strategy registry loader (config/strategies.yaml, format in marketbrief/contracts/strategies.py): the
horizon list (decision 37), the strategies per family and each entry's config hash."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml

from marketbrief.contracts.strategies import STRATEGIES_FILE
from marketbrief.core import paths
from marketbrief.lab.constants import FAMILY_AI, FAMILY_BASELINE, FAMILY_RULE


def load_registry(text: str | None = None) -> dict:
    """config/strategies.yaml as parsed (or `text`, for tests)."""
    if text is None:
        text = (paths.CONFIG / STRATEGIES_FILE).read_text(encoding="utf-8")
    return yaml.safe_load(text)


@lru_cache(maxsize=4)
def _cached(config_dir: str) -> dict:
    """The registry of a config folder, read once (the folder is the cache key)."""
    return yaml.safe_load((Path(config_dir) / STRATEGIES_FILE).read_text(encoding="utf-8"))


def registry() -> dict:
    """The registry of the current config folder (core.paths.CONFIG)."""
    return _cached(str(paths.CONFIG))


def horizons(reg: dict | None = None) -> tuple[int, ...]:
    """The horizon list N+k (`horizons`), sorted."""
    return tuple(sorted(int(k) for k in (reg or registry())["horizons"]))


def strategies(reg: dict | None = None, family: str | None = None) -> list[dict]:
    """The strategy entries, optionally of one family, in file order."""
    entries = (reg or registry())["strategies"]
    return [spec for spec in entries if family is None or spec["family"] == family]


def by_id(reg: dict | None = None) -> dict[str, dict]:
    """{strategy_id: entry}."""
    return {spec["id"]: spec for spec in strategies(reg)}


def rule_and_baselines(reg: dict | None = None) -> list[dict]:
    """The entries this session predicts for (rule strategies and baselines; AI traders are B3's)."""
    return [spec for spec in strategies(reg) if spec["family"] in (FAMILY_RULE, FAMILY_BASELINE)]


def head_to_head_families() -> tuple[str, ...]:
    """The families that contend in the head-to-head view (baselines are the yardstick, F1.7.1)."""
    return (FAMILY_RULE, FAMILY_AI)


def config_hash(spec: dict) -> str:
    """sha256 of the entry's canonical JSON (stored with each prediction)."""
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
