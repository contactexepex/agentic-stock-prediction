"""Constants and messages of the NSE collectors (relations and primary sources) and of their replay guard."""
# ---------- replay guard ----------
SCRATCH_MARKER = ".scratch-ok"
REPO_MARKERS = (".git", "CLAUDE.md")
PRICE_FILES_GLOB = "*/prices/**/*"
MSG_NO_SCRATCH_MARKER = "no {marker} marker file in MB_ROOT ({root}); create it to mark a scratch root"
MSG_ROOT_LOOKS_LIKE_REPO = "MB_ROOT ({root}) contains {marker}: looks like a repo checkout"
MSG_ROOT_HAS_PRICES = "MB_ROOT ({root}) has price files under data/*/prices: looks like a real data store"
MSG_TARGET_OUTSIDE_ROOT = "write target {target} resolves to {resolved}, outside {base} (symlink?)"
MSG_TARGET_IN_CHECKOUT_DATA = "write target {target} resolves into this checkout's data/ ({real})"
MSG_TARGET_IN_REPO = "write target {target} resolves into a repo checkout ({parent})"
MSG_TARGET_HARD_LINKED = "write target {target} is hard-linked ({links} links); replay never appends to it"
MSG_TARGET_SAME_FILE = "write target {target} is the same file as one in this checkout's data/"
MSG_REPLAY_REFUSED = "--replay writes synthetic rows; refusing: {problem}"
MSG_TODAY_NEEDS_REPLAY = "--today is only allowed with --replay"
MSG_SKIPPED_NO_NSE = "no `relations.source: nse` in this market's config"
EXIT_REPLAY_REFUSED = 2

# ---------- runner ----------
SEEN_LOOKBACK_DAYS = 400
SINCE_WINDOW_DAYS = 7   # --since backfills ask date-range endpoints one week at a time (smaller answers)
NSE_DATE_ARGUMENT = "%d-%m-%Y"
MSG_ENDPOINT_EMPTY = ("{source}: endpoint returned no rows at all (not just none for the watchlist); "
                      "check it is still live")
MSG_ROWS_RETURNED = "{source}: {total} rows returned"
MSG_ROWS_FOR_WATCHLIST = ", {matched} for watchlist tickers"
MSG_SINCE_HELP = ("backfill: ask the date-range endpoints from this date to today in one-week windows "
                  "instead of the configured lookback (default: the lookback, unchanged)")
MSG_REPLAY_HELP = ("read responses from files in this directory instead of NSE (offline tests and "
                   "debugging; writes only to a scratch MB_ROOT that holds a .scratch-ok file)")
MSG_ONLY_HELP = "collect only these kinds (repeatable)"
MSG_TODAY_HELP = "with --replay only: the collection date the saved responses belong to (YYYY-MM-DD)"
DEFAULT_SYMBOL_CALLS_PER_RUN = 10
DEFAULT_PER_TICKER_FILINGS = 4
SEEN_KEEP_QUARTERS = 4   # shareholding periods kept per ticker on a first fetch (enough for q/q changes)

