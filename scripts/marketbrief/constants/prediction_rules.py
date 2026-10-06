"""Constants of the prediction record rules (CLAUDE.md prediction rules)."""
HORIZONS = (1, 5)
CONF_MIN, CONF_MAX, WIDEN_MAX, RATIONALE_WORDS = 0.50, 0.90, 0.5, 40
REQUIRED = ("id", "as_of_date", "ticker", "horizon_days", "direction", "confidence", "rationale",
            "evidence_ids", "prompt_version")
DEFAULT_AS_OF_LABEL = "the latest price date"
DEFAULT_EVIDENCE_LABEL = "the stored news/filings/announcements"

# ---------- prediction rules ----------
MSG_UNKNOWN_TICKER = "unknown ticker {ticker!r}"
MSG_HORIZON_DAYS_MUST_BE_1_OR = "horizon_days must be 1 or 5 (got {horizon!r})"
MSG_AS_OF_DATE_IS_NOT = "as_of_date {as_of_date} is not {label} {want}"
MSG_ID_MUST_BE_AS_OF_DATE = ("id must be <as_of_date>-<ticker>-<horizon>d = {as_of_date}-{ticker}-{horizon}d (got "
                             "{id!r})")
MSG_ID_ALREADY_RECORDED = "id {id} already recorded"
MSG_DIRECTION_MUST_BE_UP_OR_DOWN = "direction must be up or down (got {direction!r})"
MSG_CONFIDENCE_MUST_BE_GOT = "confidence must be {conf_min:.2f}-{conf_max:.2f} (got {c!r})"
MSG_RANGE_WIDEN_MUST_BE_0_GOT = "range_widen must be 0-{widen_max} (got {w!r})"
MSG_RATIONALE_MUST_BE_TEXT_OF_AT = "rationale must be text of at most {rationale_words} words"
MSG_EVIDENCE_IDS_NOT_IN = "evidence ids not in {label}: {unknown}"
MSG_INDICATOR_QUALITY_IS_BLOCKED = "{ticker} indicator quality is BLOCKED"
MSG_HAS_EARNINGS_WITHIN_1_DAY_DAYS = "{ticker} has earnings within 1 day (days_to_earnings {days_to_earnings})"
MSG_PROMPT_VERSION_MUST_BE_TEXT = "prompt_version must be text"
MSG_EVIDENCE_PUBLISHED_AFTER_MADE_AT = "evidence published after made_at {isoformat}: {late}"
MSG_MISSING = "missing {k}"
MSG_MADE_AT_IS_NOT_A_TIMESTAMP = "made_at is not a timestamp ({made_at!r})"
