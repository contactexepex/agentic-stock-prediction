// The Paper portfolios page (B13, docs/ws/b13.md): rm.portfolio, page_key `_`, served by
// GET /api/v1/markets/{market}/portfolios, and one accuracy-view entry session, page_key `trades:<date>`, served by
// GET /api/v1/markets/{market}/portfolios/sessions/{date} (api/paths/paper-portfolios.yaml). Paper only: records, never
// orders.
import { definePage, readPage, type ReadDeps } from "./handler.ts";
import { notFound } from "./problem.ts";

export const PAPER_PORTFOLIOS_PAGE = definePage({ table: "portfolio", serve: "page" });
export const PORTFOLIO_SESSION_PAGE = definePage({ table: "portfolio", serve: "verbatim" });

/** An entry session as the contract writes it (IsoDate). */
const SESSION_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** GET /portfolios/sessions/{date}: one entry session's page `trades:<date>`; a session without accuracy-view trades
 *  or older than the stored 60 has no page, so 404. */
export function portfolioSessionResponse(request: Request, market: string, day: string, deps: ReadDeps): Promise<Response> {
  if (!SESSION_DATE.test(day)) return Promise.resolve(notFound("Unknown session date"));
  return readPage(request, PORTFOLIO_SESSION_PAGE, market, `trades:${day}`, deps);
}

/** A hold k as the contract writes it (1-5). */
const HOLD = /^[1-5]$/;

/** GET /portfolios/open/{hold} (UX3): the open accuracy-view trades of hold k, page `open:<k>`; a hold without open
 *  trades has no page, so 404. */
export function portfolioHoldResponse(request: Request, market: string, hold: string, deps: ReadDeps): Promise<Response> {
  if (!HOLD.test(hold)) return Promise.resolve(notFound("Unknown hold"));
  return readPage(request, PORTFOLIO_SESSION_PAGE, market, `open:${hold}`, deps);
}

/** GET /portfolios/finished/{date} (UX3): the accuracy-view trades that exited on one session, page `finished:<date>`;
 *  a session of the last 10 without such trades, or an older one, has no page, so 404. */
export function portfolioFinishedResponse(request: Request, market: string, day: string, deps: ReadDeps): Promise<Response> {
  if (!SESSION_DATE.test(day)) return Promise.resolve(notFound("Unknown session date"));
  return readPage(request, PORTFOLIO_SESSION_PAGE, market, `finished:${day}`, deps);
}
