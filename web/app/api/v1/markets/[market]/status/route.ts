// GET /api/v1/markets/{market}/status (api/openapi.yaml getMarketStatus): rm.status, page_key `_`.
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { STATUS_PAGE } from "../../../../../../lib/data/platform.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, STATUS_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
