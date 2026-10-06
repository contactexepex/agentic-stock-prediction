"""Constants of the news collector (RSS headlines)."""
COLLECTOR_NEWS = "news"
FEED_PREFIX_GNEWS = "gnews:"
DEFAULT_QUERY_TEMPLATE = '"{name}" stock'
DEFAULT_WINDOW = "1d"
DEFAULT_CATEGORY = "general"
MAX_AGE_DAYS = 3                  # older items are skipped; an outlet feed with nothing newer is `stale`
SEEN_LOOKBACK_DAYS = 7
SOCKET_TIMEOUT_SECONDS = 20
FETCH_ATTEMPTS = 2                # one retry: Google News occasionally fails a single query
RETRY_PAUSE_SECONDS = 2
PERMANENT_STATUSES = (401, 403, 404)
TITLE_SEPARATOR = " - "
