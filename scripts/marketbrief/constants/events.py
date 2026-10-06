"""Constants and messages of the events collector (earnings, ex-dividend, past results releases)."""
COLLECTOR_EVENTS = "events"
FIELD_EARNINGS_DATE = "Earnings Date"
FIELD_EX_DIVIDEND_DATE = "Ex-Dividend Date"
EVENT_EARNINGS = "earnings"
EVENT_EX_DIVIDEND = "ex_dividend"
EVENT_PERIODIC_REPORT = "periodic_report"
CALENDAR_FIELDS = {FIELD_EARNINGS_DATE: EVENT_EARNINGS, FIELD_EX_DIVIDEND_DATE: EVENT_EX_DIVIDEND}
EVENT_LABELS = {EVENT_EARNINGS: "earnings", EVENT_EX_DIVIDEND: "ex-dividend"}

SOURCE_YFINANCE = "yfinance"
SOURCE_YFINANCE_HISTORY = "yfinance_history"
SOURCE_SEC_HISTORY = "sec_history"
SOURCE_NSE_HISTORY = "nse_history"
HISTORY_SUFFIX = "_history"

TIMING_BEFORE_OPEN = "before_open"
TIMING_DURING = "during"
TIMING_AFTER_CLOSE = "after_close"
PRIORITY_FILING = 0       # SEC or NSE filings, the best source of a report date
PRIORITY_REPORT = 1       # yfinance earnings-report row
PRIORITY_CALL = 2         # yfinance earnings-call row (only times the release if it is before the open)

NEAR_DAYS = 3             # earnings dates this close together are the same report
NSE_STALE_DAYS = 100      # poll a ticker with NSE results again when its newest past earnings date is this old
QUARTER_GAP_DAYS = 120    # consecutive quarterly results are at most this far apart (45/60-day deadlines)
RELEASE_WINDOW_HOURS = 36  # a results announcement this long before the first XBRL filing = its release
DEFAULT_HISTORY_DAYS = 1100
EARNINGS_DATES_LIMIT = 40
LATE_FILING_DAYS_QUARTERLY = 48   # SEBI LODR regulation 33: 45 days plus 3 days' grace
LATE_FILING_DAYS_ANNUAL = 63      # 60 days (March quarter) plus 3 days' grace
ANNUAL_QUARTER_MONTH = 3
# NSE announcement categories that carry a results release (the PDF filed after the board meeting)
RESULTS_ANNOUNCEMENTS = ("Outcome of Board Meeting", "Financial Result Updates", "Integrated Filing- Financial")
REPORT_FORMS = ("10-Q", "10-K")      # periodic reports (not amendments) that date each quarter's results release
RESULT_8K_FORMS = ("8-K", "6-K")
ITEM_RESULTS = "2.02"
EARNINGS_DATES_METHODS = ("get_earnings_dates", "_get_earnings_dates_using_screener")
YAHOO_EVENT_TYPE_COLUMN = "Event Type"
YAHOO_EARNINGS, YAHOO_CALL = "Earnings", "Call"

WHAT_CALENDAR = "calendar"
WHAT_DIVIDENDS = "dividends"
WHAT_EARNINGS_HISTORY = "earnings_history"
ERROR_TEXT_LIMIT = 200
METHOD_ERROR_LIMIT = 120

MSG_EMPTY_CALENDAR = "empty calendar"
MSG_NO_DIVIDENDS = "no dividends returned ({why})"
MSG_STORED_DIVIDENDS = "{count} stored"
MSG_CALENDAR_LISTS_EX_DIVIDEND = "calendar lists ex-dividend {day}"
MSG_ESTIMATED_DIVIDEND = " (est. {amount:g}, last dividend)"
MSG_PERIODIC_REPORT = " ({form}, period {period})"
MSG_INTEGRATED_LIST_PARTIAL = "{symbol}: integrated filings list {rows} of {total} rows"
MSG_LATE_QUARTERS = "{ticker}: {count} quarter(s) first filed after the SEBI deadline, not used"
NSE_SOURCE_PREFIX = "nse_earnings:"

NSE_ENDPOINT_INTEGRATED = "integrated-filing-results"
NSE_ENDPOINT_FINANCIAL = "corporates-financial-results"
NSE_ENDPOINT_ANNOUNCEMENTS = "corporate-announcements"
NSE_INTEGRATED_TYPE = "Integrated Filing- Financials"
NSE_FIELDS_QUARTER_END = "qe_Date"
NSE_FIELDS_BROADCAST = ("broadcast_Date", "creation_Date")
NSE_FIELDS_FINANCIAL_TO = "toDate"
NSE_FIELDS_FINANCIAL_BROADCAST = ("broadCastDate", "exchdisstime", "filingDate")
NSE_FIELDS_ANNOUNCED = ("an_dt", "exchdisstime", "sort_date")
