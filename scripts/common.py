"""The one patch point for the data root and the config folder: `common.ROOT`, `common.CONFIG` and `common.CODE`
are properties that read and write marketbrief.core.paths, so a test (or ai_replay) that assigns `common.ROOT`
redirects every reader of the data root. All other code lives in the marketbrief package; import it from there."""
from __future__ import annotations

import sys
import types

from marketbrief.core import paths


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
