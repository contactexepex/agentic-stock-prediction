"""Constants and messages of article reading (news verification phase A): access outcomes, tiers, extractors."""
METHOD_VERSION_ARTICLES = "nv-a1"

ACCESS_FULL = "full"
ACCESS_PARTIAL = "partial"
ACCESS_PAYWALLED = "paywalled"
ACCESS_BLOCKED = "blocked"
ACCESS_UNDECODED = "undecoded"
ACCESS_SKIPPED_UNLISTED = "skipped_unlisted"
ACCESS = (ACCESS_FULL, ACCESS_PARTIAL, ACCESS_PAYWALLED, ACCESS_BLOCKED, ACCESS_UNDECODED, ACCESS_SKIPPED_UNLISTED)

TIER_PRIMARY, TIER_1, TIER_2, TIER_UNLISTED = "primary", "tier1", "tier2", "unlisted"
TIER_RANK = {TIER_PRIMARY: 0, TIER_1: 1, TIER_2: 2, TIER_UNLISTED: 3}

NUM_PERM = 128            # MinHash permutations
LEDE_SENTENCES = 3        # an attribution phrase counts as the origin only in this many first sentences
SHINGLE = 6               # words per shingle
KEY_SENTENCES = 3
KEY_SENTENCE_WORDS = 40
MIN_SENTENCE_WORDS = 6
MAX_NUMBERS = 30
HEX_DIGITS_PER_HASH = 8
MINHASH_SEED = 1

EXTRACTOR_JSONLD, EXTRACTOR_TRAFILATURA, EXTRACTOR_NEWSPAPER = "jsonld", "trafilatura", "newspaper"
EXTRACTOR_DESCRIPTION = "description"
DEFAULT_EXTRACT_ORDER = [EXTRACTOR_JSONLD, EXTRACTOR_TRAFILATURA, EXTRACTOR_NEWSPAPER]
DEFAULT_MIN_CHARS = 400
DEFAULT_FULL_CHARS = 800
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 4_000_000
READ_CHUNK_BYTES = 65536
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
GOOGLE_HOST = "news.google.com"
SOURCE_LABEL_PATTERN = r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
HTTPS = "https"
HTTPS_PORT = 443

MSG_UNPARSABLE_HTML = "unparsable HTML"
MSG_URL_MISSING = "no url"
MSG_URL_NOT_HTTPS = "not https ({scheme})"
MSG_URL_NO_SCHEME = "no scheme"
MSG_URL_PORT = "non-standard port {port}"
MSG_URL_NOT_LISTED = "host {host} not on the allowlist"
MSG_URL_NOT_FETCHED = "{domain} not fetched: {why}"
MSG_URL_FETCH_FALSE = "fetch: false"
MSG_URL_OK = "ok"
MSG_REDIRECT_NO_LOCATION = "redirect without location"
MSG_HTTP_STATUS = "HTTP {status}"
MSG_NOT_HTML = "not HTML ({content_type})"
MSG_TOO_MANY_REDIRECTS = "too many redirects"
MSG_FETCH_ERROR = "{kind}: {error_type}: {detail}"
FETCH_ERROR_TLS, FETCH_ERROR_NETWORK = "tls", "network"
FETCH_ERROR_TEXT_LIMIT = 160
CONTENT_TYPE_TEXT_LIMIT = 40

# ---------- article extraction ----------
MSG_MESSAGE = "{name}: {name_2}"
