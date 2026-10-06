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
MSG_NEWEST_BAR_BEHIND_LAST_SESSION = (
    "newest bar older than the last completed session {need} (e.g. {ticker} {newest_date})"
)
MSG_BAD_CLOSE_ON_RECENT_BAR = "close missing or <= 0 on a bar since {since}"
MSG_DUPLICATED_KEYS = "{kind}: {count} duplicated {key}(s), e.g. {examples}"
MSG_LATE_RUN_SESSION_HAS_NO_BAR = (
    "late run: session {session} has closed but has no stored bar (the run is as of the previous session)"
)
MSG_BIG_MOVE_WITHOUT_ACTION = (
    "{ticker} 1-day return {one_day_return:+.1%} on {day} with no split/corporate-action event on file"
)
MSG_COLLECTOR_ERROR = "{name}: {error}"
MSG_COLLECTOR_FAILED = "{name}: {count} failed: {failures}"
MSG_PRICE_BASIS_WARNINGS = "prices: {count} price-basis warning(s): {warnings}"
MSG_ZERO_ROWS_WITHOUT_REASON = "{name}: {key} is 0 and the summary gives no reason"
MSG_COLLECTOR_FILE_PROBLEM = "{relative_path}: {problems}"
MSG_NOT_A_JSON_SUMMARY = "{name} is not a JSON summary ({error})"
MSG_NO_ROWS_WRITTEN_TODAY_NO_COLLECTOR = "{kind}: no rows written today (no collector summaries in work/steps/)"

# ---------- validate: news_checks ----------
MSG_ARTICLE_ROWS_BREAK_RULES = "{count} news_articles rows break the article rules, e.g. {examples}"
MSG_ENRICHED_FILE_PROBLEM = "{name}: {problems}"
MSG_REPEATED_IDS = "{name}: repeated ids {ids}"
MSG_IDS_NOT_FIRST_SEEN_TODAY = "{count} ids are not news/announcements first seen today, e.g. {ids}"
MSG_IDS_ALREADY_ENRICHED = "{count} ids already in news_enriched, e.g. {ids}"
MSG_IDS_WITHOUT_ENRICHMENT = "{count} of today's news/announcement ids have no enrichment, e.g. {ids}"
MSG_ENRICHMENT_RULE_PROBLEM = "{record_id}: {problems}"

# ---------- validate: report_checks ----------
MSG_NO_RANGE_AND_NO_SKIP_REASON = "no range as of {as_of} and no skip reason: {tickers}"
MSG_REPORT_NOT_WRITTEN = "{report_path} not written"
MSG_STILL_HAS_NUMBERED_AGENT_MARKERS = "{name} still has {count} AGENT marker(s)"
MSG_LOST_ITS_REPORT_DATA_LINE = "{name} lost its report-data line"
MSG_SLACK_DRAFT_NOT_WRITTEN = "{name} not written"
MSG_WORK_CONTEXT_MD_MISSING_NARRATIVE_NUMBERS = (
    "work/context.md missing: narrative numbers checked against the skeleton and DuckDB only"
)
MSG_NEWS_FEED_COUNT_UNAVAILABLE = "news feed count unavailable ({name}: {error})"
MSG_STILL_HAS_AGENT_MARKERS = "{name} still has AGENT marker(s)"
MSG_SOURCE_QUERY_SKIPPED = "source query skipped ({error_type}: {error_text}): {query}"

# ---------- validate: row_checks ----------
MSG_LAST_LINE_HAS_NO_NEWLINE_TRUNCATED = "last line has no newline (truncated write?)"
MSG_LINE_IS_NOT_A_JSON_OBJECT = "line {index} is not a JSON object"
MSG_ROW_FIELDS_NOT_IN_THE_SCHEMA = "row {index}: fields not in the {kind} schema: {unknown}"
MSG_ROW_MISSING_ID = "row {index}: missing id"
MSG_MORE_PROBLEMS_OMITTED = "..."
MSG_LINE_IS_NOT_JSON = "line {index} is not JSON ({reason})"
MSG_ROW_TYPE_PROBLEM = "row {index}: {key}={value!r} {why}"
MSG_ROW_TIME_IN_THE_FUTURE = "row {index}: {key} {value} is in the future (now {now_text})"

