"""Trading-calendar and scheduled-event constants: rule kinds, session edges, default hours and messages."""
from datetime import time

MAJOR_WINDOW_DAYS = 2           # PASDS: a major event within 2 calendar days -> EVENT_HEAVY
DEFAULT_OPEN = time(9, 30)      # local open and close assumed only when the exchange calendar
DEFAULT_CLOSE = time(16, 0)     # is unavailable
CALENDAR_START = "2020-01-01"
BAR_SETTLE_MINUTES = 120      # a session's bar counts as final this long after its close (closing prices settle)
MIN_SESSION_OFFSET = -5
MAX_SESSION_OFFSET = 0
WEEKDAY_FRIDAY = 4
WEEKS_PADDING_DAYS = 7

EDGE_OPEN = "open"
EDGE_CLOSE = "close"

RULE_WEEKLY = "weekly"
RULE_THIRD_FRIDAY = "third_friday"
RULE_FIRST_FRIDAY = "first_friday"
RULE_LAST_WEEKDAY = "last_weekday"
RULE_MONTH_END = "month_end"   # last calendar day; market_events moves it to the last session

KEY_EVENTS_RULES = "rules"
KEY_EVENTS_FIXED = "fixed"
FILE_EVENTS_CONFIG = "events.yaml"
KEY_PROVISIONAL = "provisional"                 # an event spec flag (issue #15)
KEY_PROVISIONAL_DATES = "provisional_dates"     # emitted dates of a rule that are not confirmed
KEY_PROVISIONAL_FROM = "provisional_from"       # a rule's dates on or after this one are not confirmed
WORD_PROVISIONAL = "provisional"
PROVISIONAL_SUFFIX = " (provisional date)"

MSG_UNKNOWN_EVENT_RULE = "unknown event rule {kind!r}"
MSG_SESSION_OFFSET_RANGE = "session_offset must be between {low} and {high}, got {offset}"
MSG_NO_EXCHANGE_CALENDARS = ("exchange_calendars cannot be imported ({error}): trading days and closed-day bar "
                             "exclusion need it; install requirements.txt")
MSG_BAD_SPECIAL_SESSION_HOURS = (
    "special_session_hours {day}: {hours!r} is not \"HH:MM-HH:MM\" with the open before the close (market config)"
)
