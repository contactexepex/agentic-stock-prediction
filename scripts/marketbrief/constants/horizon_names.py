"""Names of horizons on the reader's pages (presentation/horizon_names.py; core/horizons.py, docs/SPEC.md decision 37).

An N+k row (buy at the open of D, sell at the close of D+k; its range targets the close k + 1 trading days after the
as-of close) is named by an N+k template; a row of an old window (legacy_cc, legacy_5d_d4) keeps the wording its page
used before B10, given as (names of particular horizons, template of the others), so the two never share a name."""

# HTML report and charts (view_data.py): a range card, the chart title phrase, the range and record names
WHEN_N_PLUS_K, WHEN_LEGACY = "N+{h} ({days} trading days)", ({1: "Next trading day"}, "{h} trading days")
PHRASE_N_PLUS_K = "in {days} trading days (N+{h})"   # "Where each price may be ..."
PHRASE_LEGACY = ({1: "after the next trading day"}, "in {h} trading days")
NAME_N_PLUS_K = "N+{h}"
NAME_LEGACY_DAY = ({}, "{h}-day")                    # ranges and the calibration points
NAME_LEGACY_RECORD = ({1: "Next-day"}, "{h}-day")    # a company's range record
# dashboard (presentation/dashboard/): model cards, range rows, live calls, the replay record
NAME_N_PLUS_K_MODEL = "N+{h}: sell at the close of D+{h}"
NAME_LEGACY_MODEL = ({1: "Buy today, sell tomorrow"}, "Buy today, sell within {h} days")
NAME_LEGACY_RANGE = ({1: "Next session"}, "{h} sessions")
NAME_LEGACY_CALLS = ({1: "1 day"}, "{h} days")
NAME_REPLAY = "{h} day"                              # the replay record's per-horizon fields (cover80_<h>d, ...)
# report and Slack (presentation/report/): the ranges scored on the latest target date and a call's horizon
NAME_LEGACY_SCORED_FIRST = ({1: "next-day"}, "{h}-day")   # "Yesterday: next-day 80% ranges hit ..."
NAME_LEGACY_SLACK_CALL = ({1: "next day"}, "{h} days")
