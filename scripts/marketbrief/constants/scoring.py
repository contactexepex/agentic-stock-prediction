"""Constants of the proper scores (docs/DESIGN.md section 6)."""
EPS = 1e-6
WILSON_Z = 1.96                 # 95% interval
COIN_FLIP_BRIER = 0.25
MISSING_DASH = "–"
CALL_BINS = (0.5, 0.6, 0.7, 0.8, 0.9)   # bins [0.5, 0.6), [0.6, 0.7), [0.7, 0.8), [0.8, 0.9]
RANGE_QUANTILES = (("lo80", 0.10), ("lo50", 0.25), ("hi50", 0.75), ("hi80", 0.90))

# ---------- call scoring basis (analytics/call_basis.py; config/settings.yaml call_scoring) ----------
SETTING_CALL_SCORING, SETTING_BASIS, SETTING_FROM = "call_scoring", "label_basis", "from"
SETTING_N_PLUS_K_FROM = "n_plus_k_from"   # B10: open-to-close 5-day calls made before it are legacy_5d_d4 (D+4)
BASIS_SHORT = {"close_to_close": "close→close", "open_to_close": "open→close",
               "open_to_close legacy_5d_d4": "open→close D+4 (legacy)"}
BASIS_NOTE = ("Calls are scored on one of two bases, never pooled: close→close = the as-of close to the close h "
              "sessions later (calls made before the switch, legacy); open→close = bought at the open of D, the next "
              "session, sold at the close of the k-th session after D (N+k: D+1 for N+1, D+5 for N+5). Old "
              "open→close 5-day calls sold at D+4 are labelled legacy_5d_d4 and kept apart.")
MSG_UNKNOWN_BASIS = "config/settings.yaml call_scoring.label_basis {basis!r} is not one of {known}"
MSG_SCORED_ON = " Scores of calls scored {basis}; calls on the other basis are never pooled with them."
