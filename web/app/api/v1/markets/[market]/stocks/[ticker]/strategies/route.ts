// GET /api/v1/markets/{market}/stocks/{ticker}/strategies (api/paths/company.yaml getStockStrategies): rm.stock_strategies, page_key = ticker.
import { STOCK_STRATEGIES_PAGE } from "../../../../../../../../lib/data/company.ts";
import { defaultDeps } from "../../../../../../../../lib/data/deps.ts";
import { readTickerPage } from "../../../../../../../../lib/data/handler.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request, { params }: { params: Promise<{ market: string; ticker: string }> },
): Promise<Response> {
  const { market, ticker } = await params;
  return readTickerPage(request, STOCK_STRATEGIES_PAGE, market, ticker, defaultDeps());
}
