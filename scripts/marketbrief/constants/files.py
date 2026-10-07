"""File and folder names, and text encodings."""
DIR_DATA = "data"
DIR_CONFIG_MARKETS = "markets"
DIR_SQL = "sql"
FILE_VIEWS_SQL = "views.sql"
FILE_RANGES_CONFIG = "ranges.yaml"
FILE_SETTINGS_CONFIG = "settings.yaml"
FILE_VALIDATE_CONFIG = "validate.yaml"
FILE_SEC_ACCEPTANCE_CACHE = "work/sec_acceptance.json"
ENCODING_UTF8 = "utf-8"
YAML_SUFFIX = ".yaml"
JSONL_GLOB = "**/*.jsonl"
FILE_NEWS_SOURCES_CONFIG = "news_sources.yaml"
# Issue #47: DuckDB's one read_csv over a glob silently drops every file whose line ending differs from the first
# file's, so all stored CSVs keep the CRLF that csv.writer writes (collectors/price_frames.py).
CSV_FORMAT = "csv"
CSV_LINE_ENDING = b"\r\n"
MSG_CSV_LINE_ENDINGS = (
    "{relative_path}: {bare} of {lines} lines end in a bare LF, not CRLF; DuckDB's glob read would drop this file "
    "from the price views (issue #47)"
)
