"""B2's go-live switch (config/strategies.yaml `live_from`, registry.is_live): a strategy trades only on sessions
D >= its live_from. A pre-live prediction or pick is never settled (now or after the switch: D is fixed per row),
a non-live strategy never contends in pick, and the forward summary counts only live settlements. Offline, tmp
roots (test_lab_db's fixture, whose config copy sets every strategy live from LIVE_FROM)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import yaml
from lab_fixtures import prediction
from test_lab_db import NOW, root, set_live_from, stored_trades, write_jsonl  # noqa: F401 (root is a fixture)

import common
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.lab import registry, reports, run, scoreboard, settle_run

D = "2026-10-02"                       # the fixture predictions' entry session (US)
PICK_TIME = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
REG = yaml.safe_load("""
horizons: [1, 2, 3, 4, 5]
strategies:
  - {id: rule.a.v1, family: rule, live_from: 2026-10-02}
  - {id: rule.b.v1, family: rule, live_from: '2026-10-05'}
  - {id: rule.c.v1, family: rule, live_from: null}
""")


def switch(live_from: str | None, ids: tuple[str, ...] | None = None) -> None:
    """Set live_from in the tmp config copy and drop the cached registry."""
    set_live_from(common.CONFIG, live_from, ids)
    registry._cached.cache_clear()


def count(kind: str) -> int:
    try:
        return connect("us").execute(f"SELECT count(*) FROM {kind}").fetchone()[0]
    except Exception:  # noqa: BLE001 (no file of the kind stored: the view has no rows to read)
        return 0


def test_is_live_true_false_unknown_and_edge():
    assert registry.is_live("rule.a.v1", "2026-10-02", REG) is True              # live_from == D (edge)
    assert registry.is_live("rule.a.v1", date(2026, 10, 9), REG) is True
    assert registry.is_live("rule.a.v1", "2026-10-01", REG) is False             # D before live_from
    assert registry.is_live("rule.b.v1", "2026-10-02T00:00:00", REG) is False
    assert registry.is_live("rule.b.v1", "2026-10-05", REG) is True              # a quoted live_from
    assert registry.is_live("rule.c.v1", "2030-01-01", REG) is False             # null: never live
    assert registry.is_live("rule.unknown.v1", "2030-01-01", REG) is False       # unknown id
    assert registry.is_live({"id": "x", "live_from": date(2026, 10, 2)}, "2026-10-02") is True   # an entry dict
    assert registry.is_live({"id": "x", "live_from": None}, "2026-10-02") is False
    assert registry.is_live({"id": "x"}, "2026-10-02") is False


def test_the_shipped_registry_goes_live_on_2026_10_12():
    # Go-live G = 2026-10-12 (SPEC decision 23; switched on by B19 with B2's consent): every shipped strategy has
    # live_from G, none is live on the last pre-go-live session and all are live on G.
    specs = registry.strategies(registry.load_registry())
    assert specs
    assert all(str(spec["live_from"]) == "2026-10-12" for spec in specs)
    assert not any(registry.is_live(spec, "2026-10-09", None) for spec in specs)
    assert all(registry.is_live(spec, "2026-10-12", None) for spec in specs)


def test_live_settlements_keeps_trades_live_on_their_entry_date():
    rows = [{"strategy_id": "rule.a.v1", "entry_date": "2026-10-02"},
            {"strategy_id": "rule.a.v1", "entry_date": "2026-10-01"},
            {"strategy_id": "rule.b.v1", "entry_date": "2026-10-02"},
            {"strategy_id": "rule.c.v1", "entry_date": "2026-10-09"},
            {"strategy_id": "rule.gone.v1", "entry_date": "2026-10-09"}]
    assert scoreboard.live_settlements(rows, REG) == [rows[0]]


def test_settle_skips_a_pre_live_prediction_and_its_pick_now_and_after_the_switch(root):  # noqa: F811
    cfg = load_market("us")
    pred = prediction("us", "AAPL", 1, target_price=102.2, lo80=99.0, hi80=103.0)
    pick = {"id": "h2h:2026-10-01-AAPL-rule-highest_probability", "market": "us", "ticker": "AAPL",
            "made_at": "2026-10-02T12:00:00+00:00", "session_date": D, "family": "rule",
            "pick_rule": "highest_probability", "status": "picked", "strategy_id": pred["strategy_id"],
            "prediction_id": pred["id"], "horizon_days": 1}
    write_jsonl(root, "us", "strategy_predictions", D, [pred])
    write_jsonl(root, "us", "head_to_head_picks", D, [pick])
    switch(None)                                             # not live (the shipped state)
    out = settle_run.settle_due(connect("us"), cfg, NOW, betas={})
    assert (out["due"], out["written"], out["cost_views"], out["not_live"]) == (0, 0, 0, 2)
    assert out["refused_not_locked"] == [] and count("paper_trades_settled") == count("cost_views") == 0
    switch("2026-10-05")                                     # switched on after D: the row stays pre-live
    out = settle_run.settle_due(connect("us"), cfg, NOW, betas={})
    assert (out["due"], out["written"], out["cost_views"], out["not_live"]) == (0, 0, 0, 2)
    assert count("paper_trades_settled") == count("cost_views") == 0


def test_settle_trades_a_live_prediction_and_its_pick(root):  # noqa: F811
    cfg = load_market("us")
    pred = prediction("us", "AAPL", 1, target_price=102.2, lo80=99.0, hi80=103.0)
    pick = {"id": "h2h:2026-10-01-AAPL-rule-highest_probability", "market": "us", "ticker": "AAPL",
            "made_at": "2026-10-02T12:00:00+00:00", "session_date": D, "family": "rule",
            "pick_rule": "highest_probability", "status": "picked", "strategy_id": pred["strategy_id"],
            "prediction_id": pred["id"], "horizon_days": 1}
    write_jsonl(root, "us", "strategy_predictions", D, [pred])
    write_jsonl(root, "us", "head_to_head_picks", D, [pick])
    switch(D)                                                # live_from == D: trades
    out = settle_run.settle_due(connect("us"), cfg, NOW, betas={})
    assert (out["written"], out["cost_views"], out["not_live"]) == (2, 2, 0)
    assert sorted(t["trade_id"] for t in stored_trades()) == [f"acc:{pred['id']}",
                                                               f"h2h:highest_probability:{pred['id']}"]
    assert stored_trades()[0]["net_pnl"] == 17.7                     # as test_lab_db's hand-checked trade


def test_pick_lets_only_live_strategies_contend(root):  # noqa: F811
    cfg = load_market("us")
    strong = prediction("us", "AAPL", 1, prob_up=0.8, target_price=101.0, lo80=98.0, hi80=104.0, base_close=100.0)
    live = prediction("us", "AAPL", 2, prob_up=0.6, target_price=101.0, lo80=98.0, hi80=104.0, base_close=100.0,
                      id="rule.model_news_half.v1:2026-10-01-AAPL-2d", strategy_id="rule.model_news_half.v1")
    ai = prediction("us", "AAPL", 3, target_price=101.0, lo80=96.0, hi80=106.0, base_close=100.0,
                    id="ai.combined.opus.v1:2026-10-01-AAPL-3d", strategy_id="ai.combined.opus.v1", family="ai")
    write_jsonl(root, "us", "strategy_predictions", D, [strong, live, ai])
    switch(None)
    switch(D, ("rule.model_news_half.v1",))                  # the only live strategy on D
    out = run.pick_day(connect("us"), cfg, PICK_TIME, registry.strategies(), D)
    assert (out["live_strategies"], out["picks"], out["written"], out["no_candidate"]) == (1, 2, 2, 0)
    picks = connect("us").execute("SELECT family, strategy_id, prediction_id, ranking FROM head_to_head_picks "
                                  "ORDER BY pick_rule").fetchall()
    assert [(p[0], p[1], p[2]) for p in picks] == [("rule", "rule.model_news_half.v1", live["id"])] * 2
    assert all([r["strategy_id"] for r in yaml.safe_load(p[3])] == ["rule.model_news_half.v1"] for p in picks)


def test_pick_writes_no_pick_with_nothing_live(root):  # noqa: F811
    cfg = load_market("us")
    write_jsonl(root, "us", "strategy_predictions", D,
                [prediction("us", "AAPL", 1, target_price=101.0, lo80=98.0, hi80=104.0, base_close=100.0)])
    switch(None)
    out = run.pick_day(connect("us"), cfg, PICK_TIME, registry.strategies(), D)
    assert out == {"session_date": D, "live_strategies": 0, "picks": 0, "written": 0, "no_candidate": 0,
                   "cost_views": 1, "cost_viable": out["cost_viable"]}   # the prediction's cost flag (rehearsal)
    assert count("head_to_head_picks") == 0


def test_forward_summary_counts_only_live_settlements(root):  # noqa: F811
    cfg = load_market("us")
    kept = prediction("us", "AAPL", 1, target_price=102.2, lo80=99.0, hi80=103.0)
    dropped = prediction("us", "AAPL", 1, target_price=102.2, lo80=99.0, hi80=103.0,
                         id="rule.model_news_half.v1:2026-10-01-AAPL-1d", strategy_id="rule.model_news_half.v1")
    write_jsonl(root, "us", "strategy_predictions", D, [kept, dropped])
    assert settle_run.settle_due(connect("us"), cfg, NOW, betas={})["written"] == 2     # both live (fixture)
    switch("2026-10-05", ("rule.model_news_half.v1",))       # a settlement whose D is not live for its strategy
    summary = reports.lab_summary(connect("us"), NOW)
    assert {r["strategy_id"] for r in summary["scoreboard"] if r["scope"] == "strategy"} == {"rule.model_news.v1"}
    assert {c["strategy_id"] for c in summary["heatmaps"]["cells"]} == {"rule.model_news.v1"}
