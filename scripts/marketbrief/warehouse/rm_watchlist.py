"""The Watchlist page (B11; design/mockups/02-watchlist/notes.md): rm.watchlist, page_key `_`, served by
GET /api/v1/markets/{market}/watchlist (schema WatchlistPayload in api/schemas/watchlist.yaml). It replaces the 1.0
Watchlist payload of the dashboard slice (WS1) under contract 2.0.

Payload: the page shell, B4's Company records (active and inactive; the page shows the active ones and names the
inactive under the table, decision 13), B4's Agreement per horizon and open trades, B12's latest trade checks by the
cut-off, the reference rule strategy's ranges (its newest predictions made by the cut-off) and the strategies.
Everything is as of the cut-off; no build time is in the payload."""

from __future__ import annotations

import pandas as pd

from marketbrief.constants.warehouse import MARKET_PAGE_KEY, REFERENCE_STRATEGY, RM_WATCHLIST
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.market_page_parts import companies, shell, trade_checks
from marketbrief.warehouse.news_items import iso
from marketbrief.warehouse.rm_news import market_mockup
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder

COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "state_since", "amount",
                  "amount_overridden", "currency", "last_close", "last_close_date", "change_pct",
                  ("agreement_n1", ("buy", "of")), "open_trades")
CHECK_FIELDS = ("id", "check_id", "check_row_id", "check_at", "session_date", "market", "ticker", "trade_id",
                "prediction_id", "strategy_id", "view", "horizon_days", "entry_date", "exit_date", "session_number",
                "entry_price", "last_price", "ret_since_entry_pct", "target_price", "to_target_pct", "lo80", "lo50",
                "hi50", "hi80", "band", "target_z", "flags", "flagged", "method_version", "computed_at")
STRATEGY_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
RANGE_TEXT = ("id", "strategy_id", "family", "ticker", "direction", "regime", "quality")
RANGE_NUMBERS = ("prob_up", "base_close", "target_price", "lo50", "hi50", "lo80", "hi80", "range_widen")
RANGE_DATES = ("as_of_date", "session_date", "exit_date")
# the reference strategy's newest predictions made by the cut-off (each id's first stored row)
RANGES_SQL = """
WITH p AS (SELECT DISTINCT ON (id) * FROM strategy_predictions
           WHERE made_at <= $cutoff::TIMESTAMPTZ AND strategy_id = $strategy ORDER BY id, made_at)
SELECT * FROM p WHERE as_of_date = (SELECT max(as_of_date) FROM p) ORDER BY ticker, horizon_days, id"""


def range_record(row: dict) -> dict:
    """One Prediction record with the fields of the range column."""
    record = {name: None if pd.isna(row[name]) else str(row[name]) for name in RANGE_TEXT}
    record["made_at"] = iso(row["made_at"])
    record.update({name: None if pd.isna(row[name]) else str(pd.Timestamp(row[name]).date()) for name in RANGE_DATES})
    record["horizon_days"] = int(row["horizon_days"])
    record["qualifies"] = None if pd.isna(row["qualifies"]) else bool(row["qualifies"])
    record.update({name: json_safe_float(row[name]) for name in RANGE_NUMBERS})
    return record


def ranges(ctx: BuildContext) -> list[dict]:
    """The reference rule strategy's newest predictions made by the cut-off, of the active companies."""
    frame = ctx.con.execute(RANGES_SQL, {"cutoff": ctx.cutoff, "strategy": REFERENCE_STRATEGY}).df()
    return [range_record(row) for row in frame.to_dict("records") if row["ticker"] in ctx.active]


def watchlist_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.watchlist: the market's one Watchlist page."""
    payload = {
        **shell(ctx),
        "companies": sorted(companies(ctx, COMPANY_FIELDS), key=lambda row: row["ticker"]),
        "agreement": rm_common.agreement(ctx),
        "open_trades": rm_common.open_trades(ctx),
        "trade_checks": trade_checks(ctx, CHECK_FIELDS),
        "ranges": ranges(ctx),
        "strategies": rm_common.strategies(ctx, STRATEGY_FIELDS),
    }
    return {MARKET_PAGE_KEY: payload}


BUILDERS = (PageBuilder(RM_WATCHLIST, "WatchlistPayload", watchlist_pages, owner="B11"),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/watchlist",
        table=RM_WATCHLIST,
        mockup="design/mockups/02-watchlist/data.json",
        mockup_payload=market_mockup,
        map_paths=("$.strategies", "$.agreement"),
    ),
)
