"""Constants and messages of the daily indicator snapshot (features and regime rows)."""
STEP_FEATURES = "features"
QUALITY_ORDER = ("OK", "PARTIAL", "BLOCKED")
SECTOR_PEER_RETURN = "ret_5d"
EX_DIVIDEND_WINDOW_DAYS = 10
UPCOMING_EVENT_DAYS = 14
VOL_DECIMALS = 4
VOL_CHANGE_DECIMALS = 6
MSG_NO_BENCHMARK = "no benchmark bars for {key}; run collect_prices.py first"
MSG_NO_PRICE_DATA = "no price data"
MSG_STALE_BAR = "stale: last bar {day}"
MSG_CALENDAR_NOT_COVERED = "exchange calendar does not cover {session}: assuming Mon-Fri sessions"
