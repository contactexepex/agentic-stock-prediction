"""Size limits of the refactor (docs/REFACTOR_PLAN.md): no module and no class under scripts/ longer
than MAX_LINES lines.

Today's offenders are listed with their current line count. The lists only shrink: a listed file
may not grow past its recorded count, and an entry must be removed once its file is within the
limit (or gone), so each refactor step that splits an offender also deletes its entry here."""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
MAX_LINES = 350

# module (repo-relative) -> its line count when listed (2026-10-06, commit 24749bd)
MODULE_ALLOWLIST: dict[str, int] = {
    "scripts/ai_replay.py": 1215,
    "scripts/replay.py": 1143,
    "scripts/review.py": 857,
    "scripts/neo4j_sync.py": 818,
    "scripts/validate.py": 815,
    "scripts/html_report.py": 772,
    "scripts/collect_prices.py": 641,
    "scripts/common.py": 625,
    "scripts/news_verify.py": 570,
    "scripts/collect_events.py": 478,
    "scripts/sec.py": 395,
    "scripts/news_clusters.py": 387,
    "scripts/lessons.py": 376,
    "scripts/report.py": 369,
    "scripts/backtest.py": 354,
    "scripts/range_inputs.py": 351,
}
# "module::Class" -> its line count when listed; no class is over the limit today
CLASS_ALLOWLIST: dict[str, int] = {}


def python_modules() -> list[Path]:
    return sorted(p for p in SCRIPTS.rglob("*.py") if "__pycache__" not in p.parts)


def module_lengths() -> dict[str, int]:
    return {p.relative_to(REPO).as_posix(): len(p.read_text(encoding="utf-8").splitlines()) for p in python_modules()}


def class_lengths() -> dict[str, int]:
    lengths = {}
    for path in python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                lengths[f"{path.relative_to(REPO).as_posix()}::{node.name}"] = node.end_lineno - start + 1
    return lengths


def size_problems(lengths: dict[str, int], allowlist: dict[str, int], what: str) -> list[str]:
    problems = []
    for name, lines in sorted(lengths.items()):
        if lines > MAX_LINES and name not in allowlist:
            problems.append(f"{what} {name} has {lines} lines (limit {MAX_LINES}); split it")
        elif name in allowlist and lines > allowlist[name]:
            problems.append(f"{what} {name} grew to {lines} lines (listed at {allowlist[name]}); it may only shrink")
    for name, listed in sorted(allowlist.items()):
        if name not in lengths:
            problems.append(f"{what} {name} is listed but no longer exists; remove its entry")
        elif lengths[name] <= MAX_LINES:
            problems.append(f"{what} {name} is now {lengths[name]} lines (within {MAX_LINES}); remove its entry")
    return problems


def test_modules_within_limit():
    assert size_problems(module_lengths(), MODULE_ALLOWLIST, "module") == []


def test_classes_within_limit():
    assert size_problems(class_lengths(), CLASS_ALLOWLIST, "class") == []


def test_size_problems_reports_each_case():
    allow = {"a.py": 400, "gone.py": 500, "small.py": 360}
    lengths = {"a.py": 401, "b.py": 351, "small.py": 300, "ok.py": 350}
    problems = size_problems(lengths, allow, "module")
    assert problems == [
        "module a.py grew to 401 lines (listed at 400); it may only shrink",
        "module b.py has 351 lines (limit 350); split it",
        "module gone.py is listed but no longer exists; remove its entry",
        "module small.py is now 300 lines (within 350); remove its entry",
    ]
