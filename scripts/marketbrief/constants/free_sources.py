"""Constants and messages of the free-source collectors (macro, shorts, India flows)."""
# ---------- macro ----------
COLLECTOR_MACRO = "macro"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
CBOE_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{day}_daily_options"
MACRO_VALUE_COLUMNS = ["value", "complete"]
HEADERS_CSV = {"Accept": "text/csv"}
HEADERS_HTML = {"Accept": "text/html"}
HEADERS_JSON_POST = {"Content-Type": "application/json", "Accept": "application/json"}
SOURCE_TREASURY, SOURCE_FRED, SOURCE_CBOE = "treasury", "fred", "cboe"
UNIT_PERCENT, UNIT_RATIO = "pct", "ratio"
TENOR_PATTERN = r"\s*(\d+(?:\.\d+)?)\s*(Mo|Month|Months|Yr|Year|Years)\s*"
TREASURY_DATE_FORMAT = "%m/%d/%Y"
TREASURY_DATE_COLUMN = "Date"
FRED_DATE_COLUMNS = ("observation_date", "DATE")
DEFAULT_MACRO_LOOKBACK_DAYS = 30
DEFAULT_CBOE_LOOKBACK_DAYS = 7
DEFAULT_MACRO_PAUSE_SECONDS = 1.0
YIELD_CURVE_PREVIEW = 80

MSG_SKIPPED_NO_MACRO = "no `macro:` section in this market's config"
MSG_NOT_YIELD_CSV = "not the yield-curve CSV: {preview!r}"
MSG_NO_YIELD_ROWS = "no yield-curve rows in the last {days} days"
MSG_TREASURY_NOTE = "treasury: {count} values, latest {latest}"
MSG_NO_FRED_VALUES = "no values in the last {days} days"
MSG_CBOE_NOT_YET = "cboe: no file for {day} yet (HTTP {status}); published after the close"
MSG_CBOE_RATIOS_MISSING = "ratios missing from the file: {missing}"

# ---------- shorts ----------
COLLECTOR_SHORTS = "shorts"
VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day:%Y%m%d}.txt"
SHORT_INTEREST_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
SHORT_INTEREST_FIELDS = ["settlementDate", "symbolCode", "currentShortPositionQuantity",
                         "previousShortPositionQuantity", "averageDailyVolumeQuantity", "daysToCoverQuantity",
                         "changePercent", "revisionFlag"]
SHORTS_VALUE_COLUMNS = ["short_volume", "short_exempt_volume", "total_volume", "complete"]
SHORT_INTEREST_VALUE_COLUMNS = ["short_interest", "avg_daily_volume", "days_to_cover"]
SOURCE_FINRA_VOLUME, SOURCE_FINRA_INTEREST = "finra_short_volume", "finra_short_interest"
SOURCE_FINRA_REGSHO = "finra_regsho_cnms"
VOLUME_HEADER_PREFIX = "Date|Symbol|ShortVolume"
VOLUME_MIN_FIELDS = 5
DEFAULT_VOLUME_LOOKBACK_DAYS = 10
DEFAULT_INTEREST_LOOKBACK_DAYS = 45
DEFAULT_SHORTS_PAUSE_SECONDS = 0.5
SHORT_INTEREST_LIMIT = 5000

MSG_SKIPPED_NO_SHORTS = "no `shorts:` section in this market's config"
MSG_UNEXPECTED_HEADER = "unexpected header: {preview}"
MSG_EMPTY_FILE = "empty file"
MSG_NO_TRAILER = "no row-count trailer (file may be truncated)"
MSG_TRAILER_MISMATCH = "trailer says {trailer} rows, file has {rows} (truncated?)"
MSG_FILE_WRONG_DATE = "file for {day} holds date {found}"
MSG_FINRA_NOT_YET = "shorts: no FINRA file for {day} yet (HTTP {status}); published after the close"
MSG_NO_TICKER_ROWS = "no row for watchlist tickers {missing}"
MSG_NO_INTEREST_ROWS = "no rows for the watchlist in the last {days} days (settlements are twice a month)"
MSG_INTEREST_SETTLEMENT_MISSING = "settlement {latest}: no row for watchlist tickers {missing}"
MSG_INTEREST_NOTE = "short_interest: {count} rows, settlements {settlements}"

# ---------- India flows ----------
COLLECTOR_FLOWS_INDIA = "flows_india"
FPI_URL = "https://fpi.nsdl.co.in/web/Reports/Latest.aspx"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{day:%d%m%Y}.csv"
FPI_VALUE_COLUMNS = ["gross_purchases_cr", "gross_sales_cr", "net_cr"]
INDEX_VALUE_COLUMNS = ["close", "pe", "pb", "div_yield", "complete"]
SOURCE_NSDL_FPI, SOURCE_NSE_INDICES = "nsdl_fpi", "nse_indices"
SOURCE_NSDL_FPI_DAILY, SOURCE_NSE_IND_CLOSE = "nsdl_fpi_daily", "nse_ind_close_all"
FPI_TITLE_PATTERN = r"Daily Trends in FPI Investments on (\d{2}-[A-Za-z]{3}-\d{4})"
FPI_DERIVATIVE_TITLE = "Daily Trends in FPI Derivative"
FPI_DATE_FORMAT = "%d-%b-%Y"
INDEX_DATE_FORMAT = "%d-%m-%Y"
FPI_ASSET_EQUITY, FPI_ASSET_TOTAL, FPI_ROUTE_SUBTOTAL, FPI_ROUTE_TOTAL = "Equity", "Total", "sub-total", "total"
FPI_FULL_ROW_CELLS, FPI_ASSET_ROW_CELLS, FPI_ROUTE_ROW_CELLS = 8, 6, 5
BAD_ROW_PREVIEW = 120
DEFAULT_INDEX_LOOKBACK_DAYS = 7
DEFAULT_FLOWS_PAUSE_SECONDS = 1.0

MSG_SKIPPED_NO_FLOWS = "no `india_flows:` section in this market's config"
MSG_FPI_TITLE_MISSING = "report title 'Daily Trends in FPI Investments on <date>' not found (layout changed?)"
MSG_FPI_BAD_ROWS = "{count} table rows with unreadable numbers: {rows}"
MSG_FPI_NO_TOTALS = "parsed {count} rows without an Equity sub-total and a Total line (layout changed?)"
MSG_FPI_NOTE = "fpi: report {reporting}, {count} rows"
MSG_FPI_EQUITY_NET = ", equity net {net:+,.2f} cr"
MSG_FPI_NO_EQUITY = ", no equity sub-total"
MSG_INDEX_FILE_DATES = "file for {day} holds {served}"
MSG_INDEX_NOT_YET = "indices: no NSE index file for {day} yet (HTTP {status}); published after the close"
MSG_INDEX_MISSING = "configured indices not in the file: {missing}"
REFETCH_SESSIONS = 3   # an incomplete day is fetched again only while among the last 3 sessions (collector_store.py)
