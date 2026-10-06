"""Reflection log (scripts/lessons.py): deterministic facts of settled calls, validation of the
reflector's lessons, append-only storage, and the context pack's "Lessons" section, which shows a
lesson only once it was available (available_from <= the run's clock, MB_NOW-aware)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lessons  # noqa: E402
from test_pipeline import MARKET, SCRIPTS, setup  # noqa: E402

P1, P2, P3 = "2026-08-03-AAPL-5d", "2026-08-10-MSFT-1d", "2026-08-12-AAPL-1d"
OPEN = "2026-08-14-MSFT-5d"          # a stored call with no outcome yet (not settled)
P1_SCORED, P1_RANGE_SCORED = "2026-08-11T12:10:00+00:00", "2026-08-11T12:11:00+00:00"
P2_SCORED = "2026-08-12T12:10:00+00:00"


def jl(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    p = root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def pred(pid: str, made_at: str, direction: str, conf: float, ev: list[str], rationale: str) -> dict:
    as_of, t, h = pid[:10], pid[11:].rsplit("-", 1)[0], int(pid.rsplit("-", 1)[1][:-1])
    return {"id": pid, "made_at": made_at, "as_of_date": as_of, "ticker": t, "horizon_days": h,
            "direction": direction, "confidence": conf, "rationale": rationale, "evidence_ids": ev,
            "prompt_version": "forecast-v7", "range_widen": None}


def rng(pid: str, made_at: str, target: str, lo80, lo50, hi50, hi80) -> dict:
    as_of, t, h = pid[:10], pid[11:].rsplit("-", 1)[0], int(pid.rsplit("-", 1)[1][:-1])
    return {"id": pid, "made_at": made_at, "as_of_date": as_of, "session_date": target, "target_date": target,
            "ticker": t, "horizon_days": h, "base_close": 100.0, "center": 0.0, "sigma_h": 0.02, "lo50": lo50,
            "hi50": hi50, "lo80": lo80, "hi80": hi80, "naive_lo50": None, "naive_hi50": None, "naive_lo80": None,
            "naive_hi80": None, "direction": None, "confidence": None, "regime": "NORMAL", "calibration_id": None,
            "notes": [], "inputs": [], "iv_sigma_h": None}


def build(tmp: Path, perturb: bool = False) -> tuple[Path, Path]:
    """Three settled calls: P1 (AAPL 5d, hit, range scored), P2 (MSFT 1d, miss, no range), P3 (settled
    but its range is still open, so it waits). perturb=True changes only what became known after
    2026-08-12T00:00Z: P2's outcome, a P2 lesson, and a later outcome and lesson for P3."""
    root, cfg = setup(tmp)
    jl(root, "news", "2026-08-03", [{"id": "n1", "title": "Apple raises guidance", "url": "u", "source": "s",
                                     "published_at": "2026-08-03T15:00:00+00:00",
                                     "first_seen_at": "2026-08-03T15:05:00+00:00", "feed": "f",
                                     "category": "general", "tickers": ["AAPL"]}])
    jl(root, "predictions", "2026-08-04", [pred(P1, "2026-08-04T12:00:00+00:00", "up", 0.62, ["n1"],
                                                "Guidance raised; RSI 45 leaves room.")])
    jl(root, "predictions", "2026-08-11", [pred(P2, "2026-08-11T12:00:00+00:00", "down", 0.55, ["n1"], "Peer weakness.")])
    jl(root, "predictions", "2026-08-13", [pred(P3, "2026-08-13T12:00:00+00:00", "up", 0.6, ["n1"], "Momentum.")])
    jl(root, "predictions", "2026-08-17", [pred(OPEN, "2026-08-17T12:00:00+00:00", "up", 0.6, ["n1"],
                                                "Open call: no outcome yet.")])
    jl(root, "ranges", "2026-08-04", [rng(P1, "2026-08-04T12:05:00+00:00", "2026-08-11", 95.0, 98.0, 102.0, 104.0)])
    jl(root, "ranges", "2026-08-13", [rng(P3, "2026-08-13T12:05:00+00:00", "2026-08-13", 97.0, 99.0, 101.0, 103.0)])
    jl(root, "outcomes", "2026-08-11", [
        {"prediction_id": P1, "scored_at": P1_SCORED, "base_date": "2026-08-03", "base_close": 100.0,
         "target_date": "2026-08-10", "target_close": 103.2, "actual_return": 0.032, "hit": True}])
    jl(root, "range_outcomes", "2026-08-11", [
        {"range_id": P1, "scored_at": P1_RANGE_SCORED, "target_date": "2026-08-11", "actual_close": 103.2, "z": 1.5,
         "hit50": False, "hit80": True, "naive_hit50": None, "naive_hit80": None, "is80_pct": 9.0,
         "naive_is80_pct": None, "width80_pct": 9.0, "naive_width80_pct": None, "center_err_pct": 3.2,
         "naive_center_err_pct": 3.2}])
    jl(root, "outcomes", "2026-08-12", [
        {"prediction_id": P2, "scored_at": P2_SCORED, "base_date": "2026-08-10", "base_close": 200.0,
         "target_date": "2026-08-11", "target_close": 230.0 if perturb else 202.0,
         "actual_return": 0.15 if perturb else 0.01, "hit": False}])
    jl(root, "outcomes", "2026-08-14", [
        {"prediction_id": P3, "scored_at": "2026-08-14T12:10:00+00:00", "base_date": "2026-08-12", "base_close": 100.0,
         "target_date": "2026-08-13", "target_close": 99.0 if perturb else 100.5,
         "actual_return": -0.01 if perturb else 0.005, "hit": not perturb}])
    if perturb:   # lessons that only became available after 2026-08-12T00:00Z
        jl(root, "lessons", "2026-08-12", [stored_lesson(P2, "MSFT", P2_SCORED, "A 15% squeeze; peers misled.")])
        jl(root, "lessons", "2026-08-20", [stored_lesson(P3, "AAPL", "2026-08-20T12:00:00+00:00", "Later lesson.")])
    return root, cfg


