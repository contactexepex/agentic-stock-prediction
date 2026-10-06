"""Constants of the PASDS indicators (file 06): annualization, decay and the quality rule."""
TRADING_DAYS = 252
EWMA_LAMBDA = 0.94  # RiskMetrics daily decay
FAST_CRITICAL = ("ret_1d", "ret_5d", "ema_ratio", "rsi_14", "atr_14", "realized_vol_10d")
JUMP_WARNING_RETURN = 0.4
BLOCKED_MISSING = 3   # PASDS 9.2: more than 3 critical nulls blocks the ticker
QUALITY_OK, QUALITY_PARTIAL, QUALITY_BLOCKED = "OK", "PARTIAL", "BLOCKED"
MSG_JUMP = "price jump over 40% in one day: possible unadjusted split or bad bar"
MSG_MISSING = "missing: "
