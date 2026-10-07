"""Names of horizons on the reader's pages (presentation/horizon_names.py; core/horizons.py, docs/SPEC.md decision 37).

An N+k row (buy at the open of D, sell at the close of D+k; its range targets the close k + 1 trading days after the
as-of close) is named by an N+k template; a row of an old window (legacy_cc, legacy_5d_d4) keeps the wording its page
used before B10, given as (names of particular horizons, template of the others), so the two never share a name."""

from marketbrief.constants.horizons import LABEL_LEGACY_5D_D4, LABEL_N_PLUS_K

# SQL over track_record: the scoring basis of a row as a summary key (analytics/scoring.basis_key): open-to-close
# 5-day calls of the old D+4 window (horizon_label legacy_5d_d4) are their own key, never pooled with N+k calls
BASIS_KEY_SQL = (
    f"CASE WHEN horizon_label = '{LABEL_LEGACY_5D_D4}' THEN label_basis || ' {LABEL_LEGACY_5D_D4}' ELSE label_basis END"
)
# SQL ORDER BY items after the horizon, for rows grouped by horizon_label AS label: N+k first, then old windows
LABEL_ORDER_SQL = f"label <> '{LABEL_N_PLUS_K}', label"

# HTML report and charts (view_data.py): a range card, the chart title phrase, the range and record names
WHEN_N_PLUS_K, WHEN_LEGACY = "N+{h} ({days} trading days)", ({1: "Next trading day"}, "{h} trading days")
PHRASE_N_PLUS_K = "in {days} trading days (N+{h})"  # "Where each price may be ..."
PHRASE_LEGACY = ({1: "after the next trading day"}, "in {h} trading days")
NAME_N_PLUS_K = "N+{h}"
NAME_LEGACY_DAY = ({}, "{h}-day")  # ranges and the calibration points
NAME_LEGACY_RECORD = ({1: "Next-day"}, "{h}-day")  # a company's range record
# dashboard (presentation/dashboard/): model cards, range rows, live calls, the replay record
NAME_N_PLUS_K_MODEL = "N+{h}: sell at the close of D+{h}"
NAME_LEGACY_MODEL = ({1: "Buy today, sell tomorrow"}, "Buy today, sell within {h} days")
NAME_LEGACY_RANGE = ({1: "Next session"}, "{h} sessions")
NAME_LEGACY_CALLS = ({1: "1 day"}, "{h} days")
NAME_REPLAY = "{h} day"  # the replay record's per-horizon fields (cover80_<h>d, ...)
# report and Slack (presentation/report/): the ranges scored on the latest target date and a call's horizon
NAME_LEGACY_SCORED_FIRST = ({1: "next-day"}, "{h}-day")  # "Yesterday: next-day 80% ranges hit ..."
NAME_LEGACY_SLACK_CALL = ({1: "next day"}, "{h} days")
