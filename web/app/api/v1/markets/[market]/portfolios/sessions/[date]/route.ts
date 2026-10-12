// GET /api/v1/markets/{market}/portfolios/sessions/{date} (api/paths/paper-portfolios.yaml getPortfolioSession):
// rm.portfolio, page_key `trades:<date>`.
import { defaultDeps } from "../../../../../../../../lib/data/deps.ts";
import { portfolioSessionResponse } from "../../../../../../../../lib/data/paper-portfolios.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request, { params }: { params: Promise<{ market: string; date: string }> },
): Promise<Response> {
  const { market, date } = await params;
  return portfolioSessionResponse(request, market, date, defaultDeps());
}
