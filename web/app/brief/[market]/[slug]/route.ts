// GET /brief/{market}/{session}-{token}: the public daily brief (lib/brief/brief.ts). Read-only; the gateway serves it
// without login (lib/tools/gateway.ts allowlist), the app behind Vercel Authentication.
import { briefResponse } from "../../../../lib/brief/brief.ts";
import { motherDuckStore } from "../../../../lib/data/store.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ market: string; slug: string }> }):
    Promise<Response> {
  const { market, slug } = await context.params;
  return briefResponse(motherDuckStore(), market, slug);
}
