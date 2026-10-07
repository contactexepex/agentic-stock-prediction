"""B2 scoreboard (F7) with the luck test, the paired comparisons, the heatmap data (F2.8), and the news-impact study
(F3) with a planted effect recovered. Hand-checked numbers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from lab_fixtures import US_RATES

from marketbrief.core import calendar
from marketbrief.core.market_config import load_market
from marketbrief.lab import compare, heatmaps, luck, news_impact, scoreboard
from marketbrief.lab.market_data import MarketData


def trade(n: int, net: float, **extra) -> dict:
    """A settled accuracy trade of rule.a.v1 on AAPL N+1 exiting on day n (amount 1000)."""
    row = {"id": f"acc:t{n}@1", "trade_id": f"acc:rule.a.v1:2026-10-{n:02d}-AAPL-1d", "settled_at": f"2026-11-{n:02d}",
           "prediction_id": f"rule.a.v1:2026-10-{n:02d}-AAPL-1d", "strategy_id": "rule.a.v1", "family": "rule",
           "market": "us", "view": "accuracy", "pick_rule": None, "ticker": "AAPL", "horizon_days": 1,
           "status": "settled", "entry_date": f"2026-10-{n:02d}", "exit_date_actual": f"2026-10-{n + 1:02d}",
           "net_pnl": net, "return_pct": net / 10, "target_reached": n % 2 == 0,
           "target_reached_session": 2 if n % 2 == 0 else None, "target_error_pct": 1.0, "range_hit": True,
           "regime": "TRENDING", "reason_code": "market_up"}
    row.update(extra)
    return row


def test_metrics_hand_checked():
    nets = [10.0, -5.0, -6.0, 20.0, -3.0]                 # cumulative 10, 5, -1, 19, 16: peak 10 -> -1 = -11
    rows = scoreboard.scoreboard([trade(i + 1, net) for i, net in enumerate(nets)])
    row = next(r for r in rows if r["scope"] == "strategy" and r["horizon_days"] == "all")
    assert (row["trades"], row["net_pnl"], row["mean_return_pct"], row["win_rate"]) == (5, 16.0, 0.32, 0.4)
    assert (row["worst_losing_streak"], row["max_drawdown"]) == (2, -11.0)
    assert (row["target_reached_rate"], row["median_reached_session"], row["range_hit_rate"]) == (0.4, 2, 1.0)
    assert row["sample_badge"] == "too_few_to_rank" and row["go_live"]["trades_needed"] == 295
    assert row["go_live"]["proven"] is False and row["go_live"]["beats_best_baseline"] is None
    scopes = {(r["scope"], r["horizon_days"]) for r in rows}
    assert scopes == {("strategy", "all"), ("strategy", 1), ("strategy_company", "all"), ("strategy_company", 1),
                      ("strategy_regime", "all")}


def test_newest_settlement_wins():
    old, new = trade(1, -5.0), trade(1, 7.0, id="acc:t1@2", settled_at="2026-11-02")
    rows = scoreboard.scoreboard([old, new])
    assert next(r for r in rows if r["scope"] == "strategy")["net_pnl"] == 7.0


def test_luck_test_bootstrap_and_correction():
    constant = luck.luck_test([1.0] * 30, "k", 4)
    assert (constant["low_pct"], constant["high_pct"], constant["excludes_zero"], constant["corrected"]) == (
        1.0, 1.0, True, True)
    mixed = [0.5, -0.2, 0.4, 0.1, 0.3, -0.1, 0.6, 0.2] * 5
    one, many = luck.luck_test(mixed, "k", 1), luck.luck_test(mixed, "k", 15)
    assert one == luck.luck_test(mixed, "k", 1)                                  # deterministic
    assert many["corrected_low_pct"] < one["corrected_low_pct"] == one["low_pct"]   # wider after correction
    assert luck.luck_test([2.0], "k", 3)["corrected"] is False                   # one trade: no interval


def test_go_live_beats_baseline_and_regimes():
    rows = [trade(i, 5.0, regime="UNSTABLE" if i % 2 else "TRENDING") for i in range(1, 25)]
    rows += [trade(i, 1.0, strategy_id="base.always_up.v1", family="baseline",
                   trade_id=f"acc:base:{i}", id=f"acc:b{i}@1") for i in range(1, 25)]
    out = {(r["scope"], r["strategy_id"], r["horizon_days"]): r for r in scoreboard.scoreboard(rows)}
    mine = out[("strategy", "rule.a.v1", "all")]
    assert mine["luck_test"]["m"] == 2 and mine["go_live"]["best_baseline_net_pnl"] == 24.0
    assert mine["go_live"]["beats_best_baseline"] is True and mine["go_live"]["holds_in_calm_and_volatile"] is True
    assert mine["go_live"]["proven"] is False                                     # 24 trades, under a month


def test_comparisons_pairs():
    rule = trade(1, 10.0, view="head_to_head", pick_rule="highest_probability", trade_id="h2h:r")
    ai = trade(1, 4.0, view="head_to_head", pick_rule="highest_probability", family="ai", strategy_id="ai.x.v1",
               trade_id="h2h:a", id="h2h:a@1")
    out = compare.comparisons([rule, ai], [])
    pair = next(c for c in out["head_to_head"] if c["comparison"] == "rule_vs_ai:highest_probability")
    assert (pair["pairs"], pair["net_pnl_a"], pair["net_pnl_b"], pair["wins_a"], pair["mean_diff_pct"]) == (
        1, 10.0, 4.0, 1, 0.6)
    spec = [{"id": "rule.b.v1", "compared_to": "rule.a.v1", "differs_in": "threshold"}]
    other = trade(1, 2.0, strategy_id="rule.b.v1", trade_id="acc:b", id="acc:b@1",
                  prediction_id="rule.b.v1:2026-10-01-AAPL-1d")
    versus = compare.comparisons([trade(1, 10.0), other], spec)["versus_compared_to"][0]
    assert (versus["pairs"], versus["net_pnl_a"], versus["net_pnl_b"], versus["differs_in"]) == (1, 2.0, 10.0,
                                                                                                 "threshold")


def test_heatmap_cells_and_lines():
    data = heatmaps.heatmap_data([trade(5, 10.0), trade(6, -4.0, reason_code="sector_drag")])
    week = next(c for c in data["cells"] if c["dimension"] == "horizon" and c["week"] == "all")
    assert (week["trades"], week["wins"], week["win_rate"], week["net_pnl"]) == (2, 1, 0.5, 6.0)
    codes = {c["column"] for c in data["cells"] if c["dimension"] == "reason_code"}
    assert codes == {"market_up", "sector_drag"}
    assert [line["cumulative_net_pnl"] for line in data["lines"]] == [10.0, 6.0]


def planted_market() -> tuple[MarketData, list[dict]]:
    """US sessions from 2026-01-05: SPY flat at 500; AAPL flat at 100 except a +2% open-to-close jump on each
    planted event's D (every 12th session); controls 6 sessions later, with no move after them."""
    cfg = load_market("us")
    sessions = calendar.sessions_ahead(cfg, datetime(2026, 1, 5).date(), 12 * 12 + 12)
    bars_spy, bars_aapl, price, events = {}, {}, 100.0, []
    for n, day in enumerate(sessions):
        bars_spy[day] = {"open": 500.0, "high": 500.0, "low": 500.0, "close": 500.0}
        jump = n % 12 == 0 and n < 144
        close = price * 1.02 if jump else price
        bars_aapl[day] = {"open": price, "high": close, "low": price, "close": close}
        price = close
        opening = calendar.session_open_utc(cfg, day)
        if jump:
            events.append({"id": f"e{n}", "ticker": "AAPL", "ts": (opening - timedelta(hours=1)).isoformat(),
                           "event_type": "earnings", "status": "confirmed_primary", "materiality": "high"})
        elif n % 12 == 6 and n < 144:
            events.append({"id": f"c{n}", "ticker": "AAPL", "ts": (opening - timedelta(hours=1)).isoformat(),
                           "event_type": "other", "status": "single_source", "materiality": "low",
                           "cluster_id": f"cl{n}"})
    now = datetime(2026, 12, 31, tzinfo=timezone.utc)
    data = MarketData(market="us", cfg=cfg, now=now, rates=US_RATES, bars={"SPY": bars_spy, "AAPL": bars_aapl},
                      betas={"AAPL": 1.0})
    return data, events


