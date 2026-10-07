"""B2 head-to-head picks (F1.7, decisions 41-42) with the two corrections of docs/ws/b2.md: the expected gain from
the range's conditional move and shortfall, ranked per session held, and strategies without a record ranked last.
Hand-checked numbers; ties and no_candidate included."""
from __future__ import annotations

import inspect
import math
from pathlib import Path

import pytest
from lab_fixtures import US_RATES

from marketbrief.contracts import protocol as contract
from marketbrief.lab import costs as lab_costs
from marketbrief.lab import pick_study, picks
from marketbrief.lab import protocol as built
from marketbrief.lab.constants import Z80

REPO = Path(__file__).resolve().parents[1]
CONTEXT = {"market": "us", "rate": US_RATES, "eurusd": 1.10, "made_at": "2026-10-02T11:45:00+00:00",
           "as_of_date": "2026-10-01", "session_date": "2026-10-02", "base_close": 100.0, "amount": 1000.0,
           "currency": "USD", "method_version": "lab-v1"}


def pred(sid: str, family: str, k: int, prob: float, sigma: float = 2.0, **extra) -> dict:
    """A qualifying prediction at C = 100 with target 100 and an 80% band of +-Z80 x sigma."""
    row = {"id": f"{sid}:2026-10-01-AAPL-{k}d", "strategy_id": sid, "family": family, "ticker": "AAPL",
           "horizon_days": k, "prob_up": prob, "base_close": 100.0, "target_price": 100.0,
           "lo80": 100.0 - Z80 * sigma, "hi80": 100.0 + Z80 * sigma, "amount": 1000.0, "qualifies": True}
    row.update(extra)
    return row


def trade(sid: str, ticker: str, net: float) -> dict:
    return {"strategy_id": sid, "ticker": ticker, "view": "accuracy", "status": "settled", "net_pnl": net}


def test_conditional_move_and_loss_hand_checked():
    # X ~ N(100, 2): E[X - C | X > C] = sigma x phi(0) / 0.5 = 2 x 0.398942 / 0.5 = 1.595769 (% of C = 100)
    move, loss = picks.conditional_move_loss(100.0, 100.0, 100.0 - Z80 * 2, 100.0 + Z80 * 2)
    assert move == pytest.approx(1.595769, abs=1e-6) and loss == pytest.approx(1.595769, abs=1e-6)
    move, loss = picks.conditional_move_loss(100.0, 101.0, 101.0, 101.0)     # no spread: the plain gap
    assert (move, loss) == pytest.approx((1.0, 0.0))


def test_candidate_hand_checked():
    # costs at C: 10 shares, EUR 0.99 x 1.10 x 2 = 2.178 -> 2.18, SEC 0.0000206 x 1000 = 0.02 -> 2.20 = 0.22 %
    # expected gain = 0.6 x 1.595769 - 0.4 x 1.595769 - 0.22 = 0.099154; per session (N+2) 0.049577
    out = picks.candidate(pred("rule.a.v1", "rule", 2, 0.6), "us", US_RATES, 1.10)
    assert out == {"horizon_days": 2, "prediction_id": "rule.a.v1:2026-10-01-AAPL-2d", "prob_up": 0.6,
                   "move_pct": 1.5958, "loss_pct": 1.5958, "costs_pct": 0.22, "expected_gain_pct": 0.0992,
                   "gain_per_session_pct": 0.0496}


def test_pick_rules_and_ties():
    cands = [{"horizon_days": 1, "prob_up": 0.6, "expected_gain_pct": 0.2, "gain_per_session_pct": 0.2},
             {"horizon_days": 3, "prob_up": 0.6, "expected_gain_pct": 0.6, "gain_per_session_pct": 0.2},
             {"horizon_days": 5, "prob_up": 0.58, "expected_gain_pct": 0.9, "gain_per_session_pct": 0.18}]
    assert picks.pick(cands, "highest_probability")["horizon_days"] == 1        # tie 0.6: the shorter
    assert picks.pick(cands, "best_expected_gain")["horizon_days"] == 1         # tie 0.2 per session: the shorter
    assert picks.pick([{k: v for k, v in c.items() if k != "gain_per_session_pct"} for c in cands],
                      "best_expected_gain")["horizon_days"] == 1                # contract Candidates: computed
    assert picks.pick([], "best_expected_gain") is None


