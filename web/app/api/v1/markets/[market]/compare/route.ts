// GET /api/v1/markets/{market}/compare (api/paths/rule-vs-ai.yaml getRuleVsAi): rm.compare, page_key `_`.
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { RULE_VS_AI_PAGE } from "../../../../../../lib/data/rule-vs-ai.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, RULE_VS_AI_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