def stored_lesson(pid: str, ticker: str, available_from: str, text: str, hit: bool = False, ret: float = 0.01,
                  written_at: str | None = None) -> dict:
    return {"id": f"lesson-{pid}", "prediction_id": pid, "ticker": ticker, "horizon_days": 1,
            "as_of_date": pid[:10], "made_at": available_from, "direction": "up", "confidence": 0.6, "rationale": "r",
            "evidence_ids": ["n1"], "call_prompt_version": "forecast-v7", "base_date": pid[:10], "base_close": 100.0,
            "target_date": available_from[:10], "target_close": 100 * (1 + ret), "actual_return": ret, "hit": hit,
            "range_id": None, "range_target_date": None, "range_actual_close": None, "lo80": None, "lo50": None,
            "hi50": None, "hi80": None, "hit50": None, "hit80": None, "range_position": None,
            "settled_at": available_from, "available_from": available_from, "lesson": text,
            "prompt_version": "reflect-v1", "written_at": written_at or available_from}


def run(root: Path, cfg: Path, *args: str, now: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET}
    env.pop("MB_NOW", None)
    if now:
        env["MB_NOW"] = now
    return subprocess.run([sys.executable, *args], cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)


def write(path: Path, rows: list) -> Path:
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))
    return path


def lessons_section(root: Path, cfg: Path, now: str) -> str:
    p = run(root, cfg, str(SCRIPTS / "context.py"), now=now)
    assert p.returncode == 0, p.stderr
    out = p.stdout
    start = out.index("## Lessons from past calls")
    return out[start:out.index("\n## ", start + 5)]


GOOD1 = "Called up at 0.62 on raised guidance; AAPL rose 3.2% to 103.2, above the 50% band but inside the 80% band. " \
        "Guidance news carried the move; the range was too narrow on the upside."
GOOD2 = "Called down at 0.55 on peer weakness; MSFT rose 1.0% instead. Peer weakness alone did not predict this stock."


