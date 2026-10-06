"""Labels, cutoff rules, publication-time rules and backfill steps of the AI replay (ai_replay.py)."""

from __future__ import annotations

from datetime import date, time, timedelta

FAIR, CONTAMINATED = "fair", "contaminated"  # ForecastBench leakage rule (see the docstring)

SAMPLE_START, SAMPLE_END, SAMPLE_STEP = date(2026, 7, 1), date(2026, 9, 25), 5

# The data cutoff (and made_at) is the routine's scheduled start on the next session, exchange time
# (docs/DESIGN.md section 2); other markets: REGULAR_LEAD before the open.
CUTOFF_LOCAL = {"india": time(8, 10), "us": time(8, 15)}

REGULAR_LEAD = timedelta(minutes=75)

MARKER = ".ai_replay_root"

EVIDENCE_KINDS = ("news", "filings", "announcements")  # ids a call may cite (CLAUDE.md: news/filing ids)

EVIDENCE_DAYS = 14

BANDS = (("0.50-0.59", 0.50, 0.60), ("0.60-0.69", 0.60, 0.70), ("0.70-0.90", 0.70, 0.9001))

# kind -> columns tried in order for when a row became public (first non-null wins).
# "x+1d" = the end of date column x in UTC (when no acceptance time is stored).
PUBLIC_AT: dict[str, list[str]] = {
    "filings": ["accepted_at", "filing_date+1d"],
    "fundamentals": ["accepted_at", "filing_date+1d"],
    "stakes": ["accepted_at", "filing_date+1d", "first_seen_at"],
    "insiders": ["accepted_at", "disclosed_at", "filing_date+1d", "first_seen_at"],
    "holdings": ["accepted_at", "filed_at", "filing_date+1d", "first_seen_at"],
    "announcements": ["published_at", "first_seen_at"],
    "financials": ["filed_at", "first_seen_at"],
    "predictions": ["made_at"],
    "ranges": ["made_at"],
    "outcomes": ["scored_at"],
    "range_outcomes": ["scored_at"],
    "lessons": ["available_from"],
    "features": ["computed_at"],
    "regime": ["computed_at"],
    "calibration": ["computed_at"],
    "reviews": ["computed_at"],
    "replays": ["computed_at"],
    "judgments": ["recorded_at"],
    "quotes": ["collected_at"],
    "options": ["collected_at"],
    "graph": ["added_at"],
    "graph_runs": ["run_at"],
    # SEC acceptance times from the filing's SGML header (check_sec_times.py): a permanent fact
    # about the filing, public from its acceptance; checked_at is only when we looked it up
    "sec_times": ["accepted_at"],
    # news verification phase A: an article row once fetched, a cluster row once computed (every
    # input of a cluster row is <= its as_of; news_clusters_asof() in sql/views.sql reads them)
    "news_articles": ["fetched_at"],
    "news_clusters": ["as_of"],
    "primary_texts": ["fetched_at"],
    "news_claims": ["extracted_at"],
    "news_verified": ["as_of"],  # phase B
}

FIRST_SEEN_ONLY = ("macro", "shorts", "short_interest", "fpi", "indices", "flows", "delivery")

# Bulk and block deals have only a trade date; NSE publishes each session's deals after its close,
# so a deal dated <= D was public before the next pre-open (an assumption, listed in the summary).
DATE_PUBLIC_AFTER_CLOSE = ("deals",)

for _kind in FIRST_SEEN_ONLY:
    PUBLIC_AT[_kind] = ["first_seen_at"]

# kinds public by one date column: a bar and its provenance row share the bar date, a split or bonus applies from
# its ex-date, and a day's bulk and block deals are public after that day's close
DATE_COLUMN_BY_KIND = {
    "prices": "date",
    "price_sources": "date",
    "adjustments": "ex_date",
    **dict.fromkeys(DATE_PUBLIC_AFTER_CLOSE, "date"),
}
TARGET_DATE_KINDS = ("outcomes", "range_outcomes", "lessons")  # also need target_date <= D

