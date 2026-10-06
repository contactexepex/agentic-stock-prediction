"""Constants and messages of the prices collector (Yahoo bars, NSE bhavcopy fallback, split detection)."""
from marketbrief.constants.columns import (COL_ADJ_CLOSE, COL_CLOSE, COL_COLLECTED_AT, COL_DATE, COL_HIGH, COL_LOW,
                                           COL_OPEN, COL_TICKER, COL_VOLUME)

PRICE_FILE_COLUMNS = [COL_DATE, COL_TICKER, COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE, COL_ADJ_CLOSE, COL_VOLUME,
                      COL_COLLECTED_AT]
OWN_EXCHANGE_ROLES = ("benchmark", "vol_index", "sector_etf")   # roles that follow the market's calendar
COLLECTOR_PRICES = "prices"

YAHOO_OPEN, YAHOO_HIGH, YAHOO_LOW, YAHOO_CLOSE = "Open", "High", "Low", "Close"
YAHOO_ADJ_CLOSE, YAHOO_VOLUME, YAHOO_SPLITS = "Adj Close", "Volume", "Stock Splits"
YAHOO_OHLC = [YAHOO_OPEN, YAHOO_HIGH, YAHOO_LOW, YAHOO_CLOSE]
YAHOO_INTERVAL_DAILY = "1d"
DEFAULT_PERIOD = "1mo"
PRICE_DECIMALS = 4
GAP_REFETCH_DAYS = 14        # a gap in the stored bars: fetch from this many days before the newest stored bar

STORED_LOOKBACK_DAYS = 400   # how far back newest_stored_before searches the prices files
MIN_OVERLAP = 3              # stored bars Yahoo's frame must cover for the basis check
PREV_CLOSE_TOLERANCE = 0.005  # bhavcopy PREV_CLOSE vs our stored close of the previous session
NEWEST_LOOKBACK = 40         # sessions searched back for a stock's newest stored bar
DEFAULT_FALLBACK_SESSIONS = 5
STEP_RATIO_LOW, STEP_RATIO_HIGH = 0.8, 1.25   # a price step is "the split factor" within these multiples
NSE_SCAN = 5        # frame sessions after the newest re-based stored bar searched for the ex-date
CHAIN_TOLERANCE = 0.001   # NSE PREV_CLOSE vs Yahoo's close of the same session (they agree to ~0.0002)
WEAK_FACTOR = 0.9   # from here to 1 a factor is within a normal day's move: the step alone proves nothing
# (the threshold is a judgement: a daily move of 10% or more is rare for a watchlist stock; issue #36 item 3)

SOURCE_NSE_BHAVCOPY = "nse_bhavcopy"
SOURCE_YAHOO_SPLITS = "yahoo_splits"
SOURCE_NSE_PREV_CLOSE = "nse_prev_close"
BHAVCOPY_PATH = "/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"
BHAVCOPY_SERIES = "EQ"
NSE_ARCHIVES_FULL_URL = "https://nsearchives.nseindia.com{path}"
BHAVCOPY_COLUMNS = {"day": "DATE1", "symbol": "SYMBOL", "series": "SERIES", "open": "OPEN_PRICE",
                    "high": "HIGH_PRICE", "low": "LOW_PRICE", "close": "CLOSE_PRICE", "volume": "TTL_TRD_QNTY",
                    "prev_close": "PREV_CLOSE"}

SUMMARY_SYMBOLS = "symbols"
SUMMARY_NEW_BARS = "new_bars"
SUMMARY_ADJUSTMENTS = "adjustments"
SUMMARY_REBASED = "rebased_bars"
SUMMARY_HELD = "held"
SUMMARY_FILLED_FROM_NSE = "filled_from_nse"
SUMMARY_RESOLVED_BY_NSE = "resolved_by_nse"
SUMMARY_NSE_NOTES = "nse_notes"

ENTRY_YAHOO = "yahoo"
ENTRY_ERROR = "error"
ENTRY_MISSING_AFTER_NSE = "missing_after_nse"
ENTRY_NEWEST_STORED_BAR = "newest_stored_bar"
ENTRY_SESSIONS_BEHIND = "sessions_behind"
ENTRY_BEYOND_NSE_WINDOW = "beyond_nse_window"
ENTRY_FILLED_DATES = "filled_dates"

ERROR_NO_DATA = "no data"
ERROR_NO_COMPLETED_BAR = "no completed bar"
ERROR_STALE_PREFIX = "stale"
ERROR_TEXT_LIMIT = 200
WARNING_TEXT_LIMIT = 160

