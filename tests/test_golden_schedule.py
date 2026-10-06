"""The golden harness's parallel schedule (tests/golden/parallel.py): every step has a declared
access, and the declarations order what must stay ordered. The declarations themselves are checked
against the serial run: `golden.py record --serial` then `compare` (parallel) must be identical
(docs/REFACTOR_PLAN.md, section 1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "golden"))

import golden  # noqa: E402
import parallel  # noqa: E402


def test_every_step_has_declared_access():
    for market in golden.MARKETS:
        labels = {label for _, label, _, _ in golden.steps(market)}
        assert labels <= set(parallel.ACCESS), labels - set(parallel.ACCESS)


def test_writers_keep_their_order():
    for market in golden.MARKETS:
        for phase in golden.PHASES:
            labels = [s[1] for s in golden.steps(market) if s[0] == phase]
            deps = parallel.dependencies(labels)
            for j, label in enumerate(labels):
                if label == "validate_all":
                    assert deps[j] == set(range(j))   # reads everything: waits for every earlier step
                if label == "replay_aci":
                    assert labels.index("replay") in deps[j]   # both append to data/<market>/replays
                if label in ("context", "context_after_ranges"):
                    assert labels.index("ranges" if label == "context_after_ranges" else "calibrate") in deps[j]
