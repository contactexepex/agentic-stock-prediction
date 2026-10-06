"""Constants of the prediction record rules (CLAUDE.md prediction rules)."""

HORIZONS = (1, 5)
CONF_MIN, CONF_MAX, WIDEN_MAX, RATIONALE_WORDS = 0.50, 0.90, 0.5, 40
REQUIRED = (
    "id",
    "as_of_date",
    "ticker",
    "horizon_days",
    "direction",
    "confidence",
    "rationale",
    "evidence_ids",
    "prompt_version",
)
DEFAULT_AS_OF_LABEL = "the latest price date"
DEFAULT_EVIDENCE_LABEL = "the stored news/filings/announcements"

# ---------- prediction rules ----------
MSG_UNKNOWN_TICKER = "unknown ticker {ticker!r}"
MSG_HORIZON_MUST_BE_1_OR_5 = "horizon_days must be 1 or 5 (got {horizon!r})"
MSG_AS_OF_DATE_MISMATCH = "as_of_date {as_of_date} is not {label} {want}"
MSG_ID_MUST_BE_DATE_TICKER_HORIZON = (
    "id must be <as_of_date>-<ticker>-<horizon>d = {as_of_date}-{ticker}-{horizon}d (got {id!r})"
)
MSG_ID_ALREADY_RECORDED = "id {id} already recorded"
MSG_DIRECTION_MUST_BE_UP_OR_DOWN = "direction must be up or down (got {direction!r})"
MSG_CONFIDENCE_OUT_OF_RANGE = "confidence must be {conf_min:.2f}-{conf_max:.2f} (got {confidence!r})"
MSG_RANGE_WIDEN_OUT_OF_RANGE = "range_widen must be 0-{widen_max} (got {range_widen!r})"
MSG_RATIONALE_NOT_TEXT_OR_TOO_LONG = "rationale must be text of at most {rationale_words} words"
MSG_EVIDENCE_IDS_UNKNOWN = "evidence ids not in {label}: {unknown}"
MSG_INDICATOR_QUALITY_BLOCKED = "{ticker} indicator quality is BLOCKED"
MSG_EARNINGS_WITHIN_ONE_DAY = "{ticker} has earnings within 1 day (days_to_earnings {days_to_earnings})"
MSG_PROMPT_VERSION_MUST_BE_TEXT = "prompt_version must be text"
MSG_EVIDENCE_PUBLISHED_AFTER_MADE_AT = "evidence published after made_at {made_at}: {late}"
MSG_MISSING_FIELD = "missing {field}"
MSG_MADE_AT_IS_NOT_A_TIMESTAMP = "made_at is not a timestamp ({made_at!r})"
