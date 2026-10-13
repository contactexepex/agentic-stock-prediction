// GET /api/v1/markets/{market}/portfolios/open/{hold} (api/paths/paper-portfolios.yaml getPortfolioHold):
// rm.portfolio, page_key `open:<hold>` (UX3).
import { defaultDeps } from "../../../../../../../../lib/data/deps.ts";
import { portfolioHoldResponse } from "../../../../../../../../lib/data/paper-portfolios.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request, { params }: { params: Promise<{ market: string; hold: string }> },
): Promise<Response> {
  const { market, hold } = await params;
  return portfolioHoldResponse(request, market, hold, defaultDeps());
}
