// GET /api/v1/markets/{market}/portfolios/finished/{date} (api/paths/paper-portfolios.yaml getPortfolioFinished):
// rm.portfolio, page_key `finished:<date>` (UX3).
import { defaultDeps } from "../../../../../../../../lib/data/deps.ts";
import { portfolioFinishedResponse } from "../../../../../../../../lib/data/paper-portfolios.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request, { params }: { params: Promise<{ market: string; date: string }> },
): Promise<Response> {
  const { market, date } = await params;
  return portfolioFinishedResponse(request, market, date, defaultDeps());
}
