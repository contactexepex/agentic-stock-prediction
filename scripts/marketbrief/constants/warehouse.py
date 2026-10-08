"""Names, settings keys and messages of the warehouse sync (WS1, docs/ws/ws1.md)."""

from __future__ import annotations

FILE_WAREHOUSE_CONFIG = "warehouse.yaml"
PROVIDER_MOTHERDUCK = "motherduck"
PROVIDER_LOCAL = "local"
MOTHERDUCK_PREFIX = "md:"
WAREHOUSE_STEP = "warehouse_sync"
SUMMARY_DIR = "work/warehouse"

META_SCHEMA = "meta"
SYNC_RUNS_TABLE = "sync_runs"
READ_MODEL_SCHEMA = "rm"
# page type -> read-model table in schema rm (docs/ARCHITECTURE.md 4.1)
RM_OVERVIEW = "overview"
RM_WATCHLIST = "watchlist"
RM_STOCK = "stock"
RM_BARS = "bars"
RM_TRACK_RECORD = "track_record"
# the rm tables are those of the registered builders (warehouse/rm_registry.tables())
BUILDS_TABLE = "builds"  # rm.builds: one row per build, append-only
MARKET_PAGE_KEY = "_"  # the page_key of market-level pages
BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
UNKNOWN_COMMIT = "unknown"

# ---- B4: the read-model framework (warehouse/rm_registry.py, rm_common.py, contract.py; docs/ws/b4.md) ----
RM_MODULE_PREFIX = "rm_"  # warehouse/rm_<page>.py modules declare BUILDERS and CONTRACT_CASES
MSG_DUPLICATE_TABLE = "read models: table {table!r} is built by two modules (owners {owners})"
# How a route serves a stored row (warehouse/contract.serve, web/lib/data/serve.ts):
SERVE_VERBATIM = "verbatim"  # 1.0 pages: the payload as stored
SERVE_PAGE = "page"  # 2.0 page payloads: plus cutoff and built_at at the top and status.freshness
SERVE_STATUS = "status"  # the status page: plus freshness at the top
FRESH_MINUTES = 480  # a page older than this is stale (two missed 4-hourly news syncs; web/lib/data/constants.ts)
FRESHNESS_FRESH, FRESHNESS_STALE, FRESHNESS_UNKNOWN = "fresh", "stale", "unknown"
RM_STATUS = "status"
# The registry's reference rule strategy (config/strategies.yaml: the rule set differs from it in one parameter
# each); the go-live block every page carries is its accuracy row, all horizons, forward basis.
REFERENCE_STRATEGY = "rule.model_news.v1"
DEFAULT_HORIZON = 1  # Home and the pages open on N+1 (decision 39)
# Local start times of the scheduled runs (docs/SPEC.md section 7; the status block's next_at)
POST_CLOSE_LOCAL = {"india": "17:45", "us": "18:15"}
STRATEGY_FIELDS = (
    "id",
    "family",
    "name",
    "description",
    "compared_to",
    "differs_in",
    "parameters",
    "threshold",
    "horizons",
    "live_from",
    "live",
    "settled_trades",
)
GO_LIVE_FIELDS = ("proven", "months_forward", "trades_needed", "beats_best_baseline")
# The app's cache revalidation after a sync (warehouse/revalidate.py; web/lib/data/revalidate.ts)
ENV_REVALIDATE_SECRET = "REVALIDATE_SECRET"
ENV_VERCEL_BYPASS = "VERCEL_AUTOMATION_BYPASS_SECRET"
REVALIDATE_PATH = "/api/v1/internal/revalidate"
REVALIDATE_BATCH = 200  # api/openapi.yaml RevalidateRequest maxItems
REVALIDATE_TIMEOUT_SECONDS = 20
MSG_REVALIDATE_LOCAL = "skipped: the local warehouse file has no app cache"
MSG_REVALIDATE_NO_SECRET = "skipped: {env} is not set"
MSG_REVALIDATE_FAILED = "failed: {reason} (the pages refresh at the daily safety-net revalidate)"

KIND_DAILY = "daily"
KIND_NEWS = "news"
KIND_FULL = "full"
MODE_REPLACE = "replace"
MODE_FULL = "full"
MODE_DRY_RUN = "dry_run"

REDACTED = "***"

# The MotherDuck extension, installed over HTTPS only (marketbrief/warehouse/extension.py)
EXTENSION_HOSTS = ("extensions.duckdb.org", "ext.motherduck.com")
LOADER_URL = "https://extensions.duckdb.org/{duckdb_version}/{platform}/motherduck.duckdb_extension.gz"
IMPLEMENTATION_URL = "https://ext.motherduck.com/{duckdb_version}/{platform}/motherduck_impl.{implementation_version}.duckdb_extension.gz"
IMPLEMENTATION_FILE = "motherduck_impl.{implementation_version}.duckdb_extension"
LOADER_FILE = "motherduck.duckdb_extension"
ENV_IMPLEMENTATION_VERSION = "MOTHERDUCK_EXT_VERSION"  # read by the loader: use this implementation, fetch nothing
EXTENSION_USER_AGENT = "market-brief/1.0 (personal research; warehouse sync)"
EXTENSION_TIMEOUT_SECONDS = 120
EXTENSION_ATTEMPTS = 2

MSG_TOKEN_MISSING = (
    "warehouse: the environment variable {env} is not set; set it to sync to MotherDuck, "
    "or pass --local to write the local DuckDB file instead"
)
MSG_BAD_PROVIDER = "warehouse: provider must be motherduck or local, not {provider!r} (config/warehouse.yaml)"
MSG_BAD_NAME = "warehouse: database name must be letters, digits and underscores, not {name!r}"
MSG_SYNC_FAILED = "warehouse sync failed for {market}: {error}"
MSG_INVALID_PAGE = "{table}/{page_key}: {problems}"
MSG_DISABLED = "skipped: warehouse disabled in config/warehouse.yaml (enabled: false)"
MSG_OVER_CEILING = (
    "skipped: this month's sync wall time {hours:.2f} h in meta.sync_runs reached monthly_hours_ceiling {ceiling} h"
)
MSG_EXTENSION_URL_REFUSED = "warehouse: refused extension URL {url}: HTTPS on " + ", ".join(EXTENSION_HOSTS) + " only"
MSG_EXTENSION_DOWNLOAD_FAILED = "warehouse: downloading {url} failed: {reason}"
MSG_DUCKDB_VERSION_MISMATCH = (
    "warehouse: DuckDB is {installed} but config/warehouse.yaml pins the MotherDuck extension for {pinned}; "
    "install the duckdb version pinned in requirements.txt"
)
