"""B2 F2.3 back-test (lab/backtest.py) on five hand-made US sessions: the as-of row -> entry (next open) -> exit
(the k-th close after the entry) indexing, the momentum filter, both cost views through lab/costs.py, the summary
numbers and the luck test's m. Every number below is worked out by hand in the comments."""
from __future__ import annotations

import pandas as pd
import pytest
from lab_fixtures import US_RATES

from marketbrief.lab import backtest, registry
from marketbrief.lab import costs as lab_costs

# (open, close) per session; Monday 5 Oct .. Friday 9 Oct 2026
BARS = pd.DataFrame({"open": [100.0, 100.0, 102.0, 100.0, 104.0], "close": [100.0, 101.0, 100.0, 105.0, 106.0]},
                    index=pd.DatetimeIndex(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]))
EURUSD = pd.Series([1.2], index=pd.DatetimeIndex(["2026-01-02"]))
CONTEXT = {"rate": US_RATES, "eurusd": EURUSD, "probs": None}


def test_trade_indexing_and_costs():
    trades = backtest.ticker_trades("us", BARS, 1, CONTEXT)
    # as-of rows 5, 6, 7 Oct: entry at the next open, exit at that session's close (N+1)
    assert [str(d.date()) for d in trades["entry_date"]] == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert [str(d.date()) for d in trades["exit_date"]] == ["2026-10-07", "2026-10-08", "2026-10-09"]
    assert list(trades["shares"]) == [10.0, 9.803922, 10.0]                     # 1000 / 102 to 6 decimals
    # market: order fee .99 x 1.2 x 2 = 2.376 -> 2.38 + SEC .0000206 x S -> 0.02 = 2.40 per trade
    # gross 0, 9.803922 x (105 - 102) = 29.411766, 60
    assert list(trades["net_pnl"].round(6)) == [-2.4, 27.011766, 57.6]
    # your: + FX .0075 x (B + S) (15.00, 15.22, 15.45) + fee .002 x B x 1 / 365 = 0.0055 -> 0.01
    assert list(trades["net_pnl_your"].round(6)) == [-17.41, 11.781766, 42.14]
    assert list(trades["up_last"]) == [False, True, False]                     # 101 > 100 on 6 Oct only
    one = lab_costs.cost_views("us", US_RATES, (1000.0, 1000.0), 10.0, {"eurusd": (1.2, 1.2), "holding_days": 1})
    assert (one["market"]["total"], one["your"]["total"]) == (2.40, 17.41)     # the engine's own cost code


def test_two_session_horizon_indexing():
    trades = backtest.ticker_trades("us", BARS, 2, CONTEXT)
    # N+2: entry 6 Oct open 100 -> 8 Oct close 105; entry 7 Oct open 102 -> 9 Oct close 106
    assert [(str(a.date()), str(b.date())) for a, b in zip(trades["entry_date"], trades["exit_date"])] == [
        ("2026-10-06", "2026-10-08"), ("2026-10-07", "2026-10-09")]


def test_run_backtest_rows():
    specs = registry.rule_and_baselines()
    rows = {(r["strategy_id"], r["horizon_days"]): r
            for r in backtest.run_backtest("us", {"AAPL": BARS}, specs, (1, 2), CONTEXT)}
    always = rows[("base.always_up.v1", 1)]
    # net -2.40 + 27.011766 + 57.60 = 82.211766; returns -0.24, 2.7011766, 5.76 -> mean 2.7403922
    assert (always["trades"], always["net_pnl"], always["mean_return_pct"], always["win_rate"]) == (
        3, 82.21, 2.7404, 0.6667)
    assert (always["worst_losing_streak"], always["max_drawdown"], always["basis"]) == (1, -2.4, "backtest")
    assert always["your_cost"]["net_pnl"] == 36.51                               # -17.41 + 11.781766 + 42.14
    momentum = rows[("base.momentum.v1", 1)]
    assert (momentum["trades"], momentum["net_pnl"]) == (1, 27.01)               # only the 6 Oct as-of row
    assert always["luck_test"]["m"] == 2 and rows[("base.always_up.v1", "all")]["trades"] == 5
    assert ("base.model_only.v1", 1) not in rows                                 # needs B10's probabilities
    with pytest.raises(KeyError):
        rows[("rule.model_news.v1", 1)]                                          # uses news: never back-tested
