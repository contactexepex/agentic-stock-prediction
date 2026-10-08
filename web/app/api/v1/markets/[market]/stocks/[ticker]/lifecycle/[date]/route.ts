// GET /api/v1/markets/{market}/stocks/{ticker}/lifecycle/{date} (api/paths/company.yaml getCompanyLifecycle):
// rm.lifecycle, page_key `<ticker>:<date>`.
import { lifecycleResponse } from "../../../../../../../../../lib/data/company.ts";
import { defaultDeps } from "../../../../../../../../../lib/data/deps.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request, { params }: { params: Promise<{ market: string; ticker: string; date: string }> },
): Promise<Response> {
  const { market, ticker, date } = await params;
  return lifecycleResponse(request, market, ticker, date, defaultDeps());
}
