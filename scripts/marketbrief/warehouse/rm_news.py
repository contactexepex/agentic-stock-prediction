"""The News page (B11; design/mockups/09-news/notes.md): rm.news, page_key `_`, served by
GET /api/v1/markets/{market}/news (schema NewsPayload in api/schemas/news.yaml).

Payload: the page shell (header, horizons, status, go-live), the News window of the 3 days before the cut-off (at most
50 items, 25 company and 25 market-wide by the owner's rule of 2026-10-08; news_items.capped), the calendar from the
session being predicted to 7 days after it (active companies' dates) and the companies of the rail (B4's Company
records, by ticker). Everything is as of the cut-off; no build time is in the payload."""

from __future__ import annotations

from datetime import date, timedelta

from marketbrief.constants.market_pages import NEWS_CALENDAR_DAYS, RM_NEWS
from marketbrief.constants.warehouse import MARKET_PAGE_KEY
from marketbrief.warehouse.calendar_events import calendar_events
from marketbrief.warehouse.market_page_parts import companies, market_mockup, news_selection, pick, session_date, shell
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder

ENRICHMENT_FIELDS = ("event_type", "materiality", "sentiment", "relevance", "novelty", "urgency", "priced_in",
                     "analyzed_at", "geopolitical")
NEWS_FIELDS = ("id", "market", "tickers", "primary_tickers", "title", "source", "source_domain", "url", "published_at",
               "first_seen_at", "status", "status_as_of", "independent_origins", "primary_ids", "cluster_id", "scope",
               "category", "feed", "summary", "summary_source", "market_moving", "origin",
               ("enrichment", ENRICHMENT_FIELDS))
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state", "open_trades")


def calendar(ctx: BuildContext) -> list[dict]:
    """The calendar rows from the session being predicted to NEWS_CALENDAR_DAYS after it, active companies only."""
    first = date.fromisoformat(session_date(ctx))
    last = first + timedelta(days=NEWS_CALENDAR_DAYS)
    return calendar_events(ctx.cfg, ctx.con, ctx.cutoff_time, first, last, tickers=sorted(ctx.active))


def news_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.news: the market's one News page."""
    items, window = news_selection(ctx)
    payload = {
        **shell(ctx),
        "window": window,
        "news": [pick(item, NEWS_FIELDS) for item in items],
        "calendar": calendar(ctx),
        "calendar_days": NEWS_CALENDAR_DAYS,
        "companies": sorted(companies(ctx, COMPANY_FIELDS), key=lambda company: company["ticker"]),
    }
    return {MARKET_PAGE_KEY: payload}


BUILDERS = (PageBuilder(RM_NEWS, "NewsPayload", news_pages, owner="B11"),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/news",
        table=RM_NEWS,
        mockup="design/mockups/09-news/data.json",
        mockup_payload=market_mockup,
    ),
)