def test_prepare_facts_are_deterministic(tmp_path):
    root, cfg = build(tmp_path)
    out = tmp_path / "facts.jsonl"
    p = run(root, cfg, "lessons.py", "prepare", "--out", str(out))
    assert p.returncode == 0, p.stderr
    s = json.loads(p.stdout)
    assert s["n"] == 2 and s["waiting_for_range"] == [P3]             # P3's range is open, not late: it waits
    facts = {f["prediction_id"]: f for f in map(json.loads, out.read_text().splitlines())}
    f1 = facts[P1]
    assert (f1["hit"], f1["actual_return"], f1["target_close"], f1["range_position"]) == (True, 0.032, 103.2,
                                                                                           "in_80_above_50")
    assert (f1["hit50"], f1["hit80"], f1["lo80"], f1["hi80"]) == (False, True, 95.0, 104.0)
    assert f1["settled_at"] == P1_SCORED and f1["available_from"] == P1_RANGE_SCORED   # the later of the two
    assert f1["evidence"] == [{"id": "n1", "kind": "news", "text": "Apple raises guidance",
                               "at": "2026-08-03T15:00:00+00:00"}]
    f2 = facts[P2]
    assert f2["range_id"] is None and f2["available_from"] == P2_SCORED and f2["hit"] is False


def test_validate_catches_wrong_numbers_and_ids(tmp_path):
    root, cfg = build(tmp_path)
    rows = [{"prediction_id": P1, "lesson": GOOD1, "prompt_version": "reflect-v1"},                       # 1 valid
            {"prediction_id": P2, "lesson": GOOD2, "prompt_version": "reflect-v1", "hit": False,
             "actual_return": 0.01},                                                                        # 2 valid
            {"prediction_id": P1, "lesson": GOOD1.replace("3.2%", "4.1%"), "prompt_version": "reflect-v1"},  # 3
            {"prediction_id": "2026-08-03-NFLX-5d", "lesson": "No such call.", "prompt_version": "reflect-v1"},  # 4
            {"prediction_id": P3, "lesson": "Range still open.", "prompt_version": "reflect-v1"},           # 5
            {"prediction_id": OPEN, "lesson": "Not settled.", "prompt_version": "reflect-v1"},             # 6
            {"prediction_id": P2, "lesson": "Wrong copied fact.", "prompt_version": "reflect-v1", "hit": True},  # 7
            {"prediction_id": P2, "lesson": "MSFT fell -1.0% as called.", "prompt_version": "reflect-v1"},  # 8
            {"prediction_id": P2, "lesson": " ".join(["word"] * 61), "prompt_version": "reflect-v1"},       # 9
            {"prediction_id": P2, "lesson": "ok", "prompt_version": "reflect-v1", "foo": 1},               # 10
            {"prediction_id": P2, "lesson": "Range was 93.5 wide.", "prompt_version": "reflect-v1"},        # 11
            "{not json"]                                                                                    # 12
    p = run(root, cfg, "lessons.py", "validate", str(write(tmp_path / "l.jsonl", rows)))
    assert p.returncode == 1
    out = json.loads(p.stdout)
    errs = {e["line"]: " ".join(e["errors"]) for e in out["errors"]}
    expect = {3: "number 4.1%", 4: "does not exist or is not settled", 5: "range is still open",
              6: "does not exist or is not settled", 7: "hit is True but the stored value is False",
              8: "wrong sign", 9: "1-60 words", 10: "unknown field", 11: "number 93.5", 12: "not a JSON object"}
    assert set(errs) == set(expect), errs
    for line, word in expect.items():
        assert word in errs[line], (line, errs[line])
    # lines 7-11 repeat P2 after the valid line 2: each is also a duplicate in the file
    assert all("duplicate lesson" in errs[i] for i in (7, 8, 9, 10, 11))
    assert out["valid"] == 2 and out["appended"] == 0
    assert not (root / "data" / MARKET / "lessons").exists()


