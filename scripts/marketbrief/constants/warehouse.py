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
# the info.version of api/openapi.yaml the payloads conform to (docs/ARCHITECTURE.md 4.1)
READ_MODEL_SCHEMA_VERSION = "1.0.0"
# page type -> read-model table in schema rm (docs/ARCHITECTURE.md 4.1)
RM_OVERVIEW = "overview"
RM_WATCHLIST = "watchlist"
RM_STOCK = "stock"
RM_BARS = "bars"
RM_TRACK_RECORD = "track_record"
READ_MODEL_TABLES = (RM_OVERVIEW, RM_WATCHLIST, RM_STOCK, RM_BARS, RM_TRACK_RECORD)
BUILDS_TABLE = "builds"  # rm.builds: one row per build, append-only
MARKET_PAGE_KEY = "_"  # the page_key of market-level pages
BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
# required top-level keys of each payload (api/openapi.yaml components; tests compare when the spec is present)
REQUIRED_KEYS = {
    RM_OVERVIEW: ("market", "name", "currency", "as_of", "disclaimer", "skill", "overview"),
    RM_WATCHLIST: ("market", "as_of", "skill", "rows"),
    RM_STOCK: (
        "ticker",
        "name",
        "sector",
        "as_of",
        "skill",
        "last",
        "ranges",
        "model",
        "reasoning",
        "calls",
        "news",
        "earnings",
        "indicators",
    ),
    RM_BARS: ("ticker", "as_of", "columns", "bars", "ranges"),
    RM_TRACK_RECORD: ("skill", "calls", "ranges", "replay", "min_sample"),
}
WATCHLIST_ROW_REQUIRED = ("ticker", "name", "sector", "last", "model", "calls", "ranges")
UNKNOWN_COMMIT = "unknown"

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
IMPLEMENTATION_URL = (
    "https://ext.motherduck.com/{duckdb_version}/{platform}/motherduck_impl.{implementation_version}.duckdb_extension.gz"
)
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
MSG_INVALID_PAGE = "{table}/{page_key}: missing {missing}"
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
