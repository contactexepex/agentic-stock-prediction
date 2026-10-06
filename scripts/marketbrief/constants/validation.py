"""Stages, kind groups and enumerations of the daily gate (validate.py)."""

from __future__ import annotations


STAGES = ("collect", "news", "features", "context", "forecast", "report")

# kinds whose day files are named by the trading date, with the column that says when a row was written
TRADING_DATE_KINDS = {
    "prices": "collected_at",
    "features": "computed_at",
    "regime": "computed_at",
    "calibration": "computed_at",
    "ranges": "made_at",
    "replays": "computed_at",
    "adjustments": "detected_at",
}

STAGE_KINDS = {"features": ("features", "regime", "calibration")}

FETCH_COL = {
    "quotes": "collected_at",
    "news": "first_seen_at",
    "filings": "first_seen_at",
    "announcements": "first_seen_at",
}

ENRICH_ENUMS = {
    "materiality": {"low", "medium", "high"},
    "urgency": {"low", "medium", "high"},
    "event_type": {"earnings", "macro", "product", "legal", "sector", "analyst", "ma", "flows", "other"},
}

# ---------- validate: collect_checks ----------
MSG_BENCHMARK_VOL_INDEX_NO_BARS_STORED = (
    "benchmark / vol index: no bars stored at all (never collected; the regime needs them)"
)
MSG_MARKET_SYMBOLS_WITH_NO_BARS_STORED = (
    "market symbols with no bars stored at all (never collected: cues, factors, sector ETFs)"
)
MSG_NO_STORED_PRICE_BARS = "no stored price bars"
MSG_NEWEST_BAR_OLDER_THAN_THE_LAST = "newest bar older than the last completed session {need} (e.g. {value} {value_2})"
MSG_BAD_CLOSE_ON_RECENT_BAR = "close missing or <= 0 on a bar since {since}"
MSG_DUPLICATED_KEYS = "{kind}: {count} duplicated {key}(s), e.g. {value}"
MSG_LATE_RUN_SESSION_HAS_CLOSED_BUT = (
    "late run: session {sess} has closed but has no stored bar (the run is as of the previous session)"
)
MSG_BIG_ONE_DAY_MOVE_WITHOUT_ACTION = (
    "{ticker} 1-day return {row:+.1%} on {day} with no split/corporate-action event on file"
)
MSG_COLLECTOR_PROBLEM = "{name}: {value}"
MSG_COLLECTOR_FAILED = "{name}: {count} failed: {value}"
MSG_PRICES_PRICE_BASIS_WARNING_S = "prices: {count} price-basis warning(s): {value}"
MSG_ZERO_ROWS_WITHOUT_REASON = "{name}: {key} is 0 and the summary gives no reason"
MSG_COLLECTOR_FILE_PROBLEM = "{rel}: {value}"
MSG_IS_NOT_A_JSON_SUMMARY = "{name} is not a JSON summary ({error})"
MSG_NO_ROWS_WRITTEN_TODAY_NO_COLLECTOR = "{kind}: no rows written today (no collector summaries in work/steps/)"

# ---------- validate: news_checks ----------
MSG_NEWS_ARTICLES_ROWS_BREAK_THE_ARTICLE = "{count} news_articles rows break the article rules, e.g. {value}"
MSG_ENRICHED_FILE_PROBLEM = "{name}: {value}"
MSG_REPEATED_IDS = "{name}: repeated ids {value}"
MSG_IDS_ARE_NOT_NEWS_ANNOUNCEMENTS_FIRST = "{count} ids are not news/announcements first seen today, e.g. {value}"
MSG_IDS_ALREADY_IN_NEWS_ENRICHED_E = "{count} ids already in news_enriched, e.g. {value}"
MSG_TODAYS_IDS_WITHOUT_ENRICHMENT = "{count} of today's news/announcement ids have no enrichment, e.g. {value}"
MSG_ENRICHMENT_RULE_PROBLEM = "{record_id}: {value}"

# ---------- validate: report_checks ----------
MSG_NO_RANGE_AS_OF_AND_NO = "no range as of {as_of} and no skip reason: {value}"
MSG_NOT_WRITTEN = "{value} not written"
MSG_STILL_HAS_NUMBERED_AGENT_MARKERS = "{name} still has {count} AGENT marker(s)"
MSG_LOST_ITS_REPORT_DATA_LINE = "{name} lost its report-data line"
MSG_NOT_WRITTEN_2 = "{name} not written"
MSG_WORK_CONTEXT_MD_MISSING_NARRATIVE_NUMBERS = (
    "work/context.md missing: narrative numbers checked against the skeleton and DuckDB only"
)
MSG_NEWS_FEED_COUNT_UNAVAILABLE = "news feed count unavailable ({name}: {error})"
MSG_STILL_HAS_AGENT_MARKERS = "{name} still has AGENT marker(s)"
MSG_SOURCE_QUERY_SKIPPED = "source query skipped ({name}: {value}): {value_2}"

# ---------- validate: row_checks ----------
MSG_LAST_LINE_HAS_NO_NEWLINE_TRUNCATED = "last line has no newline (truncated write?)"
MSG_LINE_IS_NOT_A_JSON_OBJECT = "line {index} is not a JSON object"
MSG_ROW_FIELDS_NOT_IN_THE_SCHEMA = "row {index}: fields not in the {kind} schema: {unknown}"
MSG_ROW_MISSING_ID = "row {index}: missing id"
MSG_MORE_PROBLEMS_OMITTED = "..."
MSG_LINE_IS_NOT_JSON = "line {index} is not JSON ({msg})"
MSG_ROW_TYPE_PROBLEM = "row {index}: {key}={value!r} {why}"
MSG_ROW_IS_IN_THE_FUTURE_NOW = "row {index}: {key} {value} is in the future (now {isoformat})"

# ---------- validate: stages ----------
MSG_NO_FEATURE_ROW = "no feature row"
MSG_FEATURE_ROW_OLDER_THAN_THE_TICKER = "feature row older than the ticker's newest bar (run features.py)"
MSG_INDICATOR_QUALITY_BLOCKED_NO_CALL_ALLOWED = "indicator quality BLOCKED: no call allowed"
MSG_NO_REGIME_ROW_AS_OF_NEWEST = "no regime row as of {need} (newest {reg})"
MSG_IS_MISSING_OR_EMPTY = "{value} is missing or empty"
MSG_FIRST_LINE_IS_NOT_TODAY_S = "first line is not today's pack header: {value!r}"
MSG_THE_CONTEXT_PACK_CONTAINS_A_PYTHON = "the context pack contains a Python traceback"
MSG_WATCHLIST_TICKERS_NOT_NAMED_IN_THE = "watchlist tickers not named in the context pack"
MSG_NO_MARKET_REGIME_SECTION = "no 'Market regime' section"