def test_longer_horizon_can_win_per_session():
    # p rises with the horizon: N+3 at 0.70 with sigma 2 x sqrt(3) beats N+1 at 0.56 per session
    rows = [pred("rule.a.v1", "rule", 1, 0.56), pred("rule.a.v1", "rule", 3, 0.70, sigma=2 * math.sqrt(3))]
    cands = [picks.candidate(p, "us", US_RATES, 1.10) for p in rows]
    assert picks.pick(cands, "best_expected_gain")["horizon_days"] == 3


def test_ranking_no_record_ranks_last_and_per_company_first():
    ids = ["rule.a.v1", "rule.b.v1", "rule.c.v1", "rule.d.v1"]
    trades = ([trade("rule.a.v1", "AAPL", -5.0)] * 20 + [trade("rule.b.v1", "JPM", 100.0)] * 5
              + [trade("rule.d.v1", "JPM", -50.0)] * 3)
    rank = picks.ranking(ids, "AAPL", trades)
    assert [(r["strategy_id"], r["basis"], r["settled_trades"], r["net_pnl"]) for r in rank] == [
        ("rule.a.v1", "per_company", 20, -100.0), ("rule.b.v1", "all_companies", 5, 500.0),
        ("rule.d.v1", "all_companies", 3, -150.0), ("rule.c.v1", "all_companies", 0, 0.0)]


def test_pick_rows_strongest_both_rules_and_no_candidate():
    preds = [pred("rule.a.v1", "rule", 1, 0.62), pred("rule.a.v1", "rule", 3, 0.60, sigma=2 * math.sqrt(3)),
             pred("rule.b.v1", "rule", 2, 0.70), pred("ai.x.v1", "ai", 1, 0.5, qualifies=False)]
    trades = [trade("rule.b.v1", "JPM", 10.0)]            # b has a record, a has none -> b is strongest
    rule_rows = picks.pick_rows("AAPL", "rule", {**CONTEXT, "family_ids": ["rule.a.v1", "rule.b.v1"]}, preds, trades)
    assert [(r["pick_rule"], r["status"], r["strategy_id"], r["horizon_days"]) for r in rule_rows] == [
        ("best_expected_gain", "picked", "rule.b.v1", 2), ("highest_probability", "picked", "rule.b.v1", 2)]
    assert rule_rows[0]["id"] == "h2h:2026-10-01-AAPL-rule-best_expected_gain" and len(rule_rows[0]["candidates"]) == 1
    ai_rows = picks.pick_rows("AAPL", "ai", {**CONTEXT, "family_ids": ["ai.x.v1"]}, preds, trades)
    assert [(r["status"], r["strategy_id"], r["horizon_days"]) for r in ai_rows] == [("no_candidate", None, None)] * 2
    assert ai_rows[0]["ranking"][0]["strategy_id"] == "ai.x.v1"


def test_protocol_matches_the_contract_signatures():
    for name in ("entry_session", "exit_session", "is_locked", "qualifies", "quantity", "round_trip_costs", "settle",
                 "strongest", "pick"):
        assert list(inspect.signature(getattr(built, name)).parameters) == list(
            inspect.signature(getattr(contract, name)).parameters), name


def test_pick_study_on_the_w1_examples():
    rates = {"india": lab_costs.rates("india"), "us": lab_costs.rates("us")}
    out = pick_study.example_spread(REPO / "design/catalogue/prediction.json", rates, 1.17)
    assert out["groups"] == 21 and out["draft"] == {1: 21} and out["draft_best_positive"] == 0
    assert len(out["corrected"]) > 1                                    # the corrected rule picks several horizons
