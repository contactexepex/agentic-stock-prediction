"""The build-work judge log (judgments/log.jsonl, CLAUDE.md "Judging every change") is
well-formed, append-only in spirit (one verdict per line) and only names commits that exist."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "judgments" / "log.jsonl"
KEYS = {"subject", "work", "commit", "round", "verdict", "summary", "recorded_at"}


def entries() -> list[dict]:
    return [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]


def test_log_lines_are_complete_verdicts():
    rows = entries()
    assert rows, "the judge log is empty"
    for r in rows:
        assert KEYS <= set(r), r
        assert r["verdict"] in ("PASS", "FAIL"), r
        assert isinstance(r["round"], int) and r["round"] >= 1, r
        assert r["summary"].strip(), r
        try:                                    # ISO UTC timestamp (early lines: a plain date)
            ts = datetime.fromisoformat(r["recorded_at"])
            assert ts.tzinfo is not None or len(r["recorded_at"]) == 10, r
        except ValueError:
            date.fromisoformat(r["recorded_at"])


def test_rounds_increase_per_subject():
    last: dict[str, int] = {}
    for r in entries():
        assert r["round"] >= last.get(r["subject"], 0), f"round went back for {r['subject']}"
        last[r["subject"]] = r["round"]


@pytest.mark.skipif(shutil.which("git") is None or not (REPO / ".git").exists(), reason="no git checkout")
def test_every_logged_commit_exists():
    missing = [r["commit"] for r in entries()
               if subprocess.run(["git", "cat-file", "-e", f"{r['commit']}^{{commit}}"], cwd=REPO,
                                 capture_output=True).returncode != 0]
    assert not missing, f"commits not in this repo: {missing}"
