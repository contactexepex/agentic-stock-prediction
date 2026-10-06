"""Exception and log messages (str.format templates) of the shared package and of the code moved into it.

Messages raised in more than one module have one constant here: MSG_UNREACHABLE, MSG_MARKET_REQUIRED,
MSG_NO_BENCHMARK_BARS_PERIOD, MSG_NO_PUBLISHED_RANGES."""

# ---------- shared by several modules ----------
MSG_UNREACHABLE = "unreachable"
MSG_MARKET_REQUIRED = "--market is required; available: {available}"
MSG_NO_BENCHMARK_BARS_PERIOD = "no benchmark bars; run collect_prices.py --period 2y first"
MSG_NO_PUBLISHED_RANGES = "no published ranges; run ranges.py first"

# ---------- core ----------
MSG_MB_NOW_NEEDS_OFFSET = "MB_NOW needs a UTC offset, e.g. 2026-07-02T12:15:00+00:00 (got {value!r})"
MSG_UNKNOWN_MARKET = "unknown market {name!r}; available: {available}"
MSG_SECTORS_ONLY_FOR_SECTOR_ETF = "symbol {symbol}: `sectors` is only for role sector_etf"
MSG_SECTOR_UNKNOWN = "symbol {symbol}: unknown sector {sector!r}"
MSG_SECTOR_MAPPED_TWICE = "sector {sector!r} is mapped to both {first} and {second}"

# ---------- free-source client ----------
MSG_FREE_SOURCE_HOST_SKIPPED = "not requested: {host} {why} earlier in this run"
MSG_FREE_SOURCE_HTTP_STATUS = "HTTP {code} from {host}"
MSG_FREE_SOURCE_PROXY_DENIED = "egress proxy denied {host}: {reason}"
MSG_FREE_SOURCE_CLOSED = ("{host} closed the connection without an HTTP answer {attempts} times "
                          "(site-side refusal; the proxy connected): {reason}")
MSG_FREE_SOURCE_UNREACHABLE = "{host} unreachable after {attempts} attempts: {reason}"
MSG_FREE_SOURCE_NOT_JSON = "not JSON: {preview!r}"
MSG_FREE_SOURCE_DEAD_PROXY = "was refused by the egress proxy"
MSG_FREE_SOURCE_DEAD_CLOSED = "closed the connection without an answer"

# ---------- NSE client ----------
MSG_NSE_HTTP_STATUS = "HTTP {code} from {host} (NSE refused or no such file)"
MSG_NSE_PROXY_DENIED = "egress proxy denied {host}: {reason}"
MSG_NSE_UNREACHABLE = "{host} unreachable after a retry: {reason}"
MSG_NSE_NOT_JSON = "not JSON (likely an NSE block page): {error}"
MSG_NSE_NO_REPLAY_FILE = "no replay file"

# ---------- SEC client ----------
MSG_SEC_FIXTURE_MISSING = "no fixture for {url}"
MSG_SEC_TIME_NO_FIXTURE = "no header fixture"
MSG_SEC_TIME_HEADER_FAILED = "header {accession}: {error}"
MSG_SEC_TIME_NO_HEADER_TIME = "no ACCEPTANCE-DATETIME in {accession}"
MSG_SEC_TIME_MISMATCH = "{accession} JSON {json_value} vs header {header}"
MSG_SEC_TIME_NO_ACCEPTANCE = "no acceptance time with an accession number"
MSG_SEC_TIME_MIXED_FILE = "mixed file (newest {newest} {newest_verdict}, oldest {oldest} {oldest_verdict})"
MSG_SEC_TIME_UNVERIFIED_WARNING = ("SEC acceptance times of CIK {cik} unverified, stored as served "
                                   "(maybe 4-5h late): {why}")
MSG_SEC_NOT_APPLICABLE = "no SEC filings for this market (the market's own collector covers it)"
MSG_SEC_USER_AGENT_MISSING = "SEC_USER_AGENT not set"

# ---------- Neo4j client ----------
MSG_NEO4J_HTTP_STATUS = "HTTP {code}: {detail}"
MSG_NEO4J_CONNECTION_FAILED = "connection failed: {reason}"