def test_validate_unit_checks():
    f = {"prediction_id": P1, "ticker": "AAPL", "horizon_days": 5, "confidence": 0.62, "actual_return": 0.032,
         "base_close": 100.0, "target_close": 103.2, "range_actual_close": 103.2, "lo80": 95.0, "lo50": 98.0,
         "hi50": 102.0, "hi80": 104.0, "evidence_ids": ["n1"], "rationale": "RSI 45."}
    assert lessons.text_number_errors(GOOD1, f) == []
    assert lessons.text_number_errors("Closed 1.2% above the 50% band on 2026-08-10; RSI 45 misled.", f) == []
    assert lessons.text_number_errors("Rose +3.2%, conf 62%, 5-day call.", f) == []
    assert lessons.text_number_errors("Fell -3.2%.", f)                      # wrong sign
    assert lessons.text_number_errors("Rose 3.5%.", f)                       # wrong return
    assert lessons.text_number_errors("Rose 3%.", f) == []                   # rounding to what is shown
    assert lessons.text_number_errors("Rose 7%.", f)                         # matches no % value
    assert lessons.text_number_errors("Closed at 3.2.", f)                   # a return needs its % sign
    assert lessons.text_number_errors("Closed 103.2%.", f)                   # a close is not a percentage
    assert lessons.position(94, 95, 98, 102, 104) == "below_80" and lessons.position(100, 95, 98, 102, 104) == "in_50"


def test_add_appends_once_with_recomputed_facts(tmp_path):
    root, cfg = build(tmp_path)
    f = write(tmp_path / "l.jsonl", [{"prediction_id": P1, "lesson": GOOD1, "prompt_version": "reflect-v1"},
                                     {"prediction_id": P2, "lesson": GOOD2, "prompt_version": "reflect-v1"}])
    bad = write(tmp_path / "bad.jsonl", [{"prediction_id": P1, "lesson": GOOD1.replace("3.2%", "9.9%"),
                                          "prompt_version": "reflect-v1"}])
    p = run(root, cfg, "lessons.py", "add", str(bad))
    assert p.returncode == 1 and json.loads(p.stdout)["appended"] == 0
    assert not (root / "data" / MARKET / "lessons").exists()               # all or nothing
    p = run(root, cfg, "lessons.py", "add", str(f))
    assert p.returncode == 0, p.stderr
    stored = [json.loads(x) for g in (root / "data" / MARKET / "lessons").glob("**/*.jsonl")
              for x in g.read_text().splitlines()]
    assert sorted(s["id"] for s in stored) == [f"lesson-{P1}", f"lesson-{P2}"]
    s1 = next(s for s in stored if s["prediction_id"] == P1)
    assert s1["available_from"] == P1_RANGE_SCORED and s1["settled_at"] == P1_SCORED and s1["lesson"] == GOOD1
    assert set(s1) == set(lessons.FACT_FIELDS) | {"lesson", "prompt_version", "written_at"}
    p = run(root, cfg, "lessons.py", "add", str(f))                        # a second add is refused
    assert p.returncode == 1 and "already stored" in p.stdout
    p = run(root, cfg, "lessons.py", "prepare", "--out", str(tmp_path / "facts.jsonl"))
    assert json.loads(p.stdout)["n"] == 0                                  # nothing left to write


def test_lesson_never_visible_before_available_from(tmp_path):
    root, cfg = build(tmp_path)
    p = run(root, cfg, "lessons.py", "add", str(write(tmp_path / "l.jsonl", [
        {"prediction_id": P1, "lesson": GOOD1, "prompt_version": "reflect-v1"}])))
    assert p.returncode == 0, p.stderr
    before_outcome = lessons_section(root, cfg, "2026-08-11T12:09:59+00:00")
    between = lessons_section(root, cfg, "2026-08-11T12:10:30+00:00")      # call scored, range not yet
    at = lessons_section(root, cfg, P1_RANGE_SCORED)
    assert "_none_" in before_outcome and "_none_" in between
    assert P1 in at and "in_80_above_50" in at and "+3.20" in at and "| hit |" in at


