// The company pages' reads (session B12, docs/ws/b12.md; api/paths/company.yaml): one keyed read per request.
//   GET /api/v1/markets/{market}/stocks/{ticker}             rm.stock            (03-company, serve page)
//   GET /api/v1/markets/{market}/stocks/{ticker}/bars        rm.bars             (verbatim)
//   GET /api/v1/markets/{market}/stocks/{ticker}/strategies  rm.stock_strategies (04-stock-strategies, serve page)
//   GET /api/v1/markets/{market}/trades[?ticker=]            rm.trades           (page `_` or the ticker, verbatim)
import { MARKET_PAGE_KEY } from "./constants.ts";
import { definePage, readPage, readTickerPage, type ReadDeps } from "./handler.ts";

export const COMPANY_PAGE = definePage({ table: "stock", serve: "page" });
export const COMPANY_BARS = definePage({ table: "bars", serve: "verbatim" });
export const STOCK_STRATEGIES_PAGE = definePage({ table: "stock_strategies", serve: "page" });
export const TRADES_PAGE = definePage({ table: "trades", serve: "verbatim" });

/** GET /trades: the market's page, or one company's when the query names a ticker. */
export function tradesResponse(request: Request, market: string, deps: ReadDeps): Promise<Response> {
  const ticker = new URL(request.url).searchParams.get("ticker");
  return ticker === null
    ? readPage(request, TRADES_PAGE, market, MARKET_PAGE_KEY, deps)
    : readTickerPage(request, TRADES_PAGE, market, ticker, deps);
}
