// GET /api/v1/markets/{market}/watchlist (api/paths/watchlist.yaml): rm.watchlist, page_key `_` (B11).
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { WATCHLIST_PAGE } from "../../../../../../lib/data/watchlist.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, WATCHLIST_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
