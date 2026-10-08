"""The company pages' read models (B12; docs/ws/b12.md), sliced per company from the market's records as of the
build's cut-off (warehouse/company_sources.read_sources, read once per build):

  rm.stock             page_key ticker  03-company, the whole page: the shared market blocks, the company, its
                                        watchlist events, agreement, picks, predictions, open trades, latest trade
                                        checks, settled trades, AI reasons, news, results, events, bars and its rows
                                        on the scoreboard (GET /markets/{market}/stocks/{ticker})
  rm.bars              page_key ticker  the company's split-adjusted bars (GET .../stocks/{ticker}/bars)
  rm.trades            page_key _       every open trade of the market and its latest check's rows (07, B13)
                       page_key ticker  the company's open trades, latest checks, settled trades and AI reasons
                                        (GET /markets/{market}/trades[?ticker=])
  rm.stock_strategies  page_key ticker  04-stock-strategies (GET .../stocks/{ticker}/strategies)

One page per collected company (ctx.collected: active and inactive; a deleted company never). Field lists and
selection rules are the mockups' (design/mockups/03-company/notes.md, 04-stock-strategies/notes.md); the shared
blocks (header, status, horizons, go_live, strategies, the Company record, Agreement, Open trade, settled trades and
the scoreboard) are rm_common's and the news items and calendar events B11's, so no record is derived twice."""
from __future__ import annotations

from datetime import date, timedelta

from marketbrief.constants.rm_company import (COMPANY_FIELDS, EVENT_DAYS, LIFECYCLE_SESSIONS, MOCKUP_COMPANY,
                                              MOCKUP_STOCK_STRATEGIES, NEWS_DAYS, NEWS_MAX, OWNER, RM_LIFECYCLE,
                                              RM_STOCK_STRATEGIES, RM_TRADES, STRATEGIES_COMPANY_FIELDS,
                                              STRATEGIES_STRATEGY_FIELDS, STRATEGY_FIELDS, TRADES_MARKET_SESSIONS,
                                              TRADES_TICKER_SESSIONS)
from marketbrief.constants.warehouse import MARKET_PAGE_KEY, REFERENCE_STRATEGY, RM_BARS, RM_STOCK, SERVE_VERBATIM
from marketbrief.core import calendar
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.calendar_events import calendar_events
from marketbrief.warehouse.company_payloads import (bars_payload, check_rows, company_news, lifecycle_payload,
                                                    market_trades_payload, pick, stock_payload,
                                                    stock_strategies_payload, trades_payload)
from marketbrief.warehouse.company_sources import CompanySources, read_sources
from marketbrief.warehouse.news_items import news_items
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder


def sources(ctx: BuildContext) -> CompanySources:
    """The market's records for the company pages, read once per build."""
    session_date = rm_common.status_block(ctx)["session"]["session_date"]
    return ctx.shared("company_sources", lambda: read_sources(ctx, ctx.as_of, session_date))


def company_blocks(ctx: BuildContext) -> dict:
    """The shared Company records by ticker, Agreement rows per horizon and Open trades (rm_common), once a build."""

    def compute() -> dict:
        return {"companies": {record["ticker"]: record for record in rm_common.companies(ctx)},
                "agreement": rm_common.agreement(ctx), "open_trades": rm_common.open_trades(ctx)}

    return ctx.shared("company_blocks", compute)


def agreement_of(agreement: dict[str, list[dict]], ticker: str) -> dict[str, list[dict]]:
    """The company's Agreement rows per horizon ("1".."5")."""
    return {horizon: [row for row in rows if row["ticker"] == ticker] for horizon, rows in agreement.items()}


def open_trades_of(open_trades: list[dict], ticker: str) -> list[dict]:
    return [row for row in open_trades if row["ticker"] == ticker]


def tickers(ctx: BuildContext) -> list[str]:
    """The collected companies (active and inactive), sorted."""
    return sorted(ctx.collected)


def market_blocks(ctx: BuildContext, strategy_fields: tuple[str, ...]) -> dict:
    """The blocks every company page of the market repeats."""
    return {**rm_common.header(ctx), "status": rm_common.status_block(ctx), **rm_common.horizons(ctx),
            "go_live": rm_common.go_live(ctx), "strategies": rm_common.strategies(ctx, strategy_fields)}


