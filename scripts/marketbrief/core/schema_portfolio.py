"""Column types of the paper portfolio's kinds (WS4; scripts/portfolio.py, docs/ws/ws4.md). Research only:
a paper trade is a record, never an order."""
from __future__ import annotations

from marketbrief.constants.kinds import KIND_PORTFOLIO_TRADES, KIND_WATCHLIST_REQUESTS
from marketbrief.core.schema_base import Schemas

PORTFOLIO_SCHEMAS: Schemas = {
    # One row per recorded paper trade, in the day file of entered_at (UTC). side buy | sell, or cancel for a
    # row that only cancels the trade named in `supersedes` (quantity 0, price null). A correction is a new
    # buy/sell row whose `supersedes` names the trade it replaces; rows are never edited. price is as traded
    # (the stored bar's basis on trade_date); price_basis open | close (the stored bar's) | manual (checked
    # against that bar's low and high). idempotency_key: a repeat of the same key is rejected.
    KIND_PORTFOLIO_TRADES: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "ticker": "VARCHAR", "side": "VARCHAR", "quantity": "DOUBLE",
        "price": "DOUBLE", "price_basis": "VARCHAR", "trade_date": "DATE", "source": "VARCHAR",
        "idempotency_key": "VARCHAR", "entered_at": "TIMESTAMPTZ", "note": "VARCHAR", "supersedes": "VARCHAR",
        # issue #112: the channel identity that asked (inbox `submitted_by`, e.g. slack:U07ABCD123; null from the
        # CLI) and the web tier's command id of the inbox row (as watchlist_events.command_id)
        "submitted_by": "VARCHAR", "command_id": "VARCHAR",
    }),
    # A request to add a company to the watchlist (status requested). Adding it to config/markets/<market>.yaml
    # stays a human or reviewed change; this row is only the request.
    KIND_WATCHLIST_REQUESTS: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "ticker": "VARCHAR", "name": "VARCHAR", "reason": "VARCHAR",
        "requested_at": "TIMESTAMPTZ", "source": "VARCHAR", "status": "VARCHAR", "idempotency_key": "VARCHAR",
    }),
}
