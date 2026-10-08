// GET /api/v1/markets/{market}/stocks/{ticker}/bars (api/paths/company.yaml getCompanyBars): rm.bars, page_key = ticker.
import { COMPANY_BARS } from "../../../../../../../../lib/data/company.ts";
import { defaultDeps } from "../../../../../../../../lib/data/deps.ts";
import { readTickerPage } from "../../../../../../../../lib/data/handler.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request, { params }: { params: Promise<{ market: string; ticker: string }> },
): Promise<Response> {
  const { market, ticker } = await params;
  return readTickerPage(request, COMPANY_BARS, market, ticker, defaultDeps());
}
