"""Constants of the range backtest."""

from __future__ import annotations


# input -> (arm when off, arm when on, column marking the rows where it applies)
INPUT_ARMS = {
    "earnings_history": ("earn_fixed", "earn_hist", "earn"),
    "ex_dividend": ("core", "exdiv", "has_div"),
    "beta_split": ("cue_direct", "cue_beta", "has_cue"),
}
