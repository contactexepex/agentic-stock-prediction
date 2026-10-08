"""The AI traders' gate (B3; docs/SPEC.md F4.2, F2.6): W1's example predictions pass, and each rule refuses: invented
ids, wrong numbers, look-ahead, a missed model anchor, a late trader, blind inputs, BLOCKED and earnings, narrowed
ranges, the track-record band, news verification, duplicates. Offline; inputs are fixtures (traders_fixtures.py)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from traders_fixtures import AS_OF, MADE_AT, NEWS_ID, PROMPTS, agent_record, inputs, published_range, score

from marketbrief.core.market_config import load_market
from marketbrief.traders import constants as c
from marketbrief.traders.gate import check_record
from marketbrief.traders.records import widened
from marketbrief.traders.registry import trader
from marketbrief.traders.sessions import deadline, entry_session, exit_session

NEWS, PATTERN, COMBINED, OPUS = PROMPTS


def codes(rec, strategy_id=NEWS, **changes) -> list[str]:
    verdict = check_record(rec, trader(strategy_id), inputs(**changes), set())
    return sorted({code for code, _ in verdict.errors})


@pytest.mark.parametrize("strategy_id", list(PROMPTS))
@pytest.mark.parametrize("horizon", [1, 3, 5])
def test_w1_examples_pass_and_rows_are_derived_from_stored_data(strategy_id, horizon):
    one = trader(strategy_id)
    verdict = check_record(agent_record(strategy_id, horizon), one, inputs(), set())
    assert verdict.errors == [] and verdict.warnings == []
    row = verdict.row
    assert row["id"] == f"{strategy_id}:{AS_OF}-NVDA-{horizon}d"
    assert row["session_date"] == "2026-10-07"
    assert row["exit_date"] == {1: "2026-10-08", 3: "2026-10-12", 5: "2026-10-14"}[horizon]
    assert row["base_close"] == published_range(horizon)["base_close"]
    assert row["qualifies"] is (row["direction"] == "up" and row["prob_up"] >= 0.55)
    assert row["confidence"] == round(max(row["prob_up"], 1 - row["prob_up"]), 4)
    assert row["config_hash"].startswith("sha256:") and len(row["config_hash"]) == 23
    assert row["amount"] == 1000.0 and row["currency"] == "USD" and row["family"] == "ai"
    if one.sees_model_score:
        assert row["model_prob"] == score(horizon)["prob_up"] and row["model_score_id"] == f"{AS_OF}-NVDA-{horizon}d"
    else:
        assert row["model_prob"] is None and row["model_score_id"] is None


def test_sessions_follow_decision_37():
    us, india = load_market("us"), load_market("india")
    assert exit_session(us, date(2026, 10, 9), 1) == date(2026, 10, 12)          # Friday entry, N+1 = Monday
    assert entry_session(us, date(2026, 10, 9)) == date(2026, 10, 12)            # as of Friday -> D Monday
    assert exit_session(india, date(2026, 9, 30), 2) == date(2026, 10, 5)        # 2 Oct 2026 is an NSE holiday
    assert deadline(us, date(2026, 10, 7)) == datetime(2026, 10, 7, 13, 15, tzinfo=timezone.utc)


def test_invented_evidence_id_is_refused():
    assert c.CODE_EVIDENCE in codes(agent_record(NEWS, evidence_ids=["0000invented0000"]))
    assert c.CODE_EVIDENCE in codes(agent_record(NEWS, evidence_ids=[NEWS_ID, "a", "b", "d"]))
    assert c.CODE_EVIDENCE in codes(agent_record(PATTERN, evidence_ids=["features:2026-10-05-NVDA"]), PATTERN)
    assert c.CODE_EVIDENCE in codes(agent_record(PATTERN, evidence_ids=["features:2026-10-06-AAPL"]), PATTERN)


def test_wrong_numbers_are_refused():
    assert c.CODE_NUMBERS in codes(agent_record(NEWS, base_close=240.0))
    assert c.CODE_NUMBERS in codes(agent_record(NEWS, exit_date="2026-10-09"))
    assert c.CODE_NUMBERS in codes(agent_record(NEWS, confidence=0.60))
    assert c.CODE_NUMBERS in codes(agent_record(NEWS, id="ai.news_results.sonnet.v1:2026-10-05-NVDA-1d"))
    assert c.CODE_TARGET in codes(agent_record(NEWS, target_price=300.0))       # outside the 80% range
    assert c.CODE_TARGET in codes(agent_record(NEWS, target_price=238.0))       # up call below C = 239.24
    assert c.CODE_PROBABILITY in codes(agent_record(NEWS, direction="down"))    # prob_up 0.576 is up
    assert c.CODE_PROBABILITY in codes(agent_record(NEWS, prob_up=0.95, target_price=241.0))
    assert c.CODE_PROBABILITY in codes(agent_record(NEWS, prob_up=0.5))


def test_look_ahead_is_refused():
    assert c.CODE_LOOKAHEAD in codes(agent_record(NEWS, evidence_ids=["late-news"]))
    late_range = {**published_range(1), "made_at": "2026-10-07T11:46:00Z"}
    ranges = inputs().ranges | {f"{AS_OF}-NVDA-1d": late_range}
    assert c.CODE_LOOKAHEAD in codes(agent_record(NEWS), ranges=ranges)
    late_score = {**score(1), "computed_at": "2026-10-07T11:46:00Z"}
    scores = inputs().scores | {f"{AS_OF}-NVDA-1d": late_score}
    assert c.CODE_LOOKAHEAD in codes(agent_record(COMBINED), COMBINED, scores=scores)
    assert c.CODE_TIME in codes(agent_record(NEWS, made_at="2026-10-07T12:30:00Z"))   # after the gate's clock


def test_missed_anchor_is_refused_for_combined_traders_only():
    stored = score(1)["prob_up"]
    for strategy_id in (COMBINED, OPUS):
        assert c.CODE_ANCHOR in codes(agent_record(strategy_id, model_prob=round(stored + 0.02, 4)), strategy_id)
        no_anchor = {k: v for k, v in agent_record(strategy_id).items() if k not in c.ANCHOR_FIELDS}
        assert c.CODE_ANCHOR in codes(no_anchor, strategy_id)
        assert c.CODE_ANCHOR in codes(agent_record(strategy_id, agent_adjustment=0.15,
                                                   prob_up=round(stored + 0.15, 4)), strategy_id)
        assert c.CODE_ANCHOR in codes(agent_record(strategy_id, prob_up=round(stored + 0.05, 4)), strategy_id)
        assert c.CODE_ANCHOR in codes(agent_record(strategy_id, adjustment_reason=None), strategy_id)
        model_only = agent_record(strategy_id, evidence_ids=[f"model_scores:{AS_OF}-NVDA-1d"])
        assert c.CODE_ANCHOR in codes(model_only, strategy_id)          # an adjustment needs a news id
    # no stored score: the anchor fields must stay out (warning only when they do)
    verdict = check_record({k: v for k, v in agent_record(COMBINED).items() if k not in c.ANCHOR_FIELDS},
                           trader(COMBINED), inputs(scores={}), set())
    assert verdict.errors == [] and [code for code, _ in verdict.warnings] == ["MODEL_SCORE_MISSING"]
    assert c.CODE_ANCHOR in codes(agent_record(COMBINED), COMBINED, scores={})


def test_blind_traders_cannot_see_the_score_or_other_inputs():
    assert c.CODE_BLIND in codes(agent_record(NEWS, model_prob=0.566, agent_adjustment=0.01, adjustment_reason="x"))
    assert c.CODE_BLIND in codes(agent_record(NEWS, evidence_ids=[NEWS_ID, f"model_scores:{AS_OF}-NVDA-1d"]))
    assert c.CODE_BLIND in codes(agent_record(NEWS, evidence_ids=[NEWS_ID, f"features:{AS_OF}-NVDA"]))
    assert c.CODE_BLIND in codes(agent_record(PATTERN, evidence_ids=[NEWS_ID]), PATTERN)
    assert c.CODE_BLIND in codes(agent_record(PATTERN, evidence_ids=[f"model_scores:{AS_OF}-NVDA-1d"]), PATTERN)


def test_late_trader_is_refused():
    assert c.CODE_TIME in codes(agent_record(NEWS, made_at="2026-10-07T13:20:00Z"),
                                now=datetime(2026, 10, 7, 13, 21, tzinfo=timezone.utc))
    assert c.CODE_TIME in codes(agent_record(NEWS, made_at="2026-10-07 11:45"))      # not ISO UTC


def test_blocked_earnings_and_regime_rules():
    feats = {"as_of_date": AS_OF, "quality": "BLOCKED", "days_to_earnings": 30}
    assert codes(agent_record(NEWS), features={"NVDA": feats}) == [c.CODE_BLOCKED]
    assert codes(agent_record(NEWS), features={"NVDA": {**feats, "quality": "OK", "days_to_earnings": 1}}) == \
        [c.CODE_EARNINGS]
    assert codes(agent_record(NEWS), regimes={}) == [c.CODE_BLOCKED]
    unstable = {AS_OF: ("UNSTABLE", None)}
    assert c.CODE_PROBABILITY in codes(agent_record(NEWS, prob_up=0.70, target_price=241.0), regimes=unstable)
    assert codes(agent_record(NEWS, prob_up=0.64), regimes=unstable) == []
    assert codes(agent_record(NEWS, ticker="AAPL")) == [c.CODE_TICKER]


def test_ranges_may_only_be_widened():
    rng = published_range(1)
    assert c.CODE_RANGE in codes(agent_record(NEWS, lo80=rng["lo80"] + 1.0))
    assert c.CODE_RANGE in codes(agent_record(NEWS, hi50=rng["hi50"] - 1.0))
    assert c.CODE_RANGE in codes(agent_record(NEWS, range_widen=-0.1))
    assert c.CODE_RANGE in codes(agent_record(NEWS, range_widen=0.6))
    wide = widened(rng, 0.2)
    assert wide["lo80"] < rng["lo80"] < rng["hi80"] < wide["hi80"]
    assert codes(agent_record(NEWS, range_widen=0.2, lo80=wide["lo80"], hi80=wide["hi80"])) == []
    assert c.CODE_NUMBERS in codes(agent_record(NEWS, range_widen=0.2, lo80=rng["lo80"] - 0.5))   # wider, not equal
    assert c.CODE_RANGE in codes(agent_record(NEWS), ranges={})                                    # no range


def test_track_record_band_closes_a_confidence():
    closed = {NEWS: {"0.50-0.60": {"n": 25, "hits": 11, "hit_rate": 0.44, "low": 0.5, "high": 0.6}}}
    assert c.CODE_TRACK in codes(agent_record(NEWS), track=closed)
    few = {NEWS: {"0.50-0.60": {"n": 19, "hits": 5, "hit_rate": 0.2632, "low": 0.5, "high": 0.6}}}
    assert codes(agent_record(NEWS), track=few) == []
    assert codes(agent_record(NEWS, prob_up=0.62, target_price=240.0), track=closed) == []    # another band


def test_news_verification_rules():
    assert "NEWS_STATUS_MAIN" in codes(agent_record(NEWS, evidence_ids=["rumour-news", NEWS_ID]))
    assert "NEWS_STATUS_BLOCKED" in codes(agent_record(NEWS, evidence_ids=[NEWS_ID, "rumour-news"]))
    assert "NEWS_STATUS_CONFIDENCE" in codes(agent_record(NEWS, evidence_ids=[NEWS_ID, "single-news"],
                                                          prob_up=0.88, target_price=241.0))
    assert codes(agent_record(NEWS, evidence_ids=[NEWS_ID, "single-news"], prob_up=0.85, target_price=241.0)) == []
    from traders_fixtures import Statuses
    verdict = check_record(agent_record(NEWS), trader(NEWS), inputs(statuses=Statuses(active=False)), set())
    assert verdict.errors == [] and [code for code, _ in verdict.warnings] == ["NEWS_STATUS_MISSING"]


def test_schema_strategy_and_duplicates():
    assert c.CODE_SCHEMA in codes({**agent_record(NEWS), "lo95": 1.0})
    assert c.CODE_SCHEMA in codes({k: v for k, v in agent_record(NEWS).items() if k != "reason"})
    assert c.CODE_STRATEGY in codes(agent_record(NEWS, prompt_version="trader-v1"))
    assert c.CODE_STRATEGY in codes(agent_record(NEWS, horizon_days=2))
    assert c.CODE_STRATEGY in codes({**agent_record(NEWS), "strategy_id": PATTERN})
    assert c.CODE_REASON in codes(agent_record(NEWS, reason="word " * 61))
    pid = f"{NEWS}:{AS_OF}-NVDA-1d"
    rerun = check_record(agent_record(NEWS), trader(NEWS), inputs(stored_predictions={pid}), set())
    assert rerun.row is None and rerun.errors == [] and [code for code, _ in rerun.warnings] == [c.CODE_STORED]
    seen: set[str] = set()
    one = trader(NEWS)
    assert check_record(agent_record(NEWS), one, inputs(), seen).errors == []
    assert [code for code, _ in check_record(agent_record(NEWS), one, inputs(), seen).errors] == [c.CODE_DUPLICATE]
    assert MADE_AT.endswith("Z")


def test_anchor_fields_without_a_score_and_repeated_evidence_are_refused():
    rec = {k: v for k, v in agent_record(COMBINED).items() if k != "model_prob"}
    assert c.CODE_ANCHOR in codes(rec, COMBINED, scores={})
    assert c.CODE_EVIDENCE in codes(agent_record(NEWS, evidence_ids=[NEWS_ID, NEWS_ID]))


def test_naive_score_time_is_read_as_utc():
    late = {**score(1), "computed_at": "2026-10-07 11:46:00"}
    assert c.CODE_LOOKAHEAD in codes(agent_record(COMBINED), COMBINED, scores=inputs().scores | {late["id"]: late})


def test_ranges_and_scores_are_read_as_of_made_at():
    """#86: with the as-of readers, a rescore after made_at is not used (no false LOOK_AHEAD), and a range published
    after made_at does not exist yet."""
    early, late = score(1), {**score(1), "prob_up": 0.70, "computed_at": "2026-10-07T11:48:00Z"}

    def scores_at(when):
        return {early["id"]: late if when >= datetime(2026, 10, 7, 11, 48, tzinfo=timezone.utc) else early}

    gi = inputs(scores_at=scores_at)
    verdict = check_record(agent_record(COMBINED), trader(COMBINED), gi, set())
    assert verdict.errors == [] and verdict.row["model_prob"] == early["prob_up"]
    assert codes(agent_record(NEWS), ranges_at=lambda _when: {}) == [c.CODE_RANGE]


def test_cited_inputs_must_be_computed_by_made_at():
    """#86: a features: or regime: id computed after made_at is look-ahead."""
    feats = {"NVDA": {"as_of_date": AS_OF, "quality": "OK", "days_to_earnings": 30,
                      "computed_at": datetime(2026, 10, 7, 11, 46, tzinfo=timezone.utc)}}
    pattern = agent_record(PATTERN, evidence_ids=[f"features:{AS_OF}-NVDA"])
    assert c.CODE_LOOKAHEAD in codes(pattern, PATTERN, features=feats)
    late_regime = {AS_OF: ("TRENDING", datetime(2026, 10, 7, 11, 47, tzinfo=timezone.utc))}
    assert c.CODE_LOOKAHEAD in codes(agent_record(PATTERN, evidence_ids=[f"regime:{AS_OF}"]), PATTERN,
                                     regimes=late_regime)


@pytest.mark.parametrize("strategy_id", list(PROMPTS))
@pytest.mark.parametrize("horizon", [1, 3, 5])
def test_w1_reliance_examples_pass_in_india(strategy_id, horizon):
    """#88: the India (RELIANCE, INR) AI examples of design/catalogue pass too; D = 2026-10-07, NSE open 03:45 UTC."""
    from traders_fixtures import agent_record_for, inputs_for
    gi = inputs_for("india", "RELIANCE", datetime(2026, 10, 7, 2, 15, tzinfo=timezone.utc))
    verdict = check_record(agent_record_for(strategy_id, "RELIANCE", horizon), trader(strategy_id), gi, set())
    assert verdict.errors == [] and verdict.row["currency"] == "INR" and verdict.row["amount"] == 100000.0
    assert verdict.row["exit_date"] == {1: "2026-10-08", 3: "2026-10-12", 5: "2026-10-14"}[horizon]
