// GET /api/v1/markets/{market}/home (api/paths/home.yaml): rm.home, page_key `_` (B11).
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { HOME_PAGE } from "../../../../../../lib/data/home.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, HOME_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
