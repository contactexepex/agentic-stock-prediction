"""The traders' input in parts and the input_check (B19's report of 2026-10-09: a trader read 343 of 432 lines of its
input and abstained on everything). Offline; outcome.add on fixtures (traders_fixtures.py)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from traders_fixtures import AS_OF, PROMPTS, agent_record, inputs

from marketbrief.core import paths
from marketbrief.traders import input_parts, outcome
from marketbrief.traders.registry import trader

NEWS = "ai.news_results.sonnet.v1"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    return tmp_path


def big_input() -> str:
    """About 130 KB: a 432-line pack with one 3000-character line."""
    lines = [f"| T{n:03d} | " + "word " * 58 + "|" for n in range(430)]
    return "# Input\n" + "\n".join(lines[:200]) + "\n" + "x " * 1500 + "\n" + "\n".join(lines[200:]) + "\n"


def test_parts_fit_one_read_and_keep_every_word(tmp_path):
    text = big_input()
    parts, check = input_parts.write_parts(tmp_path, NEWS, text)
    assert len(parts) == 6 and parts[0].name == f"{NEWS}.md" and parts[1].name == f"{NEWS}.part2.md"
    bodies = [p.read_text(encoding="utf-8") for p in parts]
    assert all(len(b.encode()) <= input_parts.PART_BYTES + 400 for b in bodies)
    assert all(len(line) <= 2000 for b in bodies for line in b.splitlines())
    assert all(f"work/traders/{p.name}" in bodies[0] for p in parts)       # part 1 names every part
    tags = [b.rstrip().splitlines()[-1].split("check fragment ")[1].split(" ")[0] for b in bodies]
    assert check == "-".join(tags) and input_parts.expected(tmp_path, NEWS) == check
    words = " ".join(" ".join(b.splitlines()[2:-2]) for b in bodies).split()
    assert words == text.split()                                           # wrapping only moves line breaks


def test_rerun_removes_stale_parts(tmp_path):
    input_parts.write_parts(tmp_path, NEWS, big_input())
    parts, _ = input_parts.write_parts(tmp_path, NEWS, "# small\n")
    assert len(parts) == 1 and sorted(p.name for p in tmp_path.glob(f"{NEWS}*.md")) == [f"{NEWS}.md"]


def two_companies():
    base = inputs()
    feats = {**base.features, "AAPL": {"as_of_date": AS_OF, "quality": "OK", "days_to_earnings": 20}}
    return inputs(active={"NVDA", "AAPL"}, features=feats, amounts={"NVDA": 1000.0, "AAPL": 1000.0})


def run(root, lines, attempt):
    path = root / f"{NEWS}.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    written = datetime(2026, 10, 7, 11, 45, tzinfo=timezone.utc).timestamp()
    os.utime(path, (written, written))
    return outcome.add(trader(NEWS), two_companies(), path, attempt)


def stored(root, kind):
    return [json.loads(line) for f in sorted((root / "data" / "us" / kind).rglob("*.jsonl"))
            for line in f.read_text().splitlines()]


def abstain(**changes):
    return {"strategy_id": NEWS, "ticker": "AAPL", "abstain": True, "horizons": [1, 3, 5],
            "reason": "No verified news on the company this week.", "prompt_version": PROMPTS[NEWS], **changes}


def test_lines_with_the_check_are_stored_and_the_field_is_not(root):
    _, check = input_parts.write_parts(root, NEWS, big_input())
    lines = [agent_record(NEWS, h, input_check=check) for h in (1, 3, 5)] + [abstain(input_check=check)]
    code, summary = run(root, lines, 1)
    assert code == 0 and summary["predictions"] == 3 and summary["abstentions"] == 1
    assert all("input_check" not in row for row in stored(root, "strategy_predictions"))


def test_partial_read_is_refused_then_gate_failed(root):
    """A line without the check of every part (the trader stopped early) is never stored, prediction or abstention."""
    _, check = input_parts.write_parts(root, NEWS, big_input())
    first_two = "-".join(check.split("-")[:2])
    lines = [agent_record(NEWS, 1, input_check=check), agent_record(NEWS, 3, input_check=first_two),
             agent_record(NEWS, 5), abstain(input_check=first_two)]
    code, summary = run(root, lines, 1)
    assert code == 1 and {e["code"] for e in summary["errors"]} == {"INPUT_UNREAD"}
    assert sorted(e["line"] for e in summary["errors"]) == [2, 3, 4]
    code, summary = run(root, lines, 2)
    assert code == 0 and summary["predictions"] == 1
    by_ticker = {r["ticker"]: r for r in stored(root, "strategy_abstentions")}
    assert by_ticker["NVDA"]["reason_code"] == "gate_failed" and by_ticker["NVDA"]["horizons"] == [3, 5]
    assert by_ticker["AAPL"]["reason_code"] == "gate_failed" and by_ticker["AAPL"]["gate_codes"] == ["INPUT_UNREAD"]


def test_without_a_prepare_run_the_check_is_off(root):
    lines = [agent_record(NEWS, h) for h in (1, 3, 5)] + [abstain()]
    code, summary = run(root, lines, 1)
    assert code == 0 and summary["predictions"] == 3
