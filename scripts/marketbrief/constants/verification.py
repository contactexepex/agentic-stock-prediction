"""News verification, phase B: data kinds, statuses, claim enums and the forecast-gate failure codes."""

KIND_NEWS_CLAIMS = "news_claims"
KIND_NEWS_VERIFIED = "news_verified"
KIND_PRIMARY_TEXTS = "primary_texts"
KIND_NEWS_CLUSTERS = "news_clusters"
KIND_NEWS_ARTICLES = "news_articles"

METHOD_VERSION_CLAIMS = "nv-b1"
METHOD_VERSION_STATUS = "nv-b1"

# Status precedence, highest first (docs/DESIGN.md section 3b). `unverified`: no verified origin and
# no primary confirmation, and every news id on days before the feature (never back-filled).
STATUS_CONTRADICTED = "contradicted"
STATUS_CONFIRMED_PRIMARY = "confirmed_primary"
STATUS_CORROBORATED = "corroborated"
STATUS_RUMOUR = "rumour"
STATUS_PROMOTIONAL = "promotional"
STATUS_SINGLE_SOURCE = "single_source"
STATUS_UNVERIFIED = "unverified"
STATUS_PRECEDENCE = (STATUS_CONTRADICTED, STATUS_CONFIRMED_PRIMARY, STATUS_CORROBORATED, STATUS_RUMOUR,
                     STATUS_PROMOTIONAL, STATUS_SINGLE_SOURCE, STATUS_UNVERIFIED)

# What a status may do in a call (forecaster.md; prediction_rules.check_news_status).
MAIN_EVIDENCE_STATUSES = (STATUS_CONFIRMED_PRIMARY, STATUS_CORROBORATED)
NEVER_SUPPORT_STATUSES = (STATUS_RUMOUR, STATUS_PROMOTIONAL)
WIDEN_ONLY_STATUSES = (STATUS_CONTRADICTED,)
WEAK_STATUSES = (STATUS_SINGLE_SOURCE, STATUS_UNVERIFIED)
WEAK_CONFIDENCE_PENALTY = 0.05

LEVEL_CLUSTER = "cluster"
LEVEL_CLAIM = "claim"

# Flags of a status row
FLAG_MISMATCH_PRIMARY = "mismatch_primary"
FLAG_PRIMARY_WITHOUT_VALUE = "primary_without_value"
FLAG_UNIT_MISMATCH = "unit_mismatch"
FLAG_PRIMARY_DENIES = "primary_denies"
FLAG_OUTLET_VALUES_DISAGREE = "outlet_values_disagree"
FLAG_STANCES_DISAGREE = "stances_disagree"

# Claim record enums (claim-checker.md)
CLAIM_TYPES = ("earnings_guidance", "deal_ma", "regulatory_legal", "mgmt_change", "rating_target", "macro",
               "rumour", "opinion", "promotional")
ATTRIBUTIONS = ("on_record", "company_statement", "sources_say", "analyst", "opinion")
STANCES = ("affirms", "denies")
STANCE_AFFIRMS, STANCE_DENIES = STANCES
UNITS = ("usd", "inr", "eur", "gbp", "pct", "bps", "count")
CURRENCY_UNITS = ("usd", "inr", "eur", "gbp")
CLAIM_TYPE_RUMOUR, CLAIM_TYPE_OPINION, CLAIM_TYPE_PROMOTIONAL = "rumour", "opinion", "promotional"
ATTRIBUTION_SOURCES_SAY, ATTRIBUTION_OPINION = "sources_say", "opinion"

# Where a quote was found (computed by claims.py, never taken from the agent)
SOURCE_ARTICLE, SOURCE_FILING, SOURCE_ANNOUNCEMENT = "article", "filing", "announcement"
PRIMARY_SOURCE_KINDS = (SOURCE_FILING, SOURCE_ANNOUNCEMENT)
FIELD_EXTRACT, FIELD_TITLE, FIELD_PRIMARY = "extract", "title", "primary"

QUOTE_MAX_WORDS = 40
FACT_KEY_PATTERN = r"[a-z0-9][a-z0-9-]{0,39}"
RELATIVE_TOLERANCE = 0.01

# Forecast gate failure codes (validate.py --stage forecast; routine/PROMPT.md)
CODE_NEWS_STATUS_MAIN = "NEWS_STATUS_MAIN"
CODE_NEWS_STATUS_BLOCKED = "NEWS_STATUS_BLOCKED"
CODE_NEWS_STATUS_CONTRADICTED = "NEWS_STATUS_CONTRADICTED"
CODE_NEWS_STATUS_CONFIDENCE = "NEWS_STATUS_CONFIDENCE"
CODE_NEWS_STATUS_MISSING = "NEWS_STATUS_MISSING"
CODE_FORECAST_RULE = "FORECAST_RULE"
