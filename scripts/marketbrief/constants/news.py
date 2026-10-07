"""Constants of the news collector (RSS headlines)."""
COLLECTOR_NEWS = "news"
FEED_PREFIX_GNEWS = "gnews:"
DEFAULT_QUERY_TEMPLATE = '"{name}" stock'
DEFAULT_WINDOW = "1d"             # Google News `when:` of a first run (no stored run) and the window's floor
DEFAULT_CATEGORY = "general"
MAX_AGE_DAYS = 3                  # older items are skipped (floor; the catch-up window can widen it); an outlet
                                  # feed with nothing newer is `stale`
SEEN_LOOKBACK_DAYS = 9            # daily files read for de-duplication: the 7-day cap plus 2 days
SOCKET_TIMEOUT_SECONDS = 20
FETCH_ATTEMPTS = 2                # one retry: Google News occasionally fails a single query
RETRY_PAUSE_SECONDS = 2
PERMANENT_STATUSES = (401, 403, 404)
TITLE_SEPARATOR = " - "

# Catch-up window (marketbrief/collectors/news_window.py; docs/DESIGN.md section 3, "News timing"): the
# span since the last successful run plus a margin, never below the defaults above, at most WINDOW_CAP_HOURS.
WINDOW_MARGIN_HOURS = 1
WINDOW_CAP_HOURS = 7 * 24
HOURS_PER_DAY = 24
RUN_OK_MAX_FAILED_SHARE = 0.5     # a run is successful when at most this share of its Google News queries failed
WINDOW_REASON_FIRST_RUN = "first_run"           # no stored run and no stored news: the defaults
WINDOW_REASON_SINCE_RUN = "since_last_run"      # the newest successful news_runs row
WINDOW_REASON_SINCE_NEWS = "since_last_news"    # no news_runs row yet: the newest stored first_seen_at
WINDOW_REASON_NO_RECENT_SUCCESS = "no_recent_success"   # news_runs rows, none successful: the cap
MSG_BAD_WINDOW = "news.google_news.window must look like 1d or 12h, not {value!r}"
# Google News RSS answers at most 100 items per query (checked 2026-10-07): a query that fills it over a
# window longer than a day is asked again per day (`after:D before:D+1`, Pacific-time days).
GOOGLE_NEWS_ITEM_CAP = 100
MAX_SLICE_QUERIES_PER_RUN = 200

# De-duplication (owner decisions Q45-Q47, 2026-10-07; marketbrief/analytics/news_dedup.py; docs/DESIGN.md
# section 3, "News de-duplication"): one article is stored once per market; a later headline at the same link is
# a news_updates row. A match counts within DEDUP_WINDOW_DAYS of the matched item's newest stored row: items are
# kept only when published within the catch-up cap (7 days), so a repeat sighting comes at most 7 days after the
# first; 2 days of margin. The collector reads DEDUP_LOOKBACK_FILES daily files (one per UTC day: today and the
# 9 days before), which cover those 9 days back from any time of today.
DEDUP_WINDOW_DAYS = 9
DEDUP_LOOKBACK_FILES = DEDUP_WINDOW_DAYS + 1
OUTLET_HOST_PREFIXES = ("www.", "m.", "amp.", "mobile.")   # stripped from hosts: the same outlet
OUTLET_LABEL_PREFIX = "label:"   # outlet key of a row with neither a host nor a configured or host-like label
TRACKING_PARAMETER = r"^(?:utm_[a-z_]+|fbclid|gclid|ocid|cmpid)$"   # dropped from publisher links
GOOGLE_NEWS_HOST = "news.google.com"   # its article links carry no meaningful query (?oc=5)
MATCH_LINK = "link"     # same canonical article link, same outlet: the same article, maybe an edited headline
MATCH_TITLE = "title"   # same normalised title from the same outlet
NEWS_ID_MAP_TABLE = "news_id_map"   # every stored news id -> its canonical id (core.database.connect)