DROPPED = {
    "news": "stored news only starts when live collection began ({first}); no history before",
    "news_enriched": "AI enrichment of news (no news history before {first})",
}

SOURCE_MARKER = ".ai_replay_source"

# Collectors run into the scratch source, one after another (SEC: the shared 10 requests/s budget and
# the SEC_USER_AGENT contact; NSE: one polite session per collector, never two at once).
BACKFILL_STEPS = {
    "us": [("collect_filings.py",), ("collect_insiders.py",), ("collect_stakes.py",), ("collect_events.py",)],
    "india": [
        ("collect_nse_india.py", "--only", "announcements", "--only", "financials", "--since", "{since}"),
        ("collect_relations_india.py", "--only", "insiders", "--only", "deals", "--since", "{since}"),
        ("collect_events.py",),
    ],
}

BACKFILL_KINDS = {
    "us": ("filings", "insiders", "stakes", "events"),
    "india": ("announcements", "financials", "insiders", "deals", "events"),
}

# ---------- ai replay: roots ----------
MSG_SCRIPT_FAILED_IN_ROOT = "{script} failed in {root} (exit {returncode}):\n{error_output}"
MSG_ROOT_MUST_NOT_BE_THE_SOURCE = "--root {root} must not be the source root or inside its data/"
MSG_ROOT_MUST_NOT_CONTAIN_THE_SOURCE = "--root {root} must not contain the source root"
MSG_ROOT_NOT_EMPTY_AND_NOT_A_REPLAY_ROOT = (
    "--root {root} exists, is not empty and is not an ai_replay root; choose another path"
)
MSG_ROOT_ALREADY_HOLDS_A_PREPARED_REPLAY = "--root {root} already holds a prepared replay; pass --force to rebuild it"

# ---------- ai replay: backfill ----------
MSG_SOURCE_NOT_EMPTY_AND_NOT_A_REPLAY_SOURCE = (
    "--source {resolved} exists, is not empty and is not an ai_replay source; choose another path"
)
MSG_NO_BACKFILL_STEPS_FOR_MARKET = "no backfill steps for market {market}"
MSG_SINCE_MUST_BE_BEFORE_TODAY = "--since must be before today"
MSG_SOURCE_IS_THE_REPO = "--source {resolved} is the repo, its real data/ or contains them; use a scratch directory"
MSG_SOURCE_INSIDE_REAL_DATA = (
    "--source {resolved} is inside the real data/ of the checkout {parent}; use a scratch directory"
)

# ---------- ai replay: record ----------
MSG_NOT_A_PREPARED_ROOT = "{root} is not a prepared ai_replay root (run prepare first)"
MSG_ROOT_PREPARED_FOR_OTHER_DAY = (
    "{root} was prepared for {prepared_market} {prepared_as_of_date}, not {requested_market} {requested_as_of_day}"
)
MSG_DAY_ALREADY_RECORDED = (
    "{market} {as_of_day} is already recorded in {store_directory}; use a new --results directory to re-run it"
)

# ---------- ai replay: prepare ----------
MSG_DAY_IN_TRAINING_PERIOD = (
    "{as_of_day} is on or before the model's training cutoff {model_cutoff} (config/settings.yaml "
    "model_training_cutoff): contaminated, not a fair test. Pass --allow-training-period to prepare it "
    "anyway."
)
MSG_NOT_A_TRADING_DAY = "{as_of_day} is not a {market} trading day"
MSG_NO_BENCHMARK_BAR_FOR_DAY = "no {benchmark} bar dated {as_of_day} in {source_path} (latest kept: {latest_kept})"

# ---------- ai replay: score ----------
MSG_NOTHING_RECORDED = "nothing recorded in {store_directory}"

# ---------- ai replay: cutoff ----------
MSG_NO_MODEL_TRAINING_CUTOFF = "{settings_path} has no model_training_cutoff (YYYY-MM-DD)"

MSG_NOT_JSON = "not JSON: {error}"
