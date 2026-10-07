"""Constants of the range engine inputs (config/ranges.yaml switches, event history rules, reaction windows)."""
INPUTS = ("earnings_history", "ex_dividend", "beta_split", "implied_vol")
INPUT_EARNINGS_HISTORY, INPUT_EX_DIVIDEND, INPUT_BETA_SPLIT, INPUT_IMPLIED_VOL = INPUTS

NEAR_DAYS = 3     # earnings dates this close together are the same report
MOVED_DAYS = 45   # an upcoming date superseded by a newer one this close was moved
# SEC item 2.02 filings that are results releases (see results_filter)
REPORT_GRACE_DAYS = 1      # a release accepted up to a day after its 10-Q/10-K still belongs to it
REPORT_WINDOW_DAYS = 60    # without a period end, the release is at most this long before the report
SAME_QUARTER_DAYS = 45     # a yfinance date this close to a confirmed SEC release is the same quarter
PENDING_MIN_RELEASES = 4   # confirmed releases needed before a pending 2.02 is judged by its lag
PENDING_LAG_SHARE = 0.75   # pending 2.02 sooner after the quarter end than this x the shortest lag: not results
PROJECTED_SLACK_DAYS = 10  # a period end projected a year on is that known one if this close (52/53-week years)
DAYS_PER_YEAR = 365
EARNINGS_LOOKBACK_DAYS = 7  # an earnings date this far before the as-of date no longer affects the horizon
MIN_CUE_OBSERVATIONS = 60

EVENT_TYPES_SQL = "('earnings', 'ex_dividend', 'periodic_report')"
LOAD_EVENTS_SQL = ("SELECT ticker, type, date, timing, amount, source, first_seen_at, period_end, accepted_at "
                   "FROM event_history "
                   f"WHERE type IN {EVENT_TYPES_SQL} ORDER BY ticker, type, date")
TYPE_EARNINGS, TYPE_EX_DIVIDEND, TYPE_PERIODIC_REPORT = "earnings", "ex_dividend", "periodic_report"
SOURCE_SEC_HISTORY, SOURCE_YFINANCE_HISTORY = "sec_history", "yfinance_history"
HISTORY_SUFFIX = "_history"
TIMING_BEFORE_OPEN, TIMING_DURING, TIMING_AFTER_CLOSE = "before_open", "during", "after_close"
BETA_FIT = "fit"
DEFAULT_BETA = 1.0
MSG_IV_TEXT = "IV {iv} to {expiry}"
MSG_IV_PRICES_EARNINGS = "{text} prices earnings"
MSG_IV_BLENDED = "{text} blended x{weight}"
