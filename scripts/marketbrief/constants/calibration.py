"""Constants and messages of the daily range calibration."""
STEP_CALIBRATE = "calibrate"
SWITCH_ACI = "aci"
SOURCE_POOL = "pool"
SOURCE_NORMAL = "normal"
ROUND_DECIMALS = 5
CALIBRATION_QUANTILES = {"q10": 0.10, "q25": 0.25, "q75": 0.75, "q90": 0.90}
# live scored ranges of the N+k window only (legacy_cc ranges, stored before B10 without horizon_label, were
# standardised on another window and never join the pool)
LIVE_RANGE_SQL = ("SELECT horizon_days, as_of_date, z FROM range_record WHERE z IS NOT NULL "
                  "AND horizon_label = 'n_plus_k' ORDER BY id")
MSG_NO_BENCHMARK = "no benchmark bars; run collect_prices.py first"
