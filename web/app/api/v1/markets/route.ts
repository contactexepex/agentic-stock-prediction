// GET /api/v1/markets (api/openapi.yaml listMarkets): both markets' status pages, composed (lib/data/platform.ts).
import { defaultDeps } from "../../../../lib/data/deps.ts";
import { marketsResponse } from "../../../../lib/data/platform.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return marketsResponse(defaultDeps());
}
