"""Constants and messages of the quotes collector (overnight and pre-open cues)."""
COLLECTOR_QUOTES = "quotes"
QUOTE_ROLES = ("benchmark", "vol_index", "cue", "factor")
ADR_KEY_SUFFIX = ":ADR"
INTRADAY_PERIOD = "5d"
INTRADAY_INTERVAL = "5m"
DAILY_PERIOD = "1mo"
YAHOO_CLOSE_COLUMN = "Close"
QUOTE_TEXT_LIMIT = 200

MSG_NO_DATA = "no data"
MSG_NO_PREVIOUS_CLOSE = "no previous close"
MSG_STALE_QUOTE = "stale: last quote {last}"
