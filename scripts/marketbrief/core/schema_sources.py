"""Column types of the free market-wide sources and of the relationship kinds (India and the connection map)."""
from __future__ import annotations

from marketbrief.core.schema_base import Schemas

# Free market-wide sources (issue #9; HTTP and storage in sources.py). A revised value is a new
# row with the same id; the *_daily/_series views keep a complete row over an incomplete one,
# then the newest first_seen_at. A per-session file stored incomplete (`complete` false) is
# fetched again on the next run while it is in the lookback.
FREE_SOURCE_SCHEMAS: Schemas = {
    # US macro (collect_macro.py): one row per series and observation date. unit: pct | ratio | index.
    "macro": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "series": "VARCHAR", "name": "VARCHAR", "value": "DOUBLE",
        "unit": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "complete": "BOOLEAN",  # Cboe: the session file had every configured ratio (Treasury, FRED: true)
    }),
    # US FINRA Reg SHO daily short-sale volume (collect_shorts.py); short_pct in percent of the
    # FINRA-reported (off-exchange) volume, not of all trading.
    "shorts": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "ticker": "VARCHAR", "short_volume": "DOUBLE",
        "short_exempt_volume": "DOUBLE", "total_volume": "DOUBLE", "short_pct": "DOUBLE",
        "markets": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "complete": "BOOLEAN",  # the day file was whole (trailer count matched) and had every watchlist ticker
    }),
    # US FINRA consolidated short interest, twice a month (collect_shorts.py); change_pct in percent.
    "short_interest": ("jsonl", {
        "id": "VARCHAR", "settlement_date": "DATE", "ticker": "VARCHAR", "short_interest": "DOUBLE",
        "prev_short_interest": "DOUBLE", "change_pct": "DOUBLE", "avg_daily_volume": "DOUBLE",
        "days_to_cover": "DOUBLE", "revised": "BOOLEAN", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    # India NSDL daily FPI investment by asset class and route, INR crore (collect_flows_india.py).
    "fpi": ("jsonl", {
        "id": "VARCHAR", "reporting_date": "DATE", "asset_class": "VARCHAR", "route": "VARCHAR",
        "gross_purchases_cr": "DOUBLE", "gross_sales_cr": "DOUBLE", "net_cr": "DOUBLE",
        "net_usd_mn": "DOUBLE", "usd_inr": "DOUBLE", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    # India NSE index closes with valuation (collect_flows_india.py); sector = watchlist sector it stands for.
    "indices": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "index_name": "VARCHAR", "sector": "VARCHAR", "open": "DOUBLE",
        "high": "DOUBLE", "low": "DOUBLE", "close": "DOUBLE", "change_pct": "DOUBLE", "volume": "DOUBLE",
        "turnover_cr": "DOUBLE", "pe": "DOUBLE", "pb": "DOUBLE", "div_yield": "DOUBLE",
        "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "complete": "BOOLEAN",  # the session file had every configured index for the right date
    }),
}

# Relationships (DESIGN.md phase 5): India insider/promoter trades (SEBI PIT), bulk and block
# deals, shareholding incl. promoter pledges (collect_relations_india.py), and the per-company
# connection map for both markets (graph-builder agent, graph.py). Merged as a column union so a
# market-specific collector can share a kind (e.g. US Form 4 rows in `insiders`): read_json fills
# columns a row does not have with NULL, and an existing column keeps its type.
RELATION_SCHEMAS: Schemas = {
    "insiders": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "source": "VARCHAR", "person": "VARCHAR",
        "person_category": "VARCHAR", "security_type": "VARCHAR", "transaction": "VARCHAR",
        "mode": "VARCHAR", "shares": "DOUBLE", "value": "DOUBLE",
        "holding_before_pct": "DOUBLE", "holding_after_pct": "DOUBLE",
        "trade_from": "DATE", "trade_to": "DATE", "disclosed_at": "TIMESTAMPTZ",
        "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "deals": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "ticker": "VARCHAR", "deal_type": "VARCHAR",
        "client": "VARCHAR", "side": "VARCHAR", "shares": "DOUBLE", "price": "DOUBLE",
        "value": "DOUBLE", "remarks": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "holdings": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "period_end": "DATE", "source": "VARCHAR",
        "promoter_pct": "DOUBLE", "public_pct": "DOUBLE", "employee_trust_pct": "DOUBLE",
        "pledged_pct_of_promoter": "DOUBLE", "pledged_pct_of_total": "DOUBLE",
        "filed_at": "TIMESTAMPTZ", "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        # nse_pledge rows (depository system-driven disclosures; see collect_relations_india.py)
        "sdd_promoter_pct": "DOUBLE", "promoter_shares": "DOUBLE", "total_shares": "DOUBLE",
        "promoter_encumbered_shares": "DOUBLE", "depository_pledged_shares": "DOUBLE",
        "depository_pledged_pct": "DOUBLE",
    }),
    # India primary sources from NSE (collect_nse_india.py).
    "announcements": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "company": "VARCHAR", "published_at": "TIMESTAMPTZ",
        "category": "VARCHAR", "subject": "VARCHAR", "url": "VARCHAR", "source": "VARCHAR",
        "first_seen_at": "TIMESTAMPTZ",
    }),
    "financials": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "basis": "VARCHAR", "period_type": "VARCHAR",
        "period_start": "DATE", "period_end": "DATE", "revenue": "DOUBLE", "revenue_item": "VARCHAR",
        "total_income": "DOUBLE", "profit_before_tax": "DOUBLE", "net_profit": "DOUBLE",
        "profit_to_owners": "DOUBLE", "eps_basic": "DOUBLE", "eps_diluted": "DOUBLE",
        "audited": "VARCHAR", "taxonomy": "VARCHAR", "filing_type": "VARCHAR", "filed_at": "TIMESTAMPTZ",
        "url": "VARCHAR", "seq_id": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "flows": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "category": "VARCHAR", "buy_cr": "DOUBLE", "sell_cr": "DOUBLE",
        "net_cr": "DOUBLE", "provisional": "BOOLEAN", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "delivery": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "ticker": "VARCHAR", "series": "VARCHAR", "close": "DOUBLE",
        "volume": "DOUBLE", "delivery_qty": "DOUBLE", "delivery_pct": "DOUBLE", "trades": "DOUBLE",
        "turnover_lacs": "DOUBLE", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "graph": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "relation": "VARCHAR", "target": "VARCHAR",
        "target_kind": "VARCHAR", "target_ticker": "VARCHAR", "aliases": "VARCHAR[]",
        "detail": "VARCHAR", "weight": "DOUBLE", "status": "VARCHAR", "as_of": "DATE",
        "source_url": "VARCHAR", "added_at": "TIMESTAMPTZ", "prompt_version": "VARCHAR",
    }),
    # One row per connection-map refresh attempt (graph.py attempt), even when no edge changed.
    "graph_runs": ("jsonl", {
        "id": "VARCHAR", "run_at": "TIMESTAMPTZ", "month": "VARCHAR", "edges": "INTEGER",
        "tickers_without_edges": "INTEGER", "note": "VARCHAR",
    }),
}
