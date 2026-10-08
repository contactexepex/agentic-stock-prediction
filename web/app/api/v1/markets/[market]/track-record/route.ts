// GET /api/v1/markets/{market}/track-record (api/paths/track-record.yaml getTrackRecord): rm.track_record, page_key `_`.
import { MARKET_PAGE_KEY } from "../../../../../../lib/data/constants.ts";
import { defaultDeps } from "../../../../../../lib/data/deps.ts";
import { readPage } from "../../../../../../lib/data/handler.ts";
import { TRACK_RECORD_PAGE } from "../../../../../../lib/data/track-record.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }): Promise<Response> {
  return readPage(request, TRACK_RECORD_PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
}
