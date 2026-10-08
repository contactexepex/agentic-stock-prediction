// GET /api/v1/markets/{market}/news (api/paths/news.yaml): rm.news, page_key `_` (B11).
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { NEWS_PAGE } from "../../../../../../lib/data/news.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, NEWS_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
