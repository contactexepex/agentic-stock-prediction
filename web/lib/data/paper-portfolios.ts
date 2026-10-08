// The Paper portfolios page (B13, docs/ws/b13.md): rm.portfolio, page_key `_`, served by
// GET /api/v1/markets/{market}/portfolios (api/paths/paper-portfolios.yaml). Paper only: records, never orders.
import { definePage } from "./handler.ts";

export const PAPER_PORTFOLIOS_PAGE = definePage({ table: "portfolio", serve: "page" });
