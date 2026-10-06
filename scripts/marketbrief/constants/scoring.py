"""Constants of the proper scores (docs/DESIGN.md section 6)."""
EPS = 1e-6
WILSON_Z = 1.96                 # 95% interval
COIN_FLIP_BRIER = 0.25
MISSING_DASH = "–"
CALL_BINS = (0.5, 0.6, 0.7, 0.8, 0.9)   # bins [0.5, 0.6), [0.6, 0.7), [0.7, 0.8), [0.8, 0.9]
RANGE_QUANTILES = (("lo80", 0.10), ("lo50", 0.25), ("hi50", 0.75), ("hi80", 0.90))
