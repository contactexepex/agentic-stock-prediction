"""The forecaster's anchor on the signal model (validate.py --stage forecast; marketbrief/model/forecast_rules.py)
and the agent-reasoning gate (scripts/agent_reasoning.py; marketbrief/model/reasoning.py), on test_validate's
synthetic US tree.
Run: pytest -q tests/test_model_gate.py"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.constants.model import KIND_AGENT_REASONING, KIND_MODEL_SCORES  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from marketbrief.model import reasoning  # noqa: E402
from marketbrief.model.forecast_rules import anchor_errors  # noqa: E402
import test_validate  # noqa: E402
from test_validate import CFG, GOOD_NEWS_ID, call, codes, forecast, write_jsonl  # noqa: E402

root = test_validate.root   # the synthetic US tree fixture, shared

SCORE_ID = "2026-10-05-AAPL-5d"


def score(prob: float, computed_at: str = "2026-10-06T11:30:00+00:00") -> dict:
    return {"id": SCORE_ID, "as_of_date": "2026-10-05", "ticker": "AAPL", "horizon_days": 5,
            "label_convention": "open_to_close", "prob_up": prob, "prob_model": prob, "calibrated": True,
            "base_rate": 0.52, "news_score": 0.0, "news_logit": 0.0, "contributions": {"up": [], "down": []},
            "model_version": "logit-v1", "model_id": "x", "trained_until": "2026-10-01", "computed_at": computed_at}


def anchored(**kw) -> dict:
    fields = {"model_prob": 0.55, "agent_adjustment": 0.05, "adjustment_reason": "confirmed order win",
              "confidence": 0.6, **kw}
    return call(**fields)


# ---------- the rule itself ----------

@pytest.mark.parametrize("rec,word", [
    ({"direction": "up", "confidence": 0.55}, "model_prob missing"),
    ({"model_prob": 0.50, "agent_adjustment": 0.05, "adjustment_reason": "r", "direction": "up",
      "confidence": 0.55}, "is not the stored model score"),
    ({"model_prob": 0.55, "direction": "up", "confidence": 0.55}, "agent_adjustment missing"),
    ({"model_prob": 0.55, "agent_adjustment": 0.15, "adjustment_reason": "r", "direction": "up",
      "confidence": 0.70}, "above 0.1"),
    ({"model_prob": 0.55, "agent_adjustment": 0.05, "direction": "up", "confidence": 0.60}, "adjustment_reason"),
    ({"model_prob": 0.55, "agent_adjustment": 0.05, "adjustment_reason": "r", "direction": "down",
      "confidence": 0.60}, "disagrees"),
    ({"model_prob": 0.55, "agent_adjustment": 0.05, "adjustment_reason": "r", "direction": "up",
      "confidence": 0.70}, "is not max(final"),
    ({"model_prob": 0.55, "agent_adjustment": -0.05, "adjustment_reason": "r", "direction": "up",
      "confidence": 0.5}, "abstain"),
])
def test_anchor_rule_failures(rec, word):
    assert any(word in e for e in anchor_errors(rec, 0.55)), anchor_errors(rec, 0.55)


@pytest.mark.parametrize("rec", [
    {"model_prob": 0.55, "agent_adjustment": 0.0, "direction": "up", "confidence": 0.55},
    {"model_prob": 0.55, "agent_adjustment": 0.10, "adjustment_reason": "r", "direction": "up", "confidence": 0.65},
    {"model_prob": 0.55, "agent_adjustment": -0.10, "adjustment_reason": "r", "direction": "down", "confidence": 0.55},
    {"model_prob": 0.55, "agent_adjustment": 0.003, "adjustment_reason": "r", "direction": "up", "confidence": 0.55},
])
def test_anchor_rule_passes(rec):
    assert anchor_errors(rec, 0.55) == []


def test_no_stored_score_means_no_model_prob():
    assert anchor_errors({"direction": "up", "confidence": 0.6}, None) == []
    assert "no model score" in anchor_errors({"model_prob": 0.5}, None)[0]


# ---------- in the forecast gate ----------

def test_gate_requires_the_anchor_when_a_score_exists(root):
    write_jsonl(root, KIND_MODEL_SCORES, date(2026, 10, 6), [score(0.55)])
    out = forecast(root, [anchored()])
    assert out["ok"], out["failures"]
    assert out["info"]["forecast"] == {"records": 1, "valid": 1, "refused_news_status": 0}
    failed = codes(forecast(root, [call()]))
    assert "model_prob missing" in failed["MODEL_ADJUSTMENT"]["detail"]
    failed = codes(forecast(root, [anchored(agent_adjustment=0.2, confidence=0.75)]))
    assert "above 0.1" in failed["MODEL_ADJUSTMENT"]["detail"]


def test_gate_uses_the_newest_score_computed_by_made_at(root):
    write_jsonl(root, KIND_MODEL_SCORES, date(2026, 10, 6),
                [score(0.55), score(0.40, computed_at="2026-10-06T11:50:00+00:00")])   # after made_at 11:45
    assert forecast(root, [anchored()])["ok"]


def test_gate_warns_without_a_score(root):
    out = forecast(root, [call()])
    assert out["ok"], out["failures"]
    assert "MODEL_SCORE_MISSING" in codes(out, "warnings")
    assert "no model score" in codes(forecast(root, [anchored()]))["MODEL_ADJUSTMENT"]["detail"]


# ---------- agent reasoning ----------

def debate(**kw) -> dict:
    rec = {"id": "2026-10-05-AAPL", "as_of_date": "2026-10-05", "ticker": "AAPL",
           "made_at": "2026-10-06T11:46:00+00:00", "bull_case": "Event coverage is positive.",
           "bear_case": "Valuation is stretched.", "verdict": "Small up call on confirmed news.",
           "decision_1d": "abstain", "decision_5d": "up", "evidence_ids": [GOOD_NEWS_ID],
           "prediction_ids": [SCORE_ID], "prompt_version": "forecast-v11"}
    rec.update(kw)
    return rec


def write_debate(root: Path, rows: list[dict]) -> Path:
    path = root / "work" / "reasoning.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def errors_of(root: Path, rows: list[dict]) -> list[str]:
    _, problems = reasoning.validate_file(CFG, write_debate(root, rows))
    return [e for p in problems for e in p["errors"]]


@pytest.mark.parametrize("change,word", [
    ({"bull_case": "word " * 81}, "bull_case must be text of 1-80 words"),
    ({"verdict": "word " * 61}, "verdict must be text of 1-60 words"),
    ({"decision_5d": "flat"}, "decision_5d must be one of"),
    ({"evidence_ids": ["ffffffffffffffff"]}, "evidence ids not stored"),
    ({"made_at": "2026-10-06T08:00:00+00:00"}, "published after made_at"),
    ({"id": "2026-10-05-AAPL-5d"}, "id must be"),
    ({"as_of_date": "2026-10-02", "id": "2026-10-02-AAPL"}, "latest feature date"),
    ({"decision_5d": "down"}, "no stored down call"),
    ({"decision_5d": "abstain"}, "abstain but"),
    ({"prediction_ids": ["2026-10-05-MSFT-5d"]}, "is not a stored call"),
    ({"written_at": "2026-10-06T12:00:00+00:00"}, "unknown field"),
])
def test_reasoning_gate_failures(root, change, word):
    write_jsonl(root, "predictions", date(2026, 10, 6), [call()])
    assert any(word in e for e in errors_of(root, [debate(**change)])), errors_of(root, [debate(**change)])


def test_reasoning_add_appends_schema_rows_once(root, monkeypatch, capsys):
    write_jsonl(root, "predictions", date(2026, 10, 6), [call()])
    assert errors_of(root, [debate()]) == []
    path = write_debate(root, [debate(), debate(ticker="BAC", id="2026-10-05-BAC", decision_5d="abstain",
                                               prediction_ids=[], evidence_ids=[])])
    monkeypatch.setattr(sys, "argv", ["agent_reasoning.py", "--market", "us", "add", str(path)])
    assert reasoning.main() == 0
    assert json.loads(capsys.readouterr().out)["added"] == 2
    stored = [json.loads(x) for f in (root / "data" / "us" / KIND_AGENT_REASONING).rglob("*.jsonl")
              for x in f.read_text().splitlines()]
    assert {r["id"] for r in stored} == {"2026-10-05-AAPL", "2026-10-05-BAC"}
    assert set(stored[0]) == set(SCHEMAS[KIND_AGENT_REASONING][1])
    assert any("already stored" in e for e in errors_of(root, [debate()]))


def test_reasoning_rerun_supersedes_the_stored_debate(root, monkeypatch, capsys):
    """Issue #50: a same-day rerun stores its own debate under the same id when it is made later and differs; the
    newest written_at is the one read (dashboard and warehouse order by written_at). An identical repeat or an
    earlier one is still refused, and the data stays append-only."""
    write_jsonl(root, "predictions", date(2026, 10, 6), [call()])
    path = write_debate(root, [debate()])
    monkeypatch.setattr(sys, "argv", ["agent_reasoning.py", "--market", "us", "add", str(path)])
    assert reasoning.main() == 0 and json.loads(capsys.readouterr().out)["added"] == 1
    rerun = debate(made_at="2026-10-06T11:55:00+00:00", verdict="Rerun: the collect gate passed this time.")
    assert errors_of(root, [rerun]) == []
    assert any("already stored" in e for e in errors_of(root, [debate(made_at="2026-10-06T11:55:00+00:00")]))
    assert any("must be made later" in e for e in errors_of(root, [{**rerun, "made_at": "2026-10-06T11:46:00+00:00"}]))
    monkeypatch.setenv("MB_NOW", "2026-10-06T12:30:00+00:00")
    monkeypatch.setattr(sys, "argv", ["agent_reasoning.py", "--market", "us", "add", str(write_debate(root, [rerun]))])
    assert reasoning.main() == 0 and json.loads(capsys.readouterr().out)["added"] == 1
    stored = [json.loads(x) for f in (root / "data" / "us" / KIND_AGENT_REASONING).rglob("*.jsonl")
              for x in f.read_text().splitlines()]
    assert [r["verdict"] for r in stored] == [debate()["verdict"], rerun["verdict"]]       # both kept
    newest = connect("us").execute("SELECT DISTINCT ON (ticker) verdict FROM agent_reasoning WHERE as_of_date = "
                                   "'2026-10-05' ORDER BY ticker, written_at DESC, id").fetchone()[0]
    assert newest == rerun["verdict"]
