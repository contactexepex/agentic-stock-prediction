"""Constants and messages of the published price ranges."""
STEP_RANGES = "ranges"
ROUND_PRICE = 4
ROUND_CENTER = 6
NO_CALIBRATION_ID = "none (normal)"
CALIBRATION_ID = "{id} ({source}, n={history}+{live})"
MSG_NO_REGIME = "no regime snapshot; run features.py first"
MSG_NOW_NEEDS_OFFSET = "--now needs a UTC offset, e.g. 2026-10-05T02:40:00+00:00"
HELP_NOW = "made_at as ISO 8601 UTC with offset instead of now (tests only)"
MSG_INDEX_CUE_IGNORED = "index cue ignored: {symbol} quoted after {first} open"
MSG_CUE_IGNORED = "cue ignored: quoted after {first} open"
MSG_LATE_CLOSED = "late: {first} closed before made_at"
MSG_LATE_OPENED = "late: {first} opened before made_at"
MSG_AI_WIDENED = "AI widened +{percent}"
MSG_INDEX_CUE = "index {index:+.2%} expected from {symbol}, x beta {beta:.2f} x{weight}"
MSG_OWN_CUE_NET = ", own cue {cue:+.2%} net x{weight}"
MSG_CUE = "cue {cue:+.2%} x{weight}"
MSG_EX_DIVIDEND = "ex-dividend {amount:g} ({share:.2%})"
NOTE_OPTIONS_IMPLIED = ", options-implied"
NOTE_PAST_MOVES = ", {count} past moves, median {median:.1%}"
LATEST_REGIME_SQL = "SELECT * FROM regime_latest ORDER BY as_of_date DESC LIMIT 1"
PREDICTIONS_SQL = ("SELECT ticker, horizon_days, direction, confidence, range_widen FROM predictions "
                   "WHERE as_of_date = ? QUALIFY row_number() OVER (PARTITION BY id ORDER BY made_at DESC) = 1")
CUE_TIME_SQL = ("SELECT coalesce(ts, collected_at) FROM quotes WHERE symbol IN (?, ?) "
                "AND CAST(collected_at AS DATE) = CAST(? AS DATE) AND collected_at <= ? "
                "ORDER BY symbol = ? DESC, collected_at DESC LIMIT 1")
INDEX_CUE_SQL = ("SELECT change_pct, coalesce(ts, collected_at) FROM quotes WHERE symbol = ? "
                 "AND CAST(collected_at AS DATE) = CAST(? AS DATE) AND collected_at <= ? "
                 "ORDER BY collected_at DESC LIMIT 1")
OPTIONS_SQL = ("SELECT * FROM options_latest WHERE day >= ? AND collected_at <= ? "
               "ORDER BY ticker, expiry, day")
