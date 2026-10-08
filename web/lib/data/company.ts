// The company pages' reads (session B12, docs/ws/b12.md; api/paths/company.yaml): one keyed read per request.
//   GET /api/v1/markets/{market}/stocks/{ticker}             rm.stock            (03-company, serve page)
//   GET /api/v1/markets/{market}/stocks/{ticker}/bars        rm.bars             (verbatim)
//   GET /api/v1/markets/{market}/stocks/{ticker}/strategies  rm.stock_strategies (04-stock-strategies, serve page)
//   GET /api/v1/markets/{market}/trades[?ticker=]            rm.trades           (page `_` or the ticker, verbatim)
//   GET /api/v1/markets/{market}/stocks/{ticker}/lifecycle/{date}  rm.lifecycle  (page `<ticker>:<date>`, verbatim)
import { MARKET_PAGE_KEY } from "./constants.ts";
import { definePage, isTicker, readPage, readTickerPage, type ReadDeps } from "./handler.ts";
import { notFound } from "./problem.ts";

export const COMPANY_PAGE = definePage({ table: "stock", serve: "page" });
export const COMPANY_BARS = definePage({ table: "bars", serve: "verbatim" });
export const STOCK_STRATEGIES_PAGE = definePage({ table: "stock_strategies", serve: "page" });
export const TRADES_PAGE = definePage({ table: "trades", serve: "verbatim" });
export const LIFECYCLE_PAGE = definePage({ table: "lifecycle", serve: "verbatim" });

/** A session date as the contract writes it (IsoDate). */
const SESSION_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** GET /trades: the market's page, or one company's when the query names a ticker. */
export function tradesResponse(request: Request, market: string, deps: ReadDeps): Promise<Response> {
  const ticker = new URL(request.url).searchParams.get("ticker");
  return ticker === null
    ? readPage(request, TRADES_PAGE, market, MARKET_PAGE_KEY, deps)
    : readTickerPage(request, TRADES_PAGE, market, ticker, deps);
}

/** GET /stocks/{ticker}/lifecycle/{date}: one session's page `<ticker>:<date>`; a day older than the stored 30
 *  sessions (or not a session) has no page, so 404. */
export function lifecycleResponse(
  request: Request, market: string, ticker: string, day: string, deps: ReadDeps,
): Promise<Response> {
  if (!isTicker(ticker)) return Promise.resolve(notFound("Unknown ticker"));
  if (!SESSION_DATE.test(day)) return Promise.resolve(notFound("Unknown session date"));
  return readPage(request, LIFECYCLE_PAGE, market, `${ticker}:${day}`, deps);
}
