"""Names and settings of the market pages' read models (B11: Home, Watchlist, News, Companies; docs/ws/b11.md).
Each setting names its source (the page's design/mockups/<page>/notes.md or the catalogue)."""

from __future__ import annotations

RM_HOME = "home"
RM_NEWS = "news"
RM_COMPANIES = "companies"
# the News page's window (design/mockups/09-news/notes.md: 3 days before the cut-off, at most 50 items)
NEWS_WINDOW_DAYS = 3
NEWS_MAX_ITEMS = 50
# market-wide feeds carry off-topic items; the analyst's relevance filters them (W1's catalogue build, request 8)
NEWS_MIN_MARKET_RELEVANCE = 0.4
# Home's news card: the same window as the News page (design/mockups/01-home/notes.md)
HOME_NEWS_WINDOW_DAYS = NEWS_WINDOW_DAYS
# the News page's calendar: the session being predicted to 7 days after it
NEWS_CALENDAR_DAYS = 7
SCOPE_COMPANY = "company"
SCOPE_MARKET = "market"
SUMMARY_ARTICLE = "article"
SUMMARY_ANALYST = "analyst"
SUMMARY_NONE = "none"
ORIGIN_STORED = "stored"
READABLE_ACCESS = ("full", "partial")
TEMPLATED_SUMMARY_MARK = " item on "  # the analyst's templated "<Type> item on <TICKER>: <title>" form
MATERIALITY_HIGH = "high"
EVENT_EARNINGS = "earnings"
HEADLINE_HISTORY_STATUS = "exists (kind news_updates)"
# calendar rows
CALENDAR_SOURCE_CONFIG = "config/events.yaml"
CALENDAR_SOURCE_MARKET = "market calendar"
CALENDAR_TYPE_HOLIDAY = "holiday"
WIDENS_MARKET = "market"
WIDENS_COMPANY = "company"
EXCHANGE_CLOSED_NAME = {"india": "NSE", "us": "US exchanges"}
COMPANY_EVENT_LABEL = {"earnings": "results", "ex_dividend": "ex-dividend"}
# the Companies page's commands (design/mockups/10-companies/notes.md); masking a deleted company (decision 12)
COMPANY_COMMAND_TOOLS = ("add_company", "deactivate_company", "reactivate_company", "set_paper_amount",
                         "delete_company")
MASKED = "(masked)"
MASKED_COMPANY = "(deleted company)"
MASKED_MESSAGE = "(this company was deleted later; its records are excluded on read)"
