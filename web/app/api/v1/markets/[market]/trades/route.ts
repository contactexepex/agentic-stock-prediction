// GET /api/v1/markets/{market}/trades[?ticker=] (api/paths/company.yaml getTrades): rm.trades, page_key `_` or the ticker.
import { tradesResponse } from "../../../../../../lib/data/company.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return tradesResponse(request, (await params).market, defaultDeps());
}
