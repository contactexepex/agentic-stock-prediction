"""Constants and messages of the decision-support dashboard (scripts/dashboard.py,
marketbrief/presentation/dashboard/). Research only: the page never places or suggests a trade."""

from __future__ import annotations

DASHBOARD_FILE = "dashboard.html"
DASHBOARD_STEP = "dashboard"
SLACK_FILES_MANIFEST = "work/slack_{market}_files.json"  # written by html_report.py; the dashboard adds its path
MANIFEST_KEY = "dashboard"

BAR_CALENDAR_DAYS = 380  # OHLC history embedded per ticker (enough for the 1-year span)
NEWS_PER_TICKER = 10  # latest headlines per ticker
NEWS_CANDIDATES = 30  # rows read per ticker before same-title copies are dropped
# Horizon names (the horizon list itself comes from config/strategies.yaml via core.horizons.horizons()):
# an N+k row (buy at the open of D, sell at the close of D+k) is "N+k"; a row of an old window keeps the wording the
# page used before B10, so the two are never shown under one name (core/horizons.py, docs/SPEC.md decision 37).
NAME_N_PLUS_K = "N+{h}"
NAME_N_PLUS_K_MODEL = "N+{h}: sell at the close of D+{h}"
NAME_LEGACY_MODEL = {1: "Buy today, sell tomorrow"}  # else "Buy today, sell within {h} days"
NAME_LEGACY_MODEL_OTHER = "Buy today, sell within {h} days"
NAME_LEGACY_RANGE = {1: "Next session"}  # else "{h} sessions"
NAME_LEGACY_RANGE_OTHER = "{h} sessions"
NAME_LEGACY_CALLS = {1: "1 day"}  # else "{h} days"
NAME_LEGACY_CALLS_OTHER = "{h} days"
NAME_LEGACY_REPLAY = "{h} day"  # the replay record's per-horizon fields (cover80_<h>d, ...)
SPANS = (("1W", "1 week", 7), ("1M", "1 month", 31), ("3M", "3 months", 92), ("1Y", "1 year", 366))
DEFAULT_SPAN = "3M"
EARNINGS_TYPE = "earnings"
CUE_ROLES = ("cue", "factor")
INDICATOR_COLUMNS = (
    "rsi_14",
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "atr_pct",
    "volume_ratio_20d",
    "ema_ratio",
    "price_vs_20d_high",
    "realized_vol_10d",
    "bb_width",
    "beta_1y",
    "rel_sector_5d",
)

VENDOR_DIR = "vendor"
VENDOR_JS = "lightweight-charts.standalone.production.js"
VENDOR_NOTICE = "NOTICE"
ASSET_DIR = "assets"
ASSET_TEMPLATE = "page.html"
ASSET_CSS = "dashboard.css"
ASSET_JS = ("dashboard.js", "overview.js", "chart.js", "stock.js", "track.js", "how.js")  # in load order
APP_BOOT = "window.MB.boot();"

# Placeholders of the page template (assets/page.html).
SLOT_TITLE, SLOT_CSS, SLOT_LIB, SLOT_APP, SLOT_DATA = "__TITLE__", "__CSS__", "__LIB__", "__APP__", "__DATA__"

MSG_PAPER_ONLY = "Paper only — no proven edge yet"
MSG_SKILL_SHOWN = "The weekly review found skill in the backtest; still research only"
MSG_RESEARCH_ONLY = "Research only, not investment advice."
MSG_NOT_AVAILABLE = "not available yet"
MSG_NO_REVIEW = (
    "No weekly review stored yet, so the model's skill has not been checked: treat every signal as paper only."
)
MSG_NO_DATA = "No indicator snapshot stored for {market} yet: run the routine first."
MSG_SKILL_RULE = (
    "Skill means: at least {min_n} out-of-sample rows, a Brier skill above {min_brier_skill} "
    "against the base rate, and an AUC 95% interval whose low end is above {min_auc_low} "
    "(config/review.yaml model_skill)."
)
SKILL_PAPER, SKILL_SHOWN = "paper", "shown"
