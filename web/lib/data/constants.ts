// The shared API data layer (session B4, docs/ws/b4.md): constants of the /api/v1 read routes. Not secrets.
// The Python side mirrors FRESH_MINUTES and the serve modes in scripts/marketbrief/constants/warehouse.py.

export const MARKETS = ["india", "us"] as const;
export type Market = (typeof MARKETS)[number];

/** A ticker as the contract allows it (api/openapi.yaml Ticker). */
export const TICKER_PATTERN = /^[A-Z0-9.&-]{1,20}$/;
/** An rm table name (the table comes from the page's own constant, never from input; checked anyway). */
export const TABLE_PATTERN = /^[a-z_]{1,40}$/;
/** A page_key: `_`, a ticker, a strategy id or `<ticker>:<date>` (the read is parameterised either way). */
export const PAGE_KEY_PATTERN = /^[A-Za-z0-9._:&-]{1,80}$/;
export const MARKET_PAGE_KEY = "_";

/** A page older than this is stale: two missed 4-hourly news syncs (ARCHITECTURE.md section 11). */
export const FRESH_MINUTES = 480;
/** The data cache's safety net; the sync revalidates changed pages by tag (ARCHITECTURE.md section 7). */
export const CACHE_REVALIDATE_SECONDS = 86400;
/** The read-model columns, in the order of every keyed SELECT. */
export const READ_MODEL_COLUMNS =
  "market, page_key, as_of, cutoff, built_at, schema_version, source_commit, payload_sha256, payload";
/** The major version of api/openapi.yaml this app serves; a stored row of another major version is refused (503). */
export const CONTRACT_MAJOR = "1";
/** The static reports site (config/settings.yaml pages_url): its pages work without the warehouse. */
export const REPORTS_URL = "https://agentic-stock-prediction-reports.vercel.app";
/** Problem.fallback_links of a market: its static dashboard and its report index. */
export function fallbackLinks(market: string): string[] {
  return [`${REPORTS_URL}/${market}/dashboard.html`, `${REPORTS_URL}/${market}/index.html`];
}

/** How a route serves a stored row (scripts/marketbrief/warehouse/contract.py `serve`). */
export type ServeMode = "verbatim" | "page" | "status";

export function cacheTag(table: string, market: string, pageKey: string): string {
  return `rm:${table}:${market}:${pageKey}`;
}
