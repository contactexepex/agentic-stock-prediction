"""The platform page (B4): rm.status, page_key `_`, served by GET /api/v1/markets/{market}/status and read for both
markets by GET /api/v1/markets. Payload MarketStatus: the shared status block (rm_common.status_block, the same
record every page carries as `status`) plus the 1.0 fields: the session plan of the as-of date, the newest daily
run (features snapshot) and the newest news run. The route adds `freshness` (serve mode status)."""

from __future__ import annotations

from marketbrief.constants.warehouse import MARKET_PAGE_KEY, RM_STATUS, SERVE_STATUS
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder

DAILY_RUN_SQL = """SELECT as_of_date, max(computed_at) FROM features WHERE computed_at <= ?::TIMESTAMPTZ
GROUP BY as_of_date ORDER BY as_of_date DESC LIMIT 1"""
NEWS_RUN_SQL = """SELECT id, ran_at, ok, since, window_hours, reason, feeds, failed, google_queries, google_failed,
new_items FROM news_runs WHERE ran_at <= ?::TIMESTAMPTZ ORDER BY ran_at DESC, id DESC LIMIT 1"""
NEWS_RUN_FIELDS = (
    "id",
    "ran_at",
    "ok",
    "since",
    "window_hours",
    "reason",
    "feeds",
    "failed",
    "google_queries",
    "google_failed",
    "new_items",
)
TIME_FIELDS = ("ran_at", "since")
NUMBER_FIELDS = ("window_hours",)
COUNT_FIELDS = ("feeds", "failed", "google_queries", "google_failed", "new_items")


def last_daily_run(ctx: BuildContext) -> dict | None:
    """The newest features snapshot stored by the cut-off: its as-of date and when it was computed."""
    row = ctx.con.execute(DAILY_RUN_SQL, [ctx.cutoff]).fetchone()
    if row is None:
        return None
    return {"as_of_date": row[0].isoformat(), "computed_at": rm_common.iso_z(row[1])}


def value_of(name: str, value):
    """One news_runs column in its JSON form."""
    if value is None:
        return None
    if name in TIME_FIELDS:
        return rm_common.iso_z(value)
    if name in NUMBER_FIELDS:
        return json_safe_float(value)
    if name in COUNT_FIELDS:
        return int(value)
    return bool(value) if name == "ok" else str(value)


def last_news_run(ctx: BuildContext) -> dict | None:
    """The newest news_runs row stored by the cut-off (ran_at)."""
    row = ctx.con.execute(NEWS_RUN_SQL, [ctx.cutoff]).fetchone()
    return None if row is None else {name: value_of(name, value) for name, value in zip(NEWS_RUN_FIELDS, row)}


def status_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.status: the market's one status page."""
    payload = {
        **rm_common.status_block(ctx),
        "plan": ctx.dashboard.get("plan"),
        "last_daily_run": last_daily_run(ctx),
        "last_news_run": last_news_run(ctx),
    }
    return {MARKET_PAGE_KEY: payload}


def status_mockup(mockup: dict, market: str, _page_key: str) -> dict:
    """The mockups' status record of a market (every page's data.json carries it as `status`)."""
    return mockup["markets"][market]["status"]


BUILDERS = (PageBuilder(RM_STATUS, "MarketStatus", status_pages, owner="B4", serve=SERVE_STATUS),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/status",
        table=RM_STATUS,
        mockup="design/mockups/01-home/data.json",
        mockup_payload=status_mockup,
        # the status page adds plan, last_daily_run and last_news_run (1.0) to the mockups' status record
        extra_keys=("plan", "last_daily_run", "last_news_run"),
    ),
)
