// GET /api/v1/markets/{market}/strategies (api/paths/strategy-lab.yaml getStrategyLab): rm.strategies, page_key `_`.
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { STRATEGY_LAB_PAGE } from "../../../../../../lib/data/strategy-lab.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, STRATEGY_LAB_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
