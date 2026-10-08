// GET /api/v1/markets/{market}/portfolios (api/paths/paper-portfolios.yaml getPaperPortfolios): rm.portfolio, page_key `_`.
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { PAPER_PORTFOLIOS_PAGE } from "../../../../../../lib/data/paper-portfolios.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, PAPER_PORTFOLIOS_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