# ---------- validate: stages ----------
MSG_NO_FEATURE_ROW = "no feature row"
MSG_FEATURE_ROW_OLDER_THAN_THE_TICKER = "feature row older than the ticker's newest bar (run features.py)"
MSG_INDICATOR_QUALITY_BLOCKED_NO_CALL_ALLOWED = "indicator quality BLOCKED: no call allowed"
MSG_NO_REGIME_ROW_FOR_SESSION = "no regime row as of {need} (newest {newest_regime})"
MSG_FILE_MISSING_OR_EMPTY = "{path} is missing or empty"
MSG_FIRST_LINE_NOT_PACK_HEADER = "first line is not today's pack header: {first_line!r}"
MSG_CONTEXT_PACK_HAS_TRACEBACK = "the context pack contains a Python traceback"
MSG_WATCHLIST_NOT_IN_CONTEXT_PACK = "watchlist tickers not named in the context pack"
MSG_NO_MARKET_REGIME_SECTION = "no 'Market regime' section"

# ---------- validate: second pass (messages built from several parts) ----------
MSG_BENCHMARK_VOL_INDEX_STALE = "benchmark / vol index bar older than {need} (the regime needs them; newest {newest})"
MSG_MARKET_SYMBOLS_STALE = "market symbols with no bar since {old} (cues, factors, sector ETFs; newest {newest})"
MSG_NOT_FETCHED_NO_ROWS = "{kind}: no stored rows at all"
MSG_NOT_FETCHED_STALE = "{kind}: newest {column} {newest} is not from this run (today {today}, max age {limit} h)"
MSG_NEWS_SOURCE_NOT_HTTPS = "scheme {scheme}"
MSG_NEWS_SOURCE_GOOGLE_DOMAIN = "Google News feed but link domain {domain}"
MSG_NEWS_SOURCE_OUTLET_DOMAIN = "outlet {feed} but link domain {domain} (allowed {allowed})"
MSG_NEWS_SOURCE_UNKNOWN_OUTLET = "feed {feed!r} is not a configured outlet"
MSG_NEWS_ROWS_FROM_UNCONFIGURED_SOURCES = "{count} news rows from unconfigured sources or not https, e.g. {examples}"
MSG_ARTICLE_UNKNOWN_ACCESS = "{record_id}: access {access!r}"
MSG_ARTICLE_EXTRACT_TOO_LONG = "{record_id}: extract longer than 3 sentences of 40 words"
MSG_ARTICLE_URL_NOT_ALLOWLISTED = "{record_id}: read from a URL that is not an allowlisted https page ({final_url})"
MSG_ARTICLE_STATUS_WITHOUT_READ = "{record_id}: access {access} but an HTTP status is stored"
MSG_ENRICH_SCORE_OUT_OF_RANGE = "{field} {value!r} not in {lower}..{upper}"
MSG_ENRICH_NOT_ONE_OF = "{field} {value!r} not one of {allowed}"
MSG_ENRICH_SUMMARY_TOO_LONG = "summary missing or over 25 words"
MSG_ENRICH_PROMPT_VERSION_MISSING = "prompt_version missing"
MSG_ENRICH_ANALYZED_AT_MISSING = "analyzed_at missing"
MSG_REPORT_SKIPPED_NOT_WRITTEN = "skipped: {name} not written yet"
MSG_RANGE_SKIPPED_LATE_RUN = "{horizon}d: target {target} closed (late run)"
MSG_RANGE_SKIPPED_MID_SESSION = "{horizon}d: target {target} opened (mid-session run)"
MSG_RANGE_SKIPPED_NO_FEATURES = "{horizon}d: no feature row as of {as_of}"
MSG_UNMATCHED_NUMBERS = (
    "{name}: {count} number(s) with no same-kind source number for the companies or symbols named "
    "(context pack, script-written report, cited news text, stored rows): {examples}"
)
MSG_UNMATCHED_NUMBER_EXAMPLE = '{token!r} in "{sentence}"'
