"""Signal tiers, proof status and paper-follow of the paper portfolio (WS4; marketbrief/portfolio/signals.py,
proof.py, paper_follow.py) on a synthetic US root: strong tiers never without proof, emitted with it, the
open_to_close basis only, and no look-ahead.
Run: pytest -q tests/test_portfolio_signals.py"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_portfolio import D1, D2, D3, D4, ctx_for, make_root, write_jsonl  # noqa: E402
from marketbrief.portfolio import paper_follow, signals  # noqa: E402
from marketbrief.portfolio.constants import LABEL_PAPER_ONLY, MSG_NO_STRONG  # noqa: E402

SCORED_AT = "2026-10-07T06:00:00+00:00"    # before the US open of 2026-10-07 (13:30 UTC)
EARLY, LATE = "2026-10-05T06:00:00+00:00", "2026-10-05T14:00:00+00:00"   # before / after the 2026-10-05 open


@pytest.fixture
def root(tmp_path, monkeypatch):
    return make_root(tmp_path, monkeypatch)


def score(ticker: str, horizon: int, prob: float, as_of=D4, computed_at=SCORED_AT) -> dict:
    up = [{"feature": "ema_ratio", "points": 1.0, "text": f"{ticker} EMA ratio: +1.0 pts"}]
    down = [{"feature": "rsi_14", "points": -0.5, "text": f"{ticker} RSI high: -0.5 pts"}]
    return {"id": f"{as_of}-{ticker}-{horizon}d", "as_of_date": str(as_of), "ticker": ticker, "horizon_days": horizon,
            "label_convention": "open_to_close", "prob_up": prob, "prob_model": prob, "calibrated": True,
            "base_rate": 0.52, "news_score": 0.0, "news_logit": 0.0, "contributions": {"up": up, "down": down},
            "model_version": "logit-v1", "model_id": "m", "trained_until": "2026-10-01", "computed_at": computed_at}


def call(ticker: str, horizon: int, model_prob: float, adjustment: float, as_of=D4) -> dict:
    final = model_prob + adjustment
    return {"id": f"{as_of}-{ticker}-{horizon}d", "made_at": "2026-10-07T07:00:00+00:00", "as_of_date": str(as_of),
            "ticker": ticker, "horizon_days": horizon, "direction": "up" if final > 0.5 else "down",
            "confidence": round(max(final, 1 - final), 4), "rationale": "r", "evidence_ids": ["n1"],
            "prompt_version": "forecast-v11", "range_widen": 0.0, "model_prob": model_prob,
            "agent_adjustment": adjustment, "adjustment_reason": "confirmed news"}


def track_record(root, n: int, hits: int, basis: str = "open_to_close", tag: str = "a") -> None:
    """n scored 1-day calls at confidence 0.65 (band 0.6-0.7), the first `hits` of them hits."""
    preds, outs = [], []
    for i in range(n):
        pid = f"2026-01-{i:03d}-X-1d-{basis}-{tag}"
        preds.append({"id": pid, "made_at": "2026-09-01T00:00:00+00:00", "as_of_date": "2026-08-31", "ticker": "X",
                      "horizon_days": 1, "direction": "up", "confidence": 0.65})
        outs.append({"prediction_id": pid, "scored_at": "2026-10-06T00:00:00+00:00", "hit": i < hits,
                     "label_basis": basis})
    write_jsonl(root, "us", "predictions", D1, preds)
    write_jsonl(root, "us", "outcomes", D1, outs)


def review(root, skill: bool, computed_at: str = "2026-10-06T00:00:00+00:00") -> None:
    write_jsonl(root, "us", "reviews", D3, [{"id": f"2026-W{computed_at[8:10]}", "week": "2026-W40",
                                             "computed_at": computed_at, "model_skill": skill}])


def payload(market: str = "us") -> dict:
    ctx = ctx_for(market)
    return signals.cockpit_payload(ctx.con, ctx.clock, ctx.market, ctx.settings)


def tiers_by_id(out: dict) -> dict[str, str]:
    return {row["id"]: row["tier"] for row in out["tiers"]}


def strong_fixture(root) -> None:
    write_jsonl(root, "us", "model_scores", D4,
                [score("AAPL", 1, 0.62), score("JPM", 1, 0.40), score("AAPL", 5, 0.53)])
    write_jsonl(root, "us", "predictions", D4, [call("AAPL", 1, 0.62, 0.05), call("JPM", 1, 0.40, -0.05)])
    write_jsonl(root, "us", "ranges", D4, [{"id": "2026-10-06-AAPL-1d", "made_at": SCORED_AT,
                                            "target_date": "2026-10-07", "ticker": "AAPL", "horizon_days": 1,
                                            "base_close": 214.0, "lo50": 212.0, "hi50": 216.0, "lo80": 210.0,
                                            "hi80": 218.0}])


def test_pure_tier_rule():
    from marketbrief.portfolio.settings import load_portfolio_config
    settings = load_portfolio_config()
    assert signals.tier_for("up", 0.70, False, True, settings) == "Buy"
    assert signals.tier_for("up", 0.70, True, True, settings) == "Strong Buy"
    assert signals.tier_for("up", 0.70, True, False, settings) == "Buy"          # strong needs a forecaster call
    assert signals.tier_for("down", 0.66, True, True, settings) == "Strong Sell"
    assert signals.tier_for("down", 0.60, True, True, settings) == "Sell"        # below strong_min_confidence
    assert signals.tier_for("up", 0.54, True, True, settings) == "Hold/No call"
    assert signals.tier_for(None, 0.5, True, True, settings) == "Hold/No call"


def test_no_strong_without_proof(root):
    strong_fixture(root)
    track_record(root, 60, 55)                    # a strong open_to_close record ...
    review(root, skill=False)                     # ... but the review found no model skill
    out = payload()
    assert out["proof"]["status"] == "not_proven" and out["strong_count"] == 0 and out["headline"] == MSG_NO_STRONG
    assert tiers_by_id(out) == {"2026-10-06-AAPL-1d": "Buy", "2026-10-06-JPM-1d": "Sell",
                                "2026-10-06-AAPL-5d": "Hold/No call"}
    assert all(row["paper_only"] and row["label"] == LABEL_PAPER_ONLY for row in out["tiers"])
    assert [c["id"] for c in out["candidates"]] == ["2026-10-06-AAPL-1d", "2026-10-06-JPM-1d", "2026-10-06-AAPL-5d"]
    assert out["candidates"][1]["reasons"] == ["JPM RSI high: -0.5 pts"]        # drivers on the candidate's side
    aapl = next(row for row in out["tiers"] if row["id"] == "2026-10-06-AAPL-1d")
    assert aapl["final_prob"] == 0.67 and aapl["range"]["lo80"] == 210.0 and aapl["band"] == "0.6-0.7"


def test_close_to_close_record_never_proves(root):
    strong_fixture(root)
    track_record(root, 60, 60, basis="close_to_close")
    review(root, skill=True)
    out = payload()
    assert out["proof"]["status"] == "not_proven" and out["strong_count"] == 0


def test_too_few_calls_or_low_wilson_never_proves(root):
    strong_fixture(root)
    review(root, skill=True)
    track_record(root, 40, 40)                    # Wilson low 0.91 but fewer than min_count 50
    assert payload()["strong_count"] == 0
    track_record(root, 30, 0, tag="b")            # 70 calls, 40 hits: Wilson low below 0.55
    out = payload()
    cell = next(c for c in out["proof"]["cells"] if c["horizon_days"] == 1 and c["band"] == "0.6-0.7")
    assert cell["n"] == 70 and cell["hits"] == 40 and cell["wilson_low"] < 0.55 and out["strong_count"] == 0


def test_strong_emitted_when_proven(root):
    strong_fixture(root)
    review(root, skill=True)
    track_record(root, 60, 50)                    # 1d band 0.6-0.7: 50/60, Wilson low ~0.72
    out = payload()
    assert out["proof"]["status"] == "proven" and out["headline"] is None and out["candidates"] == []
    tiers = tiers_by_id(out)
    assert tiers["2026-10-06-AAPL-1d"] == "Strong Buy"             # final 0.67, proven cell, a call
    assert tiers["2026-10-06-JPM-1d"] == "Strong Sell"             # final 0.35: confidence 0.65, same proven cell
    row = next(r for r in out["tiers"] if r["id"] == "2026-10-06-AAPL-1d")
    assert row["paper_only"] is False and row["proven"] is True
    five = next(r for r in out["tiers"] if r["id"] == "2026-10-06-AAPL-5d")
    assert five["paper_only"] is True                              # the 5d cells have no record


def test_blocked_ticker_is_hold(root):
    strong_fixture(root)
    write_jsonl(root, "us", "features", D4, [{"id": "f", "as_of_date": "2026-10-06", "ticker": "AAPL",
                                              "computed_at": SCORED_AT, "quality": "OK", "days_to_earnings": 1}])
    out = payload()
    row = next(r for r in out["tiers"] if r["id"] == "2026-10-06-AAPL-1d")
    assert row["tier"] == "Hold/No call" and row["blocked"] == "earnings in 1 session(s)"
    assert "2026-10-06-AAPL-1d" not in [c["id"] for c in out["candidates"]]


def test_signals_no_look_ahead(root, monkeypatch):
    strong_fixture(root)
    track_record(root, 60, 50)
    review(root, skill=True, computed_at="2026-10-07T13:00:00+00:00")             # after the clock (12:00)
    write_jsonl(root, "us", "model_scores", D4, [score("AAPL", 1, 0.90, computed_at="2026-10-07T12:30:00+00:00")])
    out = payload()
    assert out["proof"]["status"] == "not_proven" and out["proof"]["review"] is None
    assert next(r for r in out["tiers"] if r["id"] == "2026-10-06-AAPL-1d")["model_prob"] == 0.62
    monkeypatch.setenv("MB_NOW", "2026-10-07T14:00:00+00:00")
    later = payload()
    assert later["proof"]["status"] == "proven"
    assert next(r for r in later["tiers"] if r["id"] == "2026-10-06-AAPL-1d")["model_prob"] == 0.9


def test_paper_follow_simulation(root):
    # as of D2 (2026-10-02): D = 2026-10-05; 1d exits at the close of D+1 = 2026-10-06
    write_jsonl(root, "us", "model_scores", D2, [score("AAPL", 1, 0.60, as_of=D2, computed_at=EARLY),
                                                 score("JPM", 1, 0.45, as_of=D2, computed_at=EARLY),
                                                 score("AAPL", 5, 0.70, as_of=D2, computed_at=LATE)])
    ctx = ctx_for()
    out = paper_follow.simulate(ctx.con, ctx.cfg, ctx.clock, ctx.market, ctx.settings, ctx.costs)
    assert out["label"].startswith("SIMULATED") and out["late_scores"] == 1      # the 5d score came after the open
    rows = {row["id"]: row for row in out["positions"]}
    aapl, jpm = rows["2026-10-02-AAPL-1d"], rows["2026-10-02-JPM-1d"]
    assert (aapl["entry_date"], aapl["exit_date"], aapl["status"]) == ("2026-10-05", "2026-10-06", "scored")
    assert aapl["ret_pct"] == pytest.approx(round((214 / 207 - 1) * 100, 4))
    cost = lambda price: 0.0000206 + 0.000195 / price            # noqa: E731  SEC fee + TAF on $10,000 at the open
    assert aapl["net_pct"] == pytest.approx(round((214 / 207 - 1 - cost(207)) * 100, 4))
    assert jpm["direction"] == "down"
    assert jpm["net_pct"] == pytest.approx(round((-(308 / 302 - 1) - cost(302)) * 100, 4))
    assert out["sides"]["up"]["scored"] == 1 and out["sides"]["down"]["hit_rate"] == 0.0


# ---------- the shapes of api/openapi.yaml (wave 0) ----------

CANDIDATE_REQUIRED = {"ticker", "h", "tier", "model_prob", "label"}


def test_api_signal_tiers_shape(root):
    from marketbrief.portfolio import api_shapes
    strong_fixture(root)
    ctx = ctx_for()
    unproven = api_shapes.signal_tiers(payload(), ctx.cfg)
    assert set(unproven) >= {"headline", "strong", "paper_candidates", "rule"} and unproven["strong"] == []
    first = unproven["paper_candidates"][0]
    assert CANDIDATE_REQUIRED <= set(first) and first["tier"] == "paper_up" and first["h"] == 1
    assert (first["entry"], first["exit"]) == ("2026-10-07", "2026-10-08")      # open of D, close of D+1
    assert first["prediction_id"] == "2026-10-06-AAPL-1d" and first["name"] == "Apple"
    review(root, skill=True)
    track_record(root, 60, 50)
    proven = api_shapes.signal_tiers(payload(), ctx.cfg)
    assert [(c["ticker"], c["tier"]) for c in proven["strong"]] == [("AAPL", "strong_buy"), ("JPM", "strong_sell")]
    assert proven["paper_candidates"] == []


@pytest.mark.usefixtures("root")
def test_api_paper_portfolio_shape():
    from marketbrief.portfolio import api_shapes, service
    ctx = ctx_for()
    service.add_trade(ctx, service.TradeInput("AAPL", "buy", 10, D1, "open", "slack"))
    out = api_shapes.paper_portfolio(ctx)
    assert set(out) >= {"market", "as_of", "label", "positions", "trades"} and out["label"] == LABEL_PAPER_ONLY
    lot = out["positions"][0]
    assert {"ticker", "quantity", "entry_date", "entry_price"} <= set(lot)
    assert (lot["entry_price"], lot["mark_close"], lot["unrealized_return"]) == (200.0, 214.0, 0.07)
    assert out["trades"][0]["source"] == "slack" and out["trades"][0]["recorded_at"] == "2026-10-07T12:00:00+00:00"
