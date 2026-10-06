"""Constants and messages of the options collector (yfinance option-chain implied volatility)."""
COLLECTOR_OPTIONS = "options"
SOURCE_YFINANCE = "yfinance"
MIN_IV, MAX_IV = 0.01, 5.0
MIN_QUOTED_STRIKES = 2
DEFAULT_EXPIRIES = 4
DEFAULT_MAX_DAYS = 45
SEEN_LOOKBACK_DAYS = 2
SNAPSHOT_DECIMALS = 6
ERROR_TEXT_LIMIT = 200
OPTION_COLUMNS = ["strike", "impliedVolatility", "bid", "ask", "lastPrice"]

MSG_NO_EXPIRIES = "no option expiries returned"
MSG_NO_EXPIRY_IN_WINDOW = "no expiry within 1-{max_days} days"
MSG_NO_USABLE_CHAIN = "no usable chain (no quote with a plausible implied vol)"
MSG_SKIPPED_NO_CHAINS = "no free option chains for this market"
