"""Issue #36 item 4: scripts/adjustment_records.py lists the calls and ranges made while a wrong adjustments row
was active (made_at between its detected_at and its correction's), per correction, and nothing else."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_pipeline import MARKET, run, setup  # noqa: E402

WRONG_AT, FIX_AT = "2026-09-15T12:00:00+00:00", "2026-09-17T12:00:00+00:00"


def append(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.writelines(json.dumps(row) + "\n" for row in rows)


def call(ticker: str, as_of: str, made_at: str) -> dict:
    return {"id": f"{as_of}-{ticker}-1d", "made_at": made_at, "as_of_date": as_of, "ticker": ticker,
            "horizon_days": 1, "direction": "up", "confidence": 0.6, "rationale": "t", "evidence_ids": ["x"],
            "prompt_version": "test"}


def rng(ticker: str, as_of: str, made_at: str) -> dict:
    return {"id": f"{as_of}-{ticker}-r1d", "made_at": made_at, "as_of_date": as_of, "session_date": as_of,
            "target_date": as_of, "ticker": ticker, "horizon_days": 1, "base_close": 100.0, "center": 100.0,
            "sigma_h": 0.01, "lo50": 99.0, "hi50": 101.0, "lo80": 98.0, "hi80": 102.0}


def adjustment(row_id: str, factor: float, detected_at: str, **extra) -> dict:
    return {"id": row_id, "ticker": "AAPL", "ex_date": "2026-09-14", "factor": factor, "volume_factor": 1 / factor,
            "source": "yahoo_splits", "detected_at": detected_at, **extra}


def test_records_between_a_wrong_row_and_its_correction_are_listed(tmp_path):
    root, cfg = setup(tmp_path)
    out = run("adjustment_records.py", root, cfg)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"market": MARKET, "corrections": []}         # no adjustments at all
    append(root, "adjustments", "2026-09-14", [
        adjustment("AAPL-2026-09-14", 0.5, WRONG_AT),
        adjustment("AAPL-2026-09-14-fix1", 1.0, FIX_AT, supersedes="AAPL-2026-09-14", note="no split")])
    append(root, "predictions", "2026-09-15", [
        call("AAPL", "2026-09-14", "2026-09-15T11:00:00+00:00"),       # before the wrong row: not affected
        call("AAPL", "2026-09-15", "2026-09-15T12:00:00+00:00"),       # at the wrong row's detected_at: affected
        call("MSFT", "2026-09-15", "2026-09-15T13:00:00+00:00"),       # another stock: not affected
        call("AAPL", "2026-09-16", "2026-09-16T13:00:00+00:00"),       # affected, and already scored
        call("AAPL", "2026-09-17", FIX_AT)])                            # at the correction: not affected
    append(root, "outcomes", "2026-09-17", [{"prediction_id": "2026-09-16-AAPL-1d",
                                             "scored_at": "2026-09-17T22:00:00+00:00", "base_date": "2026-09-16",
                                             "base_close": 100.0, "target_date": "2026-09-17",
                                             "target_close": 101.0, "actual_return": 0.01, "hit": True}])
    append(root, "ranges", "2026-09-16", [rng("AAPL", "2026-09-16", "2026-09-16T13:00:00+00:00"),
                                          rng("AAPL", "2026-09-18", "2026-09-18T13:00:00+00:00")])
    out = run("adjustment_records.py", root, cfg)
    assert out.returncode == 0, out.stderr
    [fix] = json.loads(out.stdout)["corrections"]
    assert (fix["correction_id"], fix["wrong_id"], fix["ticker"], fix["wrong_factor"], fix["correction_factor"]) == \
        ("AAPL-2026-09-14-fix1", "AAPL-2026-09-14", "AAPL", 0.5, 1.0)
    assert [(r["kind"], r["id"], r["scored"]) for r in fix["records"]] == [
        ("prediction", "2026-09-15-AAPL-1d", False),
        ("prediction", "2026-09-16-AAPL-1d", True),
        ("range", "2026-09-16-AAPL-r1d", False)]
