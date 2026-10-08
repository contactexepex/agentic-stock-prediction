"""Column types of the strategy lab's own kinds (B2; docs/ws/b2.md, owner decisions 50-51). Research only: a paper
trade is a record, never an order. Conventions as in core/schema_lab.py (money in the market currency, `_pct` in
percent points)."""
from __future__ import annotations

from marketbrief.constants.kinds import KIND_COST_VIEWS, KIND_LAB_BACKTESTS
from marketbrief.core.schema_base import Schemas

B2_SCHEMAS: Schemas = {
    # The two cost views (decision 50) and the cost-viable flag (decision 51) of one lab record, in the day file of
    # computed_at: id = cv:<record_kind>:<record_id>. record_kind prediction | pick (pre-open: every prediction or
    # pick that would trade, with the round trip estimated at the reference price C = base_close) | settlement
    # (post-close: the settled trade's actual costs; record_id = the paper_trades_settled id).
    # expected_move_pct = (target / C - 1) x 100; your_cost_pct / market_cost_pct = the round trip in that view
    # as % of the amount; expected_gain_your_pct = p x move - (1 - p) x loss - your_cost_pct with the picks' move
    # and loss (lab/gain.py); cost_viable = expected_gain_your_pct > 0 (owner decision 2026-10-07; null without a
    # probability or range, when the amount buys no whole share at C (no trade, no costs: the cost columns are
    # null too), and on settlement rows). market_costs = the paper_trades_settled
    # `costs` (strategies are ranked on it); your_costs = market + owner-specific items (India NRI reporting
    # charge per trade date and DP charge; US BUX FX markup each way and the pro-rated portfolio fee); the
    # *_lines are JSON {charge: amount}. net_pnl_* and return_pct_* for settlements only (return = net / amount).
    # holding_days: calendar days from D to the exit session (the US portfolio fee).
    KIND_COST_VIEWS: ("jsonl", {
        "id": "VARCHAR", "record_kind": "VARCHAR", "record_id": "VARCHAR", "trade_id": "VARCHAR",
        "prediction_id": "VARCHAR", "strategy_id": "VARCHAR", "market": "VARCHAR", "ticker": "VARCHAR",
        "horizon_days": "INTEGER", "session_date": "DATE", "exit_date": "DATE", "amount": "DOUBLE",
        "currency": "VARCHAR", "reference_price": "DOUBLE", "target_price": "DOUBLE",
        "expected_move_pct": "DOUBLE", "market_cost_pct": "DOUBLE", "your_cost_pct": "DOUBLE",
        "expected_gain_your_pct": "DOUBLE",
        "cost_viable": "BOOLEAN", "market_costs": "DOUBLE", "market_cost_lines": "JSON", "your_costs": "DOUBLE",
        "your_cost_lines": "JSON", "net_pnl_market": "DOUBLE", "return_pct_market": "DOUBLE",
        "net_pnl_your": "DOUBLE", "return_pct_your": "DOUBLE", "holding_days": "INTEGER", "eurusd_entry": "DOUBLE",
        "eurusd_exit": "DOUBLE", "computed_at": "TIMESTAMPTZ", "method_version": "VARCHAR",
    }),
    # The F2.3 back-test (lab/backtest.py; basis backtest, never pooled with forward results) as stored by
    # `lab.py backtest --store` (lab/backtest_store.py), in the day file of computed_at: one row per strategy and
    # horizon ("1".."5" or "all" = pooled). run_id = <market>-<as_of_date>-<stored|history>, id =
    # bt:<run_id>:<strategy_id>:<horizon>; a rerun of a run_id stores nothing new. as_of_date = the clock's last
    # complete session; history = the long-history cache was added; splice = its diagnostics per symbol;
    # eurusd_source = how the BUX order fee was converted; probs_source = walk_forward:<model_version> when the
    # model strategies without news got B10's walk-forward probabilities, else null; note = why they did not (null
    # otherwise); data_first_date / data_last_date = the bars' span. Row numbers in the market-cost view, your_* in
    # the owner's (cost_views); luck_test JSON as lab/luck.py; sample_badge ok | too_few_to_rank.
    KIND_LAB_BACKTESTS: ("jsonl", {
        "id": "VARCHAR", "run_id": "VARCHAR", "market": "VARCHAR", "computed_at": "TIMESTAMPTZ",
        "as_of_date": "DATE", "history": "BOOLEAN", "splice": "JSON", "eurusd_source": "VARCHAR",
        "probs_source": "VARCHAR", "note": "VARCHAR", "data_first_date": "DATE", "data_last_date": "DATE",
        "method_version": "VARCHAR", "strategy_id": "VARCHAR", "family": "VARCHAR", "horizon": "VARCHAR",
        "trades": "INTEGER", "net_pnl": "DOUBLE", "mean_return_pct": "DOUBLE", "win_rate": "DOUBLE",
        "worst_losing_streak": "INTEGER", "max_drawdown": "DOUBLE", "your_net_pnl": "DOUBLE",
        "your_mean_return_pct": "DOUBLE", "luck_test": "JSON", "sample_badge": "VARCHAR", "first_entry": "DATE",
        "last_exit": "DATE",
    }),
}