def company_news_items(ctx: BuildContext, ticker: str) -> list[dict]:
    """B11's news items about the company first seen in the NEWS_DAYS before the cut-off, status as of the company,
    the newest NEWS_MAX."""
    since = ctx.cutoff_time - timedelta(days=NEWS_DAYS)
    return company_news(news_items(ctx.cfg, ctx.con, ctx.cutoff_time, tickers=[ticker], since=since,
                                   status_ticker=ticker))[:NEWS_MAX]


def market_calendar(ctx: BuildContext) -> list[dict]:
    """B11's calendar of the market and every collected company, from the session being predicted."""

    def compute() -> list[dict]:
        first = date.fromisoformat(rm_common.status_block(ctx)["session"]["session_date"])
        return calendar_events(ctx.cfg, ctx.con, ctx.cutoff_time, first, first + timedelta(days=EVENT_DAYS))

    return ctx.shared("company_calendar", compute)


def company_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.stock: the 03 page of every collected company."""
    data, blocks = sources(ctx), company_blocks(ctx)
    companies = blocks["companies"]
    shared = {**market_blocks(ctx, STRATEGY_FIELDS), "reference_strategy": REFERENCE_STRATEGY,
              "companies": [pick(companies[ticker], COMPANY_FIELDS) for ticker in tickers(ctx)]}
    events = market_calendar(ctx)
    return {ticker: stock_payload(data, ticker, shared, {
        "company": pick(companies[ticker], COMPANY_FIELDS),
        "agreement": agreement_of(blocks["agreement"], ticker),
        "open_trades": open_trades_of(blocks["open_trades"], ticker),
        "news": company_news_items(ctx, ticker),
        "events": events,
    }) for ticker in tickers(ctx)}


def bars_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.bars: the bars of every collected company."""
    data = sources(ctx)
    return {ticker: bars_payload(data, ticker) for ticker in tickers(ctx)}


def sessions_back(cfg: dict, last_day: str | None, count: int) -> list[str]:
    """The `count` market sessions ending at `last_day` (included when a session), oldest first; [] without a day."""
    if last_day is None:
        return []
    days, day = [], calendar.prev_session(cfg, date.fromisoformat(last_day))
    for _ in range(count):
        days.append(day.isoformat())
        day = calendar.prev_session(cfg, day, include=False)
    return days[::-1]


def first_of(days: list[str]) -> str | None:
    return days[0] if days else None


def trades_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.trades: the market's page (settled trades of the last TRADES_MARKET_SESSIONS sessions to the as-of date)
    and one page per collected company (the last TRADES_TICKER_SESSIONS). Without an as-of date (nothing stored yet)
    no window applies."""
    data, open_trades = sources(ctx), company_blocks(ctx)["open_trades"]
    market_from = first_of(sessions_back(ctx.cfg, data.as_of, TRADES_MARKET_SESSIONS))
    ticker_from = first_of(sessions_back(ctx.cfg, data.as_of, TRADES_TICKER_SESSIONS))
    pages = {ticker: trades_payload(data, ticker, open_trades_of(open_trades, ticker), ticker_from)
             for ticker in tickers(ctx)}
    return {MARKET_PAGE_KEY: market_trades_payload(data, open_trades, market_from), **pages}


def lifecycle_key(ticker: str, day: str) -> str:
    return f"{ticker}:{day}"


def lifecycle_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.lifecycle: one page per collected company and session D (the path of the predictions made for D), the last
    LIFECYCLE_SESSIONS sessions ending at the session being predicted (an older day has no page: the route answers
    404). The rm.trades windows end at the as-of date instead: they count exit sessions, which are never after it."""
    data = sources(ctx)
    days = sessions_back(ctx.cfg, rm_common.status_block(ctx)["session"]["session_date"], LIFECYCLE_SESSIONS)
    return {lifecycle_key(ticker, day): lifecycle_payload(data, ticker, day) for ticker in tickers(ctx) for day in days}


def trade_checks(ctx: BuildContext) -> list[dict]:
    """The full rows (every column of view trade_check_rows, times as ISO UTC Z) of the market's latest intraday
    trade check at or before the cut-off, collected companies only, by ticker then trade id: for the market pages
    (B11), which pick their fields. Copies, so a caller may change them."""
    rows = sorted(sources(ctx).market_checks, key=lambda row: (row["ticker"], row["trade_id"]))
    return [dict(row) for row in rows]


def market_trade_checks(ctx: BuildContext) -> list[dict]:
    """The same rows with the catalogue trade-check fields of rm.trades `_` (schema TradeCheck), for B13's
    portfolio page."""
    return check_rows(sources(ctx).market_checks)


