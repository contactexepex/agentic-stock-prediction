"""Constants of the news analyst's input window (marketbrief/pipeline/news_pending.py)."""
STEP_NEWS_PENDING = "news_pending"
PENDING_FILE = "work/news_pending.jsonl"
PENDING_MAX_DAYS = 7              # the window reaches back at most this far (the news catch-up cap)
ITEM_KIND_NEWS = "news"
ITEM_KIND_ANNOUNCEMENT = "announcement"
NEWS_COLUMNS = (
    "id", "title", "source", "url", "published_at", "first_seen_at", "feed", "category",
    "tickers", "primary_tickers", "tag_confidence",
)
ANNOUNCEMENT_COLUMNS = ("id", "ticker", "company", "category", "subject", "url", "published_at", "first_seen_at")
# Issue #46: each pending item carries a priority; watchlist items (a watchlist ticker tag, or an NSE announcement)
# come first and are scored one by one, background items (no watchlist tag) may be scored in groups
PRIORITY_WATCHLIST = "watchlist"
PRIORITY_BACKGROUND = "background"
MSG_TEMPLATED_SUMMARIES = (
    "{shared} of {records} watchlist records share their summary with another record (more than {limit:.0%}): "
    "a keyword-rule pass, not a reading of each headline (issue #46); e.g. {example!r}"
)
