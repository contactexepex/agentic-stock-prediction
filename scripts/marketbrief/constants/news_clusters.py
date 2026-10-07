"""Constants of news clustering (news verification phase A): settings defaults, flags, labels and SQL."""
from marketbrief.constants.articles import ACCESS_FULL, ACCESS_PARTIAL, ACCESS_PAYWALLED

STEP_NEWS_CLUSTERS = "news_clusters"
METHOD_VERSION_CLUSTERS = "nv-a1"
READ_ACCESS = (ACCESS_FULL, ACCESS_PARTIAL, ACCESS_PAYWALLED)
GOOGLE_NEWS_HOST = "news.google.com"

# defaults of the `clusters:` settings in config/news_sources.yaml
DEFAULT_LOOKBACK_HOURS = 144
DEFAULT_WINDOW_HOURS = 72
DEFAULT_TITLE_JACCARD = 0.5
DEFAULT_TITLE_MIN_SHARED = 2
DEFAULT_COPY_CONTAINMENT = 0.5
DEFAULT_MIN_SHINGLES = 30
MAX_EXAMPLES = 3
MAX_UNVETTED_DOMAINS = 40
MAX_SIZE_BUCKET = 10
STATE_HASH_LENGTH = 16

LABEL_WIRE, LABEL_PROVIDER, LABEL_OUTLET = "wire:", "provider:", "outlet:"
FLAG_PROMOTIONAL = "promotional_provider"
FLAG_SOURCES_SAY = "sources_say"
FLAG_SINGLE_SOURCE = "single_source"
FLAG_NO_VETTED_ORIGIN = "no_vetted_origin"
FLAG_ORIGINS_UNVERIFIED = "origins_unverified"
FLAG_OPINION = "opinion"
FLAG_LOW_TIER_ONLY = "low_tier_only"
FLAG_UNREAD = "unread"
FLAG_DUPLICATES_REMOVED = "duplicates_removed"
STATE_HASH_KEYS = ("news_ids", "duplicate_ids", "primary_ids", "origins", "origin_groups", "independent_origins",
                   "unread_vetted_origins", "unvetted_ids", "flags", "outlets")

NEWS_ROWS_SQL = ("SELECT id, title, url, source, source_domain, published_at, first_seen_at, primary_tickers "
                 "FROM news WHERE first_seen_at <= ? AND first_seen_at >= ? ORDER BY first_seen_at, id")
ARTICLES_SQL = "SELECT * FROM news_articles_asof(?::TIMESTAMPTZ) ORDER BY id"   # with a duplicate's article
FILINGS_SQL = ("SELECT id, ticker, coalesce(accepted_at, CAST(filing_date AS TIMESTAMPTZ) + INTERVAL 1 DAY) AS t "
               "FROM filings WHERE list_contains(?, form) ORDER BY t, id")
ANNOUNCEMENTS_SQL = ("SELECT id, ticker, published_at FROM announcements "
                     "WHERE published_at IS NOT NULL ORDER BY published_at, id")
STORED_CLUSTERS_SQL = ("SELECT DISTINCT ON (cluster_id) cluster_id, state_hash FROM news_clusters "
                       "WHERE as_of <= ? ORDER BY cluster_id, as_of DESC")
