"""The Companies page (B11; design/mockups/10-companies/notes.md): rm.companies, page_key `_`, served by
GET /api/v1/markets/{market}/companies (schema CompaniesPayload in api/schemas/companies.yaml).

Payload: the page shell, the market's default paper amount (decision 26), B4's Company records (active first, then
by ticker; a deleted company never appears, decision 12), the lifecycle events recorded by the cut-off of the
companies shown, the company commands received by the cut-off with every echo of a deleted company masked, the news
tagged with an inactive company since it went inactive, and how many companies were deleted. Everything is as of the
cut-off; no build time is in the payload."""

from __future__ import annotations

from marketbrief.constants.market_pages import RM_COMPANIES
from marketbrief.constants.warehouse import MARKET_PAGE_KEY
from marketbrief.contracts.watchlist import DEFAULT_AMOUNT
from marketbrief.lifecycle.constants import STATE_ACTIVE
from marketbrief.warehouse.company_records import command_rows, inactive_news, lifecycle_rows, shown_companies
from marketbrief.warehouse.market_page_parts import companies, pick, shell
from marketbrief.warehouse.news_items import news_items
from marketbrief.warehouse.rm_news import market_mockup
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder

COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "state_since", "added_at", "amount",
                  "amount_overridden", "currency", "yahoo", "nse_symbol", "cik", "last_close", "last_close_date",
                  "change_pct", ("agreement_n1", ("buy", "of")), "open_trades")
NEWS_FIELDS = ("id", "market", "tickers", "primary_tickers", "title", "source", "published_at", "first_seen_at",
               "status", ("enrichment", ("event_type", "materiality", "sentiment", "relevance", "novelty", "urgency",
                                         "priced_in", "analyzed_at")))


def news_of_inactive(ctx: BuildContext, records: list[dict]) -> list[dict]:
    """News items tagged with an inactive company and first seen since it went inactive, by the cut-off."""
    inactive = [record for record in records if record["state"] != STATE_ACTIVE]
    if not inactive:
        return []
    since = min(record["state_since"] for record in inactive)
    items = news_items(ctx.cfg, ctx.con, ctx.cutoff_time, tickers=[record["ticker"] for record in inactive],
                       since=since)
    return [pick(item, NEWS_FIELDS) for item in inactive_news(items, records)]


def companies_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.companies: the market's one Companies page."""
    records, deleted = shown_companies(ctx.market, ctx.cutoff_time)
    rows = sorted(companies(ctx, COMPANY_FIELDS), key=lambda row: (row["state"] != STATE_ACTIVE, row["ticker"]))
    payload = {
        **shell(ctx),
        "default_amount": DEFAULT_AMOUNT[ctx.market],
        "companies": rows,
        "lifecycle": lifecycle_rows(ctx.con, ctx.cutoff_time, {row["ticker"] for row in rows}),
        "commands": command_rows(ctx.con, ctx.cutoff_time, deleted),
        "news_inactive": news_of_inactive(ctx, records),
        "deleted_count": len(deleted),
    }
    return {MARKET_PAGE_KEY: payload}


BUILDERS = (PageBuilder(RM_COMPANIES, "CompaniesPayload", companies_pages, owner="B11"),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/companies",
        table=RM_COMPANIES,
        mockup="design/mockups/10-companies/data.json",
        mockup_payload=market_mockup,
    ),
)