def stock_strategies_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.stock_strategies: the 04 page of every collected company."""
    data, blocks = sources(ctx), company_blocks(ctx)
    shared = market_blocks(ctx, STRATEGIES_STRATEGY_FIELDS)
    return {ticker: stock_strategies_payload(data, ticker, shared, {
        "company": pick(blocks["companies"][ticker], STRATEGIES_COMPANY_FIELDS),
        "agreement": agreement_of(blocks["agreement"], ticker),
    }) for ticker in tickers(ctx)}


def company_mockup(mockup: dict, market: str, page_key: str) -> dict:
    """The 03 mockup's payload of a page: the market's shared keys and the company's page (the market's default
    company for a company the mockup does not hold)."""
    held = mockup["markets"][market]
    page = held["pages"].get(page_key) or held["pages"][held["default_ticker"]]
    shared = {key: value for key, value in held.items() if key not in ("pages", "default_ticker")}
    # a news item's shape is the market's example items together: W1's invented items predate
    # enrichment.geopolitical (design/mockups/09-news/notes.md), so one company's example may lack it
    news = [item for example in held["pages"].values() for item in example["news"]]
    return {**shared, **page, "news": news}


def strategies_mockup(mockup: dict, market: str, _page_key: str) -> dict:
    """The 04 mockup's payload (one example company per market)."""
    return mockup["markets"][market]


def trades_mockup(mockup: dict, market: str, page_key: str) -> dict:
    """rm.trades has no mockup of its own: its lists are the 03 mockup's (a company page's) and its header."""
    page = company_mockup(mockup, market, page_key)
    keys = ("market", "as_of", "open_trades", "trade_checks", "settled") + (() if page_key == MARKET_PAGE_KEY else
                                                                            ("ticker", "reasons"))
    return {key: page[key] for key in keys}


def lifecycle_mockup(mockup: dict, market: str, page_key: str) -> dict:
    """rm.lifecycle has no mockup of its own: its lists are the 03 mockup page's (same records and fields) under one
    day's header."""
    page = company_mockup(mockup, market, page_key.split(":")[0])
    day = page["status"]["session"]["session_date"]
    return {"market": page["market"], "ticker": page["ticker"], "session_date": day,
            **{key: page[key] for key in ("predictions", "head_to_head", "trade_checks", "settled", "reasons")}}


def bars_mockup(mockup: dict, market: str, page_key: str) -> dict:
    page = company_mockup(mockup, market, page_key)
    return {key: page[key] for key in ("market", "ticker", "as_of", "bars")}


BUILDERS = (
    PageBuilder(RM_STOCK, "CompanyPage", company_pages, owner=OWNER),
    PageBuilder(RM_BARS, "CompanyBars", bars_pages, owner=OWNER, serve=SERVE_VERBATIM),
    PageBuilder(RM_TRADES, "TradesPage", trades_pages, owner=OWNER, serve=SERVE_VERBATIM),
    PageBuilder(RM_STOCK_STRATEGIES, "StockStrategiesPage", stock_strategies_pages, owner=OWNER),
    PageBuilder(RM_LIFECYCLE, "LifecyclePage", lifecycle_pages, owner=OWNER, serve=SERVE_VERBATIM),
)
CONTRACT_CASES = (
    ContractCase(path="/api/v1/markets/{market}/stocks/{ticker}", table=RM_STOCK, mockup=MOCKUP_COMPANY,
                 mockup_payload=company_mockup, map_paths=("$.strategies", "$.agreement")),
    ContractCase(path="/api/v1/markets/{market}/stocks/{ticker}/bars", table=RM_BARS, mockup=MOCKUP_COMPANY,
                 mockup_payload=bars_mockup),
    ContractCase(path="/api/v1/markets/{market}/trades", table=RM_TRADES, mockup=MOCKUP_COMPANY,
                 mockup_payload=trades_mockup),
    ContractCase(path="/api/v1/markets/{market}/stocks/{ticker}/strategies", table=RM_STOCK_STRATEGIES,
                 mockup=MOCKUP_STOCK_STRATEGIES, mockup_payload=strategies_mockup,
                 map_paths=("$.strategies", "$.agreement")),
    ContractCase(path="/api/v1/markets/{market}/stocks/{ticker}/lifecycle/{date}", table=RM_LIFECYCLE,
                 mockup=MOCKUP_COMPANY, mockup_payload=lifecycle_mockup),
)
