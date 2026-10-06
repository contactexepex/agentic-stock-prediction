"""Constants and messages of the SEC relationship collectors (insiders, stakes, holdings, fundamentals)."""

COLLECTOR_INSIDERS = "insiders"
COLLECTOR_STAKES = "stakes"
COLLECTOR_HOLDINGS = "holdings"
COLLECTOR_FUNDAMENTALS = "fundamentals"
CFG_RELATIONSHIPS = "relationships"
DEFAULT_LOOKBACK_DAYS = 7
SEEN_LOOKBACK_DAYS = 120
ERROR_TEXT_LIMIT = 200
ISO_DATE_LENGTH = 10

# ---------- insiders (Form 4) ----------
DEFAULT_INSIDER_FORMS = ["4", "4/A"]
ROLE_OFFICER, ROLE_DIRECTOR, ROLE_TEN_PCT_OWNER, ROLE_OTHER = "Officer", "Director", "10% owner", "Other"
CODE_PURCHASE, CODE_SALE = "P", "S"
INSIDER_VALUE_DECIMALS = 2
NON_DERIVATIVE_TABLE = ("nonDerivativeTable", "nonDerivativeTransaction", False)
DERIVATIVE_TABLE = ("derivativeTable", "derivativeTransaction", True)

# ---------- stakes (Schedule 13D / 13G) ----------
DEFAULT_STAKE_FORMS = ["SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A"]
KIND_13D, KIND_13G = "13D", "13G"
AMENDMENT_SUFFIX = "/A"
PURPOSE_LIMIT = 600

# ---------- holdings (13F) ----------
FILING_WINDOW_DAYS = 50  # 13F deadline is 45 days after quarter end
DEFAULT_QUARTERS = 2
FORM_13F_HR, FORM_13F_NT = "13F-HR", "13F-NT"
REPORT_TYPE_HOLDINGS = "13F HOLDINGS REPORT"
REPORT_TYPE_NOTICE = "13F NOTICE"
MSG_UNNAMED_MANAGER = "unnamed manager"
MSG_NO_FILERS = "no filers or cusips configured"
MSG_UP_TO_DATE = "up to date (quarter {quarter})"
MSG_NO_NEW_QUARTER = "no new quarter due (quarter {quarter} window closed)"
MSG_UNKNOWN_REPORT_TYPE = "unknown report type"
MSG_INCOMPLETE_OTHER_MANAGERS = "{report_type}: other managers report part of the holdings"
MSG_INCOMPLETE_CONFIDENTIAL = "holdings omitted as confidential"
MSG_INCOMPLETE_PLACEHOLDER = "placeholder table (CUSIP 000000000)"
MSG_INCOMPLETE_TABLE_LINES = "table has {lines} of {total} lines"
MSG_NO_INFORMATION_TABLE = "no information table in filing"

# ---------- 13F holdings ----------
MSG_REPORTED_BY = "{filer} {period}: reported by {by}"
MSG_HELD = "{filer} {period}: {held} held"
MSG_HELD_INCOMPLETE = " (incomplete: {why})"
