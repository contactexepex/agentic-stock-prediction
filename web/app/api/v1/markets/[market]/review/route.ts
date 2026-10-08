// GET /api/v1/markets/{market}/review (api/paths/review.yaml getResearchReview): rm.review, page_key `_`.
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { REVIEW_PAGE } from "../../../../../../lib/data/review.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, REVIEW_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
