"""B2 rule strategies and baselines (F2) on W1's example per-horizon scores and ranges (design/catalogue/
prediction.json: the reference strategy's probability, target and range per company and horizon stand in for B10's
model_scores and ranges rows), plus the news weights, blocks and abstentions of F2.6, and the registry."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.lab import registry  # noqa: E402
from marketbrief.lab.strategies import TickerInputs, company_rows, logit  # noqa: E402
from marketbrief.model.settings import load_model_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads((REPO / "design/catalogue/prediction.json").read_text())["records"]
NEWS_CFG = load_model_config()["news"]


def inputs_from_examples(ticker: str, **extra) -> TickerInputs:
    """W1's reference predictions of today (as of 2026-10-06) as HorizonScore / HorizonRange fixtures."""
    ref = {r["horizon_days"]: r for r in EXAMPLES if r["ticker"] == ticker and r["strategy_id"] == "rule.model_news.v1"
           and r["as_of_date"] == "2026-10-06"}
    one = ref[1]
    scores = {k: {"id": r["range_id"], "prob_model": r["prob_up"], "prob_up": r["prob_up"]} for k, r in ref.items()}
    ranges = {k: {"id": r["range_id"], "center": r["target_price"], "lo50": r["lo50"], "hi50": r["hi50"],
                  "lo80": r["lo80"], "hi80": r["hi80"]} for k, r in ref.items()}
    values = dict(market=one["market"], ticker=ticker, as_of_date="2026-10-06", session_date=one["session_date"],
                  exit_dates={k: r["exit_date"] for k, r in ref.items()}, made_at=one["made_at"],
                  base_close=one["base_close"], prev_close=None, regime=one["regime"], quality="OK",
                  days_to_earnings=30, amount=one["amount"], currency=one["currency"], scores=scores, ranges=ranges,
                  news=[])
    values.update(extra)
    return TickerInputs(**values)


def by_id(rows):
    return {r["id"]: r for r in rows}


def test_registry_horizons_and_hash():
    assert registry.horizons() == (1, 2, 3, 4, 5)
    assert len(registry.rule_and_baselines()) == 11
    spec = registry.strategies()[0]
    assert registry.config_hash(spec) == registry.config_hash(dict(reversed(list(spec.items()))))


def test_reference_reproduces_the_examples_and_every_horizon():
    preds, skipped = company_rows(registry.rule_and_baselines(), inputs_from_examples("NVDA", prev_close=238.9),
                                  NEWS_CFG)
    rows = by_id(preds)
    assert len(preds) == 10 * 5 and len(skipped) == 1                       # global: no cross-market score yet
    assert skipped[0]["strategy_id"] == "rule.model_news_global.v1" and skipped[0]["reason_code"] == "abstained"
    for k in range(1, 6):
        mine = rows[f"rule.model_news.v1:2026-10-06-NVDA-{k}d"]
        example = next(r for r in EXAMPLES if r["id"] == mine["id"])
        assert (mine["prob_up"], mine["target_price"], mine["lo80"], mine["hi80"], mine["exit_date"]) == (
            example["prob_up"], example["target_price"], example["lo80"], example["hi80"], example["exit_date"])
        assert mine["qualifies"] is (mine["prob_up"] >= 0.55)
        assert mine["evidence_ids"] == [f"model_scores:{mine['range_id']}", "features:2026-10-06-NVDA"]
    strict = rows["rule.model_news_strict.v1:2026-10-06-NVDA-1d"]
    assert strict["prob_up"] == 0.566 and strict["qualifies"] is False          # 60% bar
    assert rows["base.always_up.v1:2026-10-06-NVDA-3d"]["direction"] == "up"
    assert rows["base.momentum.v1:2026-10-06-NVDA-3d"]["direction"] == "up"     # 239.24 > 238.90
    assert rows["base.always_up.v1:2026-10-06-NVDA-3d"]["prob_up"] is None


def test_regime_filter_writes_but_does_not_trade():
    preds, _ = company_rows(registry.rule_and_baselines(), inputs_from_examples("RELIANCE"), NEWS_CFG)
    rows = by_id(preds)                                                     # India: EVENT_HEAVY
    calm = rows["rule.model_news_calm.v1:2026-10-06-RELIANCE-3d"]
    ref = rows["rule.model_news.v1:2026-10-06-RELIANCE-3d"]
    assert calm["prob_up"] == ref["prob_up"] and ref["qualifies"] is True and calm["qualifies"] is False
    assert rows["base.momentum.v1:2026-10-06-RELIANCE-1d"]["direction"] == "down"   # no previous close given


def test_news_weights_statuses_and_evidence():
    news = [{"id": "n-cor", "sentiment": 1.0, "relevance": 1.0, "materiality": "high", "event_type": "product",
             "status": "corroborated"},
            {"id": "n-single", "sentiment": 1.0, "relevance": 1.0, "materiality": "medium", "event_type": "product",
             "status": "single_source"},
            {"id": "n-rumour", "sentiment": 1.0, "relevance": 1.0, "materiality": "high", "event_type": "ma",
             "status": "rumour"}]
    preds, _ = company_rows(registry.rule_and_baselines(), inputs_from_examples("NVDA", news=news), NEWS_CFG)
    rows = by_id(preds)
    base = logit(0.566)
    # item weights: corroborated 1 x 1 x high 1.0 x 0.7 = 0.7; single-source medium 0.5 x 0.3 = 0.15; rumour 0
    expected = {"rule.model_news.v1": 0.85, "rule.model_news_half.v1": 0.425, "rule.model_news_double.v1": 1.7,
                "rule.model_news_confirmed.v1": 0.7, "rule.model_news_high.v1": 0.7, "base.model_only.v1": 0.0}
    for sid, score in expected.items():
        prob = 1 / (1 + math.exp(-(base + NEWS_CFG["coefficient"] * score)))
        assert rows[f"{sid}:2026-10-06-NVDA-1d"]["prob_up"] == round(prob, 4), sid
    assert rows["rule.model_news.v1:2026-10-06-NVDA-1d"]["evidence_ids"][-2:] == ["n-cor", "n-single"]
    assert "n-rumour" not in rows["rule.model_news_double.v1:2026-10-06-NVDA-1d"]["evidence_ids"]
    only_single, _ = company_rows(registry.rule_and_baselines(), inputs_from_examples("NVDA", news=news[1:2]),
                                  NEWS_CFG)
    assert all(not any(e.startswith("n-") for e in p["evidence_ids"]) for p in only_single)   # first not verified


def test_blocked_quality_and_earnings_abstain_for_every_strategy():
    for extra, code in (({"quality": "BLOCKED"}, "blocked_quality"), ({"days_to_earnings": 1}, "earnings_window")):
        preds, skipped = company_rows(registry.rule_and_baselines(), inputs_from_examples("NVDA", **extra), NEWS_CFG)
        assert preds == [] and len(skipped) == 11 and {s["reason_code"] for s in skipped} == {code}
        assert skipped[0]["id"] == "rule.model_news.v1:2026-10-06-NVDA" and skipped[0]["horizons"] == [1, 2, 3, 4, 5]
