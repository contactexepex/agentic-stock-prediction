"""A trader's file through `add` (B3; docs/SPEC.md F4.2-F4.3): one retry, then abstentions; a late trader times out;
the kill switch; reruns add nothing. Also the registry, the input file and the CLI. Offline, fixtures only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from traders_fixtures import AS_OF, PROMPTS, REPO, agent_record, inputs

from marketbrief.core import paths
from marketbrief.traders import outcome, prepare
from marketbrief.traders import registry as registry_module
from marketbrief.traders.registry import load_traders, trader, trader_problems

NEWS, PATTERN, COMBINED, OPUS = PROMPTS
ABSTAIN = {"strategy_id": NEWS, "ticker": "AAPL", "abstain": True, "horizons": [1, 3, 5],
           "reason": "No verified news on the company this week.", "made_at": "2026-10-07T11:45:00Z",
           "prompt_version": "trader-news-v1"}


def two_companies(**changes):
    """NVDA (fixture ranges) and AAPL (active, no ranges: it must abstain)."""
    base = inputs()
    feats = {**base.features, "AAPL": {"as_of_date": AS_OF, "quality": "OK", "days_to_earnings": 20}}
    return inputs(active={"NVDA", "AAPL"}, features=feats, amounts={"NVDA": 1000.0, "AAPL": 1000.0}, **changes)


def write(path: Path, lines: list) -> Path:
    path.write_text("".join((json.dumps(x) if isinstance(x, dict) else x) + "\n" for x in lines))
    return path


def stored(root: Path, kind: str) -> list[dict]:
    files = sorted((root / "data" / "us" / kind).rglob("*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text().splitlines()]


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    return tmp_path


def test_clean_file_is_stored_with_explicit_abstention(root):
    lines = [agent_record(NEWS, h) for h in (1, 3, 5)] + [ABSTAIN]
    path = write(root / "f.jsonl", lines)
    written = datetime(2026, 10, 7, 11, 45, tzinfo=timezone.utc).timestamp()
    os.utime(path, (written, written))            # a clockless trader's made_at is the file's write time
    code, summary = outcome.add(trader(NEWS), two_companies(), path, 1)
    assert code == 0 and summary["predictions"] == 3 and summary["abstentions"] == 1
    rows = stored(root, "strategy_predictions")
    assert [r["id"] for r in rows] == [f"{NEWS}:{AS_OF}-NVDA-{h}d" for h in (1, 3, 5)]
    assert rows[0]["made_at"] == "2026-10-07T11:45:00Z"
    (skip,) = stored(root, "strategy_abstentions")
    assert skip["id"] == f"{NEWS}:{AS_OF}-AAPL" and skip["reason_code"] == "abstained" and skip["horizons"] == [1, 3, 5]
    assert skip["reason"] == ABSTAIN["reason"] and skip["session_date"] == "2026-10-07"
    # a rerun adds nothing
    gi = two_companies(stored_predictions={r["id"] for r in rows}, stored_abstentions={skip["id"]})
    code, summary = outcome.add(trader(NEWS), gi, root / "f.jsonl", 1)
    assert code == 0 and summary["predictions"] == 0 and summary["abstentions"] == 0


def test_one_retry_then_gate_failed_abstentions(root):
    bad = agent_record(NEWS, 5, evidence_ids=["0000invented0000"])
    lines = [agent_record(NEWS, 1), agent_record(NEWS, 3), bad]      # AAPL missing entirely
    path = write(root / "f.jsonl", lines)
    code, summary = outcome.add(trader(NEWS), two_companies(), path, 1)
    assert code == 1 and summary["predictions"] == 0 and not (root / "data").exists()
    assert {e["code"] for e in summary["errors"]} == {"EVIDENCE_UNKNOWN", "NO_RECORD"}
    code, summary = outcome.add(trader(NEWS), two_companies(), path, 2)
    assert code == 0 and summary["predictions"] == 2 and summary["abstentions"] == 2
    by_ticker = {r["ticker"]: r for r in stored(root, "strategy_abstentions")}
    assert by_ticker["NVDA"]["reason_code"] == "gate_failed" and by_ticker["NVDA"]["horizons"] == [5]
    assert by_ticker["NVDA"]["gate_codes"] == ["EVIDENCE_UNKNOWN"] and by_ticker["NVDA"]["attempts"] == 2
    assert by_ticker["AAPL"]["gate_codes"] == ["NO_RECORD"] and by_ticker["AAPL"]["horizons"] == [1, 3, 5]


def test_late_trader_abstains_with_timeout(root):
    late = datetime(2026, 10, 7, 13, 16, tzinfo=timezone.utc)          # deadline 13:15 UTC (open 13:30 - 15 min)
    lines = [agent_record(NEWS, h) for h in (1, 3, 5)] + [ABSTAIN]
    code, summary = outcome.add(trader(NEWS), two_companies(now=late), write(root / "f.jsonl", lines), 1)
    assert code == 0 and summary["status"] == "timeout" and summary["predictions"] == 0
    rows = stored(root, "strategy_abstentions")
    assert {r["ticker"]: r["reason_code"] for r in rows} == {"AAPL": "timeout", "NVDA": "timeout"}
    assert not (root / "data" / "us" / "strategy_predictions").exists()


def test_blocked_and_earnings_companies_get_their_own_codes(root):
    feats = {"NVDA": {"as_of_date": AS_OF, "quality": "BLOCKED", "days_to_earnings": 30},
             "AAPL": {"as_of_date": AS_OF, "quality": "OK", "days_to_earnings": 0}}
    gi = inputs(active={"NVDA", "AAPL"}, features=feats, amounts={"NVDA": 1000.0, "AAPL": 1000.0})
    code, summary = outcome.add(trader(NEWS), gi, write(root / "f.jsonl", [agent_record(NEWS, 1)]), 2)
    assert code == 0 and summary["predictions"] == 0
    rows = {r["ticker"]: r for r in stored(root, "strategy_abstentions")}
    assert rows["NVDA"]["reason_code"] == "blocked_quality" and rows["AAPL"]["reason_code"] == "earnings_window"


def test_kill_switch_records_killed_for_everyone(root, tmp_path):
    agents = tmp_path / "code" / ".claude" / "agents"
    agents.mkdir(parents=True)
    for name in registry_module.TRADER_FILES.values():
        text = (REPO / ".claude" / "agents" / name).read_text()
        agents.joinpath(name).write_text(text.replace("enabled: true", "enabled: false", 1))
    off = load_traders(tmp_path / "code")[NEWS]
    assert off.enabled is False
    code, summary = outcome.add(off, two_companies(), write(root / "f.jsonl", [agent_record(NEWS, 1)]), 1)
    assert code == 0 and summary["status"] == "killed"
    assert {r["reason_code"] for r in stored(root, "strategy_abstentions")} == {"killed"}


def test_registry_and_agent_files_agree():
    assert trader_problems() == []
    traders = load_traders()
    assert set(traders) == set(PROMPTS)
    assert {k: t.prompt_version for k, t in traders.items()} == PROMPTS
    assert traders[OPUS].agent_file.name == "forecaster.md" and traders[OPUS].agent_model.startswith("claude-opus")
    assert all(t.horizons == (1, 3, 5) for t in traders.values())
    assert [k for k, t in traders.items() if t.sees_model_score] == [OPUS, COMBINED]
    for name in ("trader-news-results.md", "trader-pattern-mood.md", "trader-combined.md"):
        front = (REPO / ".claude" / "agents" / name).read_text().split("---")[1]
        assert "tools: Read, Write\n" in front     # no Bash: the blind traders cannot query the model score


def test_input_file_keeps_blind_traders_blind():
    pack = ("## Market regime (latest)\n\nTRENDING\n\n## Indicators (latest snapshot)\n\n| NVDA |\n\n"
            "## Signal model: P(up) per ticker\n\n| 2026-10-06-NVDA-1d | 0.5660 |\n\n"
            "## News events and verification status\n\n| a41c9e07b2d35f18 | corroborated |\n\n"
            "## Open predictions\n\n| forecaster call |\n\n## Lessons from past calls\n\nlesson\n")
    texts = {sid: prepare.build(trader(sid), inputs(), pack) for sid in PROMPTS}
    news, summary = texts[NEWS]
    assert "Signal model" not in news and "P(up)" not in news and "Indicators" not in news
    assert "News events" in news and "Open predictions" not in news and "Lessons" not in news
    assert set(summary["left_out"]) == {"Market regime (latest)", "Indicators (latest snapshot)",
                                        "Signal model: P(up) per ticker", "Open predictions",
                                        "Lessons from past calls"}
    pattern = texts[PATTERN][0]
    assert "Signal model" not in pattern and "News events" not in pattern and "Indicators" in pattern
    combined = texts[COMBINED][0]
    assert "Signal model" in combined and "P(up) 0.5660" in combined and "News events" in combined
    assert "deadline 2026-10-07T13:15:00+00:00" in news and "N+3 = close of 2026-10-12" in news
    small = registry_module.Trader(**{**trader(COMBINED).__dict__, "budget": {"max_input_kb": 1, "max_minutes": 5}})
    text, cut = prepare.build(small, inputs(), pack)
    assert cut["cut"] and "Cut by the input budget" in text


def test_cli_commands_show_help():
    env = {**os.environ, "PYTHONPATH": str(REPO / "scripts")}
    for command in ("check", "prepare", "validate", "add", "eod-prepare", "eod-validate", "eod-add",
                    "director-prepare", "director-validate", "director-add"):
        result = subprocess.run([sys.executable, "-m", "marketbrief.traders", command, "--help"], cwd=REPO, env=env,
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, (command, result.stderr[-500:])
    result = subprocess.run([sys.executable, "-m", "marketbrief.traders", "--market", "us", "check"], cwd=REPO,
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0 and json.loads(result.stdout)["problems"] == []


def test_gate_stamps_made_at_from_the_file_time(root):
    """The Sonnet traders have no clock: a line without made_at gets the file's write time, capped at the gate's."""
    from marketbrief.traders.run import file_stamp
    lines = [{k: v for k, v in agent_record(NEWS, h).items() if k != "made_at"} for h in (1, 3, 5)]
    path = write(root / "f.jsonl", lines)
    written = datetime(2026, 10, 7, 11, 44, tzinfo=timezone.utc).timestamp()
    os.utime(path, (written, written))
    gi = inputs()
    assert file_stamp(path, gi) == "2026-10-07T11:44:00Z"
    code, summary = outcome.add(trader(NEWS), gi, path, 1)
    assert code == 0 and summary["predictions"] == 3
    assert {r["made_at"] for r in stored(root, "strategy_predictions")} == {"2026-10-07T11:44:00Z"}
    future = datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc).timestamp()
    os.utime(path, (future, future))
    assert file_stamp(path, gi) == "2026-10-07T11:50:00Z"          # capped at the gate's clock
    early = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc).timestamp()   # before the range was published
    os.utime(path, (early, early))
    errors = outcome.add(trader(NEWS), inputs(stored_predictions=set()), path, 1)[1]["errors"]
    assert {e["code"] for e in errors} == {"LOOK_AHEAD"}


def test_clockless_trader_made_at_is_always_the_stamp_and_a_clock_trader_keeps_its_own():
    """#88: a trader without Bash cannot know the time, so a made_at it states is replaced (warning); the Opus
    forecaster (Bash) keeps its own."""
    from marketbrief.traders.run import gate_lines
    assert trader(NEWS).has_clock is False and trader(OPUS).has_clock is True
    invented = agent_record(NEWS, 1, made_at="2026-10-07T09:00:00Z")
    gated = gate_lines([invented], trader(NEWS), inputs(), "2026-10-07T11:45:00Z")
    assert gated["rows"][0]["made_at"] == "2026-10-07T11:45:00Z"
    assert [w["code"] for w in gated["warnings"]] == ["MADE_AT_STAMPED"]
    own = agent_record(OPUS, 1, made_at="2026-10-07T11:44:00Z")
    kept = gate_lines([own], trader(OPUS), inputs(), "2026-10-07T11:46:00Z")
    assert kept["rows"][0]["made_at"] == "2026-10-07T11:44:00Z" and kept["warnings"] == []


def test_abstain_then_prediction_for_one_horizon_is_refused_and_abstain_time_is_checked():
    """#84: an abstain line before a prediction of the same horizon is a repeat; an abstain made after the gate's
    clock is refused."""
    from marketbrief.traders.run import abstain_errors, gate_lines
    skip = {**ABSTAIN, "ticker": "NVDA", "horizons": [1]}
    gated = gate_lines([skip, agent_record(NEWS, 1)], trader(NEWS), inputs(), None)
    assert gated["rows"] == [] and "TRADER_DUPLICATE" in {e["code"] for e in gated["errors"]}
    late = {**skip, "made_at": "2026-10-07T12:30:00Z"}          # the gate's clock is 11:50
    assert [code for code, _ in abstain_errors(late, trader(NEWS), inputs())] == ["TRADER_TIME"]
