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


# The first 17 lines were written on 2026-10-05 with a plain date. The log is append-only, so they
# stay; every later line must carry a full ISO timestamp in UTC.
DATE_ONLY_LINES = 17


def test_recorded_at_is_iso_utc():
    for n, r in enumerate(entries(), 1):
        if n <= DATE_ONLY_LINES:
            assert date.fromisoformat(r["recorded_at"]), r
            continue
        ts = datetime.fromisoformat(r["recorded_at"])
        assert len(r["recorded_at"]) > 10 and ts.utcoffset() is not None and ts.utcoffset().total_seconds() == 0, \
            f"line {n}: recorded_at must be ISO UTC, got {r['recorded_at']!r}"


def round_problems(rows: list[dict]) -> list[str]:
    """Rounds of one subject never go back, except that round 1 may start a new cycle after a PASS
    (e.g. a later end-to-end `integration` review of new work); an unfinished FAIL cycle may not restart."""
    problems, last = [], {}
    for row in rows:
        previous = last.get(row["subject"])
        if previous is not None and row["round"] < previous["round"]:
            if not (row["round"] == 1 and previous["verdict"] == "PASS"):
                problems.append(f"round went back for {row['subject']}: {previous['round']} -> {row['round']}")
        last[row["subject"]] = row
    return problems


def test_rounds_increase_per_subject():
    assert round_problems(entries()) == []


def test_round_check_on_synthetic_logs():
    def line(subject, round_, verdict):
        return {"subject": subject, "round": round_, "verdict": verdict}

    assert round_problems([line("a", 3, "PASS"), line("a", 2, "PASS")]) != []   # 3 -> 2 fails
    assert round_problems([line("a", 2, "PASS"), line("a", 1, "PASS")]) == []   # PASS then 1 passes
    assert round_problems([line("a", 2, "FAIL"), line("a", 1, "FAIL")]) != []   # FAIL then 1 fails
    assert round_problems([line("a", 1, "FAIL"), line("a", 2, "PASS"), line("b", 1, "PASS")]) == []


@pytest.mark.skipif(shutil.which("git") is None or not (REPO / ".git").exists(), reason="no git checkout")
def test_every_logged_commit_exists():
    missing = [r["commit"] for r in entries()
               if subprocess.run(["git", "cat-file", "-e", f"{r['commit']}^{{commit}}"], cwd=REPO,
                                 capture_output=True).returncode != 0]
    assert not missing, f"commits not in this repo: {missing}"
