// POST /api/v1/markets/{market}/paper-trades (api/paths/paper-portfolios.yaml createPaperTrade): the owner's paper
// trade from the Paper portfolios page, through B5's tool layer (add_paper_trade, the dashboard identity). Refused in
// gateway mode (middleware and the tool layer). Never an order.
import { submitPaperTrade } from "../../../../../../lib/data/paper-trades.ts";
import { dashboardContext, toolLayerFromEnv } from "../../../../../../lib/tools/index.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return submitPaperTrade(request, (await params).market, toolLayerFromEnv(), dashboardContext());
}
