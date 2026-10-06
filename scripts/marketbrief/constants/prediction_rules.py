"""Constants of the prediction record rules (CLAUDE.md prediction rules)."""
HORIZONS = (1, 5)
CONF_MIN, CONF_MAX, WIDEN_MAX, RATIONALE_WORDS = 0.50, 0.90, 0.5, 40
REQUIRED = ("id", "as_of_date", "ticker", "horizon_days", "direction", "confidence", "rationale",
            "evidence_ids", "prompt_version")
DEFAULT_AS_OF_LABEL = "the latest price date"
DEFAULT_EVIDENCE_LABEL = "the stored news/filings/announcements"