MSG_STALE = "stale: newest bar {newest}, expected {expected} or later"
MSG_HELD_NOTE = "price basis unconfirmed (split/bonus?): new bars held, see warnings"
MSG_HELD_BY_YAHOO_FRAME = "price basis unconfirmed (split/bonus?); held, see warnings"
MSG_NO_NEWEST_STORED = "none in the last {sessions} sessions"
MSG_BEYOND_WINDOW = "the fallback checks only sessions from {start}"
MSG_MISSING_AFTER_FALLBACK = "missing sessions after NSE fallback"
MSG_FALLBACK_ERROR = "nse fallback error: {error}"
MSG_LONGER_HISTORY_FAILED = "{key}: longer Yahoo history for the basis check failed: {error}"
MSG_SPLIT_CHECK_FAILED = "{key}: split/bonus check failed: {error}"

MSG_BHAVCOPY_WRONG_DAY = "bhavcopy for {day} holds {held}; not used"
MSG_BHAVCOPY_NO_DATED_ROWS = "no dated rows"
MSG_BHAVCOPY_PROBLEM = "nse {problem}"
MSG_BHAVCOPY_FETCH_FAILED = "nse bhavcopy {day}: {error}"
MSG_NO_EQ_ROW = "no EQ row for {ticker} in the bhavcopy"
MSG_NOT_FILLED = "nse {day} {ticker}: {reason}; not filled"
MSG_SPLIT_AFTER_PREVIOUS = "Yahoo reports a split/bonus on {day}; price basis may differ"
MSG_NO_STORED_CLOSE = "no stored close for the previous session {previous} to check the price basis"
MSG_NO_PREV_CLOSE = "bhavcopy has no PREV_CLOSE to check the price basis against {previous}"
MSG_BASIS_MISMATCH = ("price basis mismatch: bhavcopy PREV_CLOSE {nse_previous:g} vs stored close {stored:g} on "
                      "{previous} ({gap:+.1%}); split, bonus or other corporate action")

MSG_NO_STORED_IN_FRAME = ("{key}: no stored bar in Yahoo's frame to check the price basis; its first close "
                          "({first}) is {ratio:.4f}x our newest stored close ({stored_day}): not verifiable, "
                          "new bars held")
MSG_NO_WINDOW_FOR_SPLIT = ("{key}: Yahoo reports a split/bonus on {day} (ratio {ratio:g}) but no stored bar in the "
                           "fetched window before it to check the stored basis; not recorded, new bars held")
MSG_SPLIT_NOT_REBASED = ("{key}: Yahoo reports a split/bonus on {day} (ratio {ratio:g}) but its own frame steps by "
                         "{step:.4f} there (not re-based); not recorded, new bars held")
MSG_SPLIT_NEITHER_ADJUSTED = ("{key}: Yahoo reports a split/bonus on {day} (ratio {ratio:g}) and steps by "
                              "{step:.4f} there, but neither its history nor ours is "
                              "adjusted; not recorded, new bars held")
MSG_SPLIT_RATIOS_UNEXPLAINED = ("{key}: Yahoo reports a split/bonus on {day} (ratio {ratio:g}) but Yahoo/stored "
                                "closes before it range {low:.4f}-{high:.4f} (expected {factor:.4f} or 1); not "
                                "recorded, new bars held")
MSG_CLOSE_MISMATCH = ("{key}: Yahoo's close differs from the stored close on {count} date(s) {first}..{last} "
                      "(Yahoo/stored {low:.4f}-{high:.4f})")
MSG_NOT_ONE_REBASE = "; not one re-base of the stored history, not recorded"
MSG_REBASE_NOT_FRACTION = "; a re-base by a ratio that is no simple fraction: not recorded, new bars held"
MSG_NSE_CHECK_SUFFIX = "; NSE check: {why}"
MSG_REBASE_UNCONFIRMED = ("; a re-base by {fraction} that no Yahoo split row or NSE bhavcopy confirms (yet): "
                          "not recorded, new bars held")

MSG_CHECK_NOT_WATCHLIST = "not a watchlist stock (no bhavcopy row)"
MSG_CHECK_BHAVCOPY_FAILED = "bhavcopy {day}: {error}"
MSG_CHECK_NO_ROW_WITH_PREV_CLOSE = "no EQ row with PREV_CLOSE for {key} in the {day} bhavcopy"
MSG_CHECK_PREVIOUS_UNKNOWN = ("the session before {day} ({previous}) is neither the stored bar {last} "
                              "nor in Yahoo's frame")
MSG_CHECK_PREV_CLOSE_OFF = "{day}: PREV_CLOSE {prev_close:g} vs the as-traded close {expected:g} of {previous}"
MSG_CHECK_NO_STEP_PROOF = "{day}: no step proves the ex-date and the next session's bhavcopy is not available yet"
MSG_CHECK_CHAIN_BROKEN = ("{day}: PREV_CLOSE {prev_close:g} is neither Yahoo's close of {previous_day} "
                          "({yahoo_close:g}) nor it / {factor:.4f}")
MSG_CHECK_NO_EX_DATE = "no ex-date found in the bhavcopies of {first}..{last}"
