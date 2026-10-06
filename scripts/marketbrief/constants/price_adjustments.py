"""Split and bonus adjustments of stored price bars: tolerances, the kind folder and record keys."""
SPLIT_TOLERANCE = 0.01       # a measured price ratio vs a split factor (Yahoo rounds closes)
BASIS_MATCH_TOLERANCE = 0.02  # |Yahoo close / stored close - 1| above this: the stored bar is on another basis
MAX_SPLIT_TERM = 20          # a split factor is p/q with p, q <= 20 (1:1 bonus 1/2, 1:10 bonus 10/11, 3:2 split 2/3)
FRACTION_TOLERANCE = 0.001   # a re-based close is the old one x factor up to Yahoo's rounding

KEY_EX_DATE = "ex_date"
KEY_FACTOR = "factor"
KEY_DETECTED_AT = "detected_at"
KEY_SUPERSEDES = "supersedes"
