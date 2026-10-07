"""Column types of the strategy lab's own kind (B2; docs/ws/b2.md, owner decisions 50-51). Research only: a paper
trade is a record, never an order. Conventions as in core/schema_lab.py (money in the market currency, `_pct` in
percent points)."""
from __future__ import annotations

from marketbrief.constants.kinds import KIND_COST_VIEWS
from marketbrief.core.schema_base import Schemas

B2_SCHEMAS: Schemas = {
    # The two cost views (decision 50) and the cost-viable flag (decision 51) of one lab record, in the day file of
    # computed_at: id = cv:<record_kind>:<record_id>. record_kind prediction | pick (pre-open: every prediction or
    # pick that would trade, with the round trip estimated at the reference price C = base_close) | settlement
    # (post-close: the settled trade's actual costs; record_id = the paper_trades_settled id).
    # expected_move_pct = (target / C - 1) x 100; your_cost_pct / market_cost_pct = the round trip in that view
    # as % of the amount; cost_viable = expected_move_pct > your_cost_pct. market_costs = the paper_trades_settled
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
        "cost_viable": "BOOLEAN", "market_costs": "DOUBLE", "market_cost_lines": "JSON", "your_costs": "DOUBLE",
        "your_cost_lines": "JSON", "net_pnl_market": "DOUBLE", "return_pct_market": "DOUBLE",
        "net_pnl_your": "DOUBLE", "return_pct_your": "DOUBLE", "holding_days": "INTEGER", "eurusd_entry": "DOUBLE",
        "eurusd_exit": "DOUBLE", "computed_at": "TIMESTAMPTZ", "method_version": "VARCHAR",
    }),
}