# ---------- relations (insiders, deals, holdings) ----------
COLLECTOR_RELATIONS = "relations_india"
RELATION_KINDS = ["insiders", "deals", "holdings"]
DEFAULT_INSIDER_LOOKBACK_DAYS = 14
DEFAULT_DEAL_LOOKBACK_DAYS = 5
BACKFILL_CAP_ROWS = 70
SOURCE_PIT, SOURCE_SHAREHOLDING, SOURCE_PLEDGE = "nse_pit", "nse_shp", "nse_pledge"
SOURCE_SNAPSHOT, SOURCE_ARCHIVE, SOURCE_HISTORICAL = "nse_snapshot", "nse_archive", "nse_historical"
DEAL_TYPES = ("bulk", "block")
PIT_ID_PREFIX, SHP_ID_PREFIX, PLEDGE_ID_PREFIX = "nse-pit-", "nse-shp", "nse-pledge"
ENDPOINT_PIT, ENDPOINT_DEAL_SNAPSHOT = "corporates-pit-gg", "snapshot-capital-market-largedeal"
ENDPOINT_DEAL_HISTORY = "historicalOR/bulk-block-short-deals"
ENDPOINT_SHAREHOLDING, ENDPOINT_PLEDGE = "corporate-share-holdings-master", "corporate-pledgedata"
NO_RECORDS = "NO RECORDS"
MSG_PIT_LABEL_DAYS = "{lookback} days"
MSG_PIT_LABEL_SINCE = "since {since}, {windows} weekly calls"
MSG_PIT_COVERAGE = "insiders: PIT filings index ({label})"
MSG_NO_XBRL = "filing has no XBRL file"
MSG_DEALS_COVERAGE = "deals: bulk+block snapshot as on {as_on}"
MSG_DEALS_ARCHIVE_NOTE = "deals: {deal_type}.csv archive has {rows} rows, {watchlist} for watchlist tickers"
MSG_DEALS_CAP = "{deal_type} backfill for {symbol} hit NSE's 70-row cap; older deals may be missing"
MSG_DEALS_BACKFILL_NOTE = "deals backfill: {calls} per-ticker calls since {since}, {found} rows returned"
MSG_HOLDINGS_POLLED = "holdings {source}: {count} ticker(s) polled for quarter {quarter}"
MSG_HOLDINGS_NO_ROWS = "holdings {source}: no rows for {ticker}"
MSG_HOLDINGS_CALLS = "holdings {source}: {count} per-ticker calls"
MSG_DEALS_BACKFILL_HELP = "also query bulk/block deals per ticker for the last DAYS days (2 calls per ticker)"
MSG_FULL_RELATIONS_HELP = "poll every ticker that misses the latest quarter (no per-run cap)"

# ---------- primary sources (announcements, financials, flows, delivery) ----------
COLLECTOR_NSE_INDIA = "nse_india"
NSE_KINDS = ["announcements", "financials", "flows", "delivery"]
DEFAULT_ANNOUNCEMENT_LOOKBACK_DAYS = 2
DEFAULT_DELIVERY_LOOKBACK_DAYS = 5
SOURCE_ANNOUNCEMENTS, SOURCE_FIIDII, SOURCE_BHAVCOPY = "nse_announcements", "nse_fiidii", "nse_bhavcopy"
ENDPOINT_ANNOUNCEMENTS, ENDPOINT_INTEGRATED, ENDPOINT_FLOWS = (
    "corporate-announcements", "integrated-filing-results", "fiidiiTradeReact")
INTEGRATED_TYPE = "Integrated Filing- Financials"
FINANCIAL_ID_PREFIX = "nse-fin-"
DELIVERY_ID_PREFIX = "nse-dlv-"
DELIVERY_SEEN_DAYS = 60
BHAVCOPY_PATH = "/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"
PUBLISHED_HOUR_IST = 19   # today's bhavcopy is not published before this hour (IST)
WEEKEND_FIRST_DAY = 5
MSG_ANNOUNCEMENTS_COVERAGE = "announcements ({label})"
MSG_FINANCIALS_POLLED = "financials: {count} ticker(s) polled for quarter {quarter}"
MSG_FINANCIALS_NONE_LISTED = "financials: no integrated filings listed for {ticker}"
MSG_FINANCIALS_CALLS = "financials: {count} per-ticker index calls"
MSG_FLOWS_COVERAGE = "flows: FII/DII report"
MSG_DELIVERY_MISSING = "delivery: no bhavcopy for {day} ({error}); holiday or not yet published"
MSG_DELIVERY_HOLIDAY = "delivery: file for {day} holds {served} (holiday); ids use the file's date"
MSG_DELIVERY_COVERAGE = "delivery: bhavcopy {day}"
MSG_FULL_NSE_HELP = "poll every ticker missing the latest quarter and parse all its listed filings"
DELIVERY_ERROR_LIMIT = 40
