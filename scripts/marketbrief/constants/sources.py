"""Hosts, URLs, user agents, timeouts and retry settings of the data-source clients."""
from zoneinfo import ZoneInfo

FREE_SOURCE_USER_AGENT = "Mozilla/5.0 (compatible; market-brief/1.0; personal research, low volume)"
NSE_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36")
RSS_USER_AGENT = "market-brief/1.0 (personal research; RSS reader)"

ACCEPT_ANY = "*/*"
ACCEPT_LANGUAGE_US = "en-US,en;q=0.9"
ACCEPT_LANGUAGE_NSE = "en-US,en;q=0.9,en-IN;q=0.8"
ACCEPT_ENCODING_IDENTITY = "identity"

FREE_SOURCE_PAUSE_SECONDS = 1.0
FREE_SOURCE_TIMEOUT_SECONDS = 45
FREE_SOURCE_ATTEMPTS = 3
FREE_SOURCE_BACKOFF_SECONDS = 3.0

NSE_TIMEOUT_SECONDS = 30
NSE_ATTEMPTS = 2
NSE_RETRY_WAIT_SECONDS = 2
NSE_DEFAULT_PAUSE_SECONDS = 0.7
NSE_BASE_URL = "https://www.nseindia.com"
NSE_ARCHIVES_URL = "https://nsearchives.nseindia.com"
NSE_ARCHIVES_HOST = "nsearchives.nseindia.com"

SEC_MIN_INTERVAL_SECONDS = 0.15   # <= ~7 requests/s, under SEC's 10/s limit
SEC_TIMEOUT_SECONDS = 60
SEC_ATTEMPTS = 3
SEC_RETRY_STATUSES = (429, 500, 502, 503)
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

NEO4J_TIMEOUT_SECONDS = 60
NEO4J_RETRIES = 2
NEO4J_DEFAULT_BACKOFF_SECONDS = 2.0
NEO4J_RETRY_STATUSES = (429, 500, 502, 503, 504)

SLACK_TIMEOUT_SECONDS = 60

ACCEPT_HTML_PAGES = "text/html,application/xhtml+xml"
ARTICLE_DEFAULT_USER_AGENT = "market-brief/1.0"
NSE_REFERER_PAGES = {  # Referer per API: NSE checks that the call comes from its own page
    "corporates-pit-gg": "/companies-listing/corporate-filings-insider-trading",
    "bulk-block-short-deals": "/report-detail/display-bulk-and-block-deals",
    "snapshot-capital-market-largedeal": "/market-data/large-deals",
    "corporate-share-holdings-master": "/companies-listing/corporate-filings-shareholding-pattern",
    "corporate-pledgedata": "/companies-listing/corporate-filings-pledged-data",
    "corporate-announcements": "/companies-listing/corporate-filings-announcements",
    "integrated-filing-results": "/companies-listing/corporate-integrated-filing",
    "corporates-financial-results": "/companies-listing/corporate-filings-financial-results",
    "fiidiiTradeReact": "/reports/fii-dii",
}

PROXY_TUNNEL_FAILURE = "Tunnel connection failed"
CONNECTION_CLOSED_MARKERS = ("RemoteDisconnected", "closed connection", "Connection reset", "EOF occurred",
                             "UNEXPECTED_EOF")

NSE_DATE_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%B-%Y",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")
NSE_MISSING_VALUES = (None, "", "-", "Nil", "NA")
NSE_YAHOO_SUFFIX = ".NS"
TIMEZONE_IST = ZoneInfo("Asia/Kolkata")