def test_news_impact_recovers_a_planted_effect():
    data, events = planted_market()
    rows = {(r["event_type"], r["horizon_days"]): r for r in
            news_impact.impact_rows(data, events, (1, 3, 5), "2026-W53", data.now)}
    for k in (1, 3, 5):
        planted, control = rows[("earnings", k)], rows[("other", k)]
        assert planted["n_events"] == 12 and planted["enough"] is True
        assert planted["mean_abnormal_pct"] == pytest.approx(2.0, abs=1e-9)        # +2% beyond a flat market
        assert control["mean_abnormal_pct"] == pytest.approx(0.0, abs=1e-9) and control["n_events"] == 12
        assert planted["id"] == f"ni-us-2026-W53-earnings-confirmed_primary-high-{k}"
    few = news_impact.impact_rows(data, events[:4], (1,), "2026-W53", data.now)
    assert all(r["enough"] is False and r["mean_abnormal_pct"] is None for r in few)


def test_news_impact_has_no_look_ahead():
    data, events = planted_market()
    early = MarketData(**{**data.__dict__, "now": datetime(2026, 2, 1, tzinfo=timezone.utc)})
    rows = news_impact.impact_rows(early, events, (1,), "2026-W05", early.now)
    assert sum(r["n_events"] for r in rows) < 12 * 2