def test_future_outcomes_change_nothing_at_a_past_made_at(tmp_path):
    made_at = "2026-08-12T00:00:00+00:00"
    secs = {}
    for name, perturb in (("base", False), ("perturbed", True)):
        root, cfg = build(tmp_path / name, perturb=perturb)
        p = run(root, cfg, "lessons.py", "add", str(write(tmp_path / f"{name}.jsonl", [
            {"prediction_id": P1, "lesson": GOOD1, "prompt_version": "reflect-v1"}])))
        assert p.returncode == 0, p.stderr
        secs[name] = (lessons_section(root, cfg, made_at), lessons_section(root, cfg, "2026-08-21T00:00:00+00:00"))
    assert secs["base"][0] == secs["perturbed"][0]                          # identical at the past made_at
    assert P1 in secs["base"][0] and P2 not in secs["base"][0]
    assert secs["base"][1] != secs["perturbed"][1]                          # the perturbation is real later on
    assert "A 15% squeeze" in secs["perturbed"][1] and "Later lesson." in secs["perturbed"][1]


def test_context_section_last3_per_ticker_and_market_wide(tmp_path):
    root, cfg = setup(tmp_path)
    days = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]
    rows = [stored_lesson(f"{d}-AAPL-1d", "AAPL", f"{d}T20:00:00+00:00", f"AAPL lesson {i}.", hit=i % 2 == 0)
            for i, d in enumerate(days)]
    rows.append(stored_lesson("2026-08-04-MSFT-1d", "MSFT", "2026-08-04T21:00:00+00:00", "MSFT lesson."))
    # a correction of AAPL lesson 4 written later: the newest version is shown
    rows.append(stored_lesson("2026-08-07-AAPL-1d", "AAPL", "2026-08-07T20:00:00+00:00", "AAPL lesson 4 corrected.",
                              hit=True, written_at="2026-08-07T21:00:00+00:00"))
    jl(root, "lessons", "2026-08-07", rows)
    sec = lessons_section(root, cfg, "2026-08-10T12:00:00+00:00")
    market_wide, per_ticker = sec.split("Last 3 per ticker:")
    assert "Most recent 3, market-wide" in market_wide
    assert [x for x in ("AAPL lesson 4 corrected.", "AAPL lesson 3.", "AAPL lesson 2.", "AAPL lesson 1.",
                        "MSFT lesson.") if x in market_wide] == ["AAPL lesson 4 corrected.", "AAPL lesson 3.",
                                                                 "AAPL lesson 2."]
    aapl = [line for line in per_ticker.splitlines() if line.startswith("| AAPL")]
    assert len(aapl) == 3 and "AAPL lesson 4 corrected." in aapl[0] and "AAPL lesson 2." in aapl[2]
    assert "| AAPL lesson 4. |" not in sec and "AAPL lesson 0." not in sec
    assert any("MSFT lesson." in line for line in per_ticker.splitlines() if line.startswith("| MSFT"))
    # as of a day earlier, only what was available by then
    early = lessons_section(root, cfg, "2026-08-04T20:30:00+00:00")
    assert "AAPL lesson 1." in early and "MSFT lesson." not in early and "AAPL lesson 2." not in early


def test_ai_replay_keeps_lessons_by_available_from():
    import ai_replay as ar
    d, cut = date(2026, 8, 14), pd.Timestamp("2026-08-17T12:15:00+00:00")
    assert ar.keep_row("lessons", {"available_from": "2026-08-14T22:00:00+00:00", "target_date": "2026-08-14"}, d, cut)
    assert not ar.keep_row("lessons", {"available_from": "2026-08-17T12:16:00+00:00", "target_date": "2026-08-14"},
                           d, cut)                                          # available after the cutoff
    assert not ar.keep_row("lessons", {"available_from": "2026-08-14T22:00:00+00:00", "target_date": "2026-08-17"},
                           d, cut)                                          # target after D
