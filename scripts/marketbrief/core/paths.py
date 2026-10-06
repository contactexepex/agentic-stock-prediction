"""Where the code, the data root and the config folder are.

This module is the one lookup point for these paths: code reads `paths.ROOT` and `paths.CONFIG` at call
time, and the old `common.ROOT` / `common.CONFIG` names read and write these variables (tests and
ai_replay reassign them to point a run at a scratch root)."""
from __future__ import annotations

import os
from pathlib import Path

from marketbrief.constants.environment import ENV_CONFIG, ENV_ROOT
from marketbrief.constants.files import DIR_DATA

CODE = Path(__file__).resolve().parents[3]
ROOT = Path(os.environ.get(ENV_ROOT, CODE))
CONFIG = Path(os.environ.get(ENV_CONFIG, CODE / "config"))


def data_dir(market: str) -> Path:
    """The market's data tree: <root>/data/<market>."""
    return ROOT / DIR_DATA / market
