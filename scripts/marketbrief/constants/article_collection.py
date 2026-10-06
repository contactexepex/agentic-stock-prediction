"""Constants and messages of the articles collector (reads the article behind material headlines)."""
COLLECTOR_ARTICLES = "articles"
GOOGLE_DOMAIN = "google.com"
DECODER_NAME = "googlenewsdecoder"
TZ_ABBREVIATIONS = {"EDT": -4 * 3600, "EST": -5 * 3600, "CDT": -5 * 3600, "CST": -6 * 3600, "MDT": -6 * 3600,
                    "MST": -7 * 3600, "PDT": -7 * 3600, "PST": -8 * 3600, "IST": 5 * 3600 + 1800, "GMT": 0, "UTC": 0}
CONFIDENCE_RANK = {"high": 2, "low": 1}
DEFAULT_MIN_CONFIDENCE = "high"
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_MAX_AGE_HOURS = 48
DEFAULT_MIN_PRIORITY = 1
DEFAULT_PAUSE_SECONDS = 1.5
DEFAULT_MAX_PER_RUN = 80
DEFAULT_MAX_SECONDS = 900
DEFAULT_DECODE_BATCH = 10
DEFAULT_TIMEOUT_SECONDS = 20
DECODER_ERROR_LIMIT = 160
NOTE_LIMIT = 160
EXTRACTION_ERROR_LIMIT = 120
UNVETTED_LIMIT = 40
UNDECODED_WARNING_SHARE = 0.5
BYLINE_LIMIT = 120
PROVIDER_LIMIT = 80
DATE_VALUE_LIMIT = 30

MSG_OUTLET_NOT_LISTED = "outlet {outlet!r} not on the allowlist (not requested)"
MSG_NOT_REQUESTED = "not requested: {why}"
MSG_SAME_ARTICLE_TITLE = "same article as {first_id} (same title and outlet, not requested again)"
MSG_SAME_ARTICLE_URL = "same article as {first_id} (same URL, not requested again)"
MSG_NOT_DECODED = "not decoded"
MSG_LINK_NOT_RESOLVED = "Google News link not resolved: {message}"
MSG_EXTRACTION_FAILED = "extraction failed: {error_type}: {detail}"
MSG_STOPPED_AFTER = "stopped after {seconds:.0f}s; {left} items left for the next run"
MSG_LINKS_NOT_DECODED = "{count} of {tried} Google News links not decoded"
MSG_DATE_NOT_STORED = "{field} {value!r} not stored (no zone or after fetch)"
MSG_DECODER_REQUEST_REFUSED = "decoder request to {scheme}://{host} refused (not Google over HTTPS)"
NOTE_DECODE_REQUESTS = "decode = one GET per Google News link + one POST per batch"
