"""Constants and messages of the range engine math."""
DAYS_PER_YEAR = 365.0       # implied volatilities are annualized over 365 calendar days
EWMA_LAMBDA = 0.94          # RiskMetrics daily decay
WARMUP_SESSIONS = 60        # sessions before the first standardized return
MIN_EXPIRY_DAYS = 0.5       # an option expiring today counts as half a day
MSG_EARNINGS_IN_HORIZON = "earnings in horizon (x{multiple} day{note})"
MSG_REGIME = "regime {regime} x{factor}"
MSG_MAJOR_EVENT = "major event x{factor}"
