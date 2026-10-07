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
