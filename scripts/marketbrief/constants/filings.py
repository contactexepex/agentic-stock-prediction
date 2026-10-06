"""Constants and messages of the SEC collectors (filings, acceptance-time checks)."""
COLLECTOR_FILINGS = "filings"
# SEC renamed beneficial-ownership forms "SCHEDULE 13D/13G" (structured XML) in Dec 2024; keep both.
DEFAULT_FILING_FORMS = ["8-K", "10-Q", "10-K", "6-K", "20-F", "4", "SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G"]
DEFAULT_LOOKBACK_DAYS = 7
SEEN_LOOKBACK_DAYS = 60
ERROR_TEXT_LIMIT = 200
MSG_TICKER_MAP_FILE = "company_tickers.json"
MSG_SKIPPED_NOT_SEC = "no SEC filings for this market"
