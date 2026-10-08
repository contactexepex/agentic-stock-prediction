// GET /api/v1/markets/{market}/stocks/{ticker} (api/paths/company.yaml getCompanyPage): rm.stock, page_key = ticker.
import { COMPANY_PAGE } from "../../../../../../../lib/data/company.ts";
import { defaultDeps } from "../../../../../../../lib/data/deps.ts";
import { readTickerPage } from "../../../../../../../lib/data/handler.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request, { params }: { params: Promise<{ market: string; ticker: string }> },
): Promise<Response> {
  const { market, ticker } = await params;
  return readTickerPage(request, COMPANY_PAGE, market, ticker, defaultDeps());
}
