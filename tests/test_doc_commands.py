"""The commands that CLAUDE.md, routine/PROMPT.md, routine/NEWS_PROMPT.md and the agent files tell the daily run
to execute still work.

Every `python -c "..."` snippet is run from scripts/ (a `'...'` placeholder SQL becomes `SELECT 1`), and every
`python scripts/<name>.py` command must name an existing script whose `--help` exits 0. A moved or deleted
module that an agent is told to import or run therefore fails here, not in the daily run."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC_FILES = [REPO / "CLAUDE.md", REPO / "routine" / "PROMPT.md", REPO / "routine" / "NEWS_PROMPT.md",
             *sorted((REPO / ".claude" / "agents").glob("*.md"))]
INLINE_SNIPPET = re.compile(r'python3? -c "((?:[^"\\]|\\.)*)"')
SCRIPT_COMMAND = re.compile(r"python3? (scripts/[A-Za-z_0-9]+\.py)")


def doc_text() -> list[tuple[str, str]]:
    return [(path.relative_to(REPO).as_posix(), path.read_text(encoding="utf-8")) for path in DOC_FILES]


def inline_snippets() -> list[tuple[str, str]]:
    found = []
    for name, text in doc_text():
        for match in INLINE_SNIPPET.finditer(text):
            found.append((name, match.group(1).replace("'...'", "'SELECT 1'")))
    return found


def script_commands() -> list[str]:
    return sorted({match.group(1) for _, text in doc_text() for match in SCRIPT_COMMAND.finditer(text)})


def run_python(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO / "scripts")}
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120,
                          check=False)


def test_docs_contain_commands():
    assert inline_snippets(), "CLAUDE.md data rule 4 has a python -c snippet"
    assert "scripts/context.py" in script_commands()


@pytest.mark.parametrize("name,snippet", inline_snippets())
def test_inline_python_snippet_runs(name, snippet):
    result = run_python(["-c", snippet], REPO / "scripts")
    assert result.returncode == 0, f"{name}: {snippet}\n{result.stderr[-1500:]}"


@pytest.mark.parametrize("script", script_commands())
def test_script_command_exists_and_shows_help(script):
    assert (REPO / script).is_file(), f"{script} is named in the docs but does not exist"
    result = run_python([script, "--help"], REPO)
    assert result.returncode == 0, f"{script} --help failed:\n{result.stderr[-1500:]}"
