// POST /slack/interactions: modal submissions and buttons (gateway deployment only; web/middleware.ts).
import { value } from "../../../lib/tools/env.ts";
import { verifiedBody } from "../_lib/verify.ts";
import { handleInteraction } from "../_lib/interactions.ts";
import { REFUSED, nowSeconds, slackDepsFromEnv, toResponse } from "../_lib/deps.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const raw = await verifiedBody(request, value(process.env, "SLACK_SIGNING_SECRET"), nowSeconds());
  if (raw === null) return REFUSED();
  let payload: unknown;
  try {
    payload = JSON.parse(new URLSearchParams(raw).get("payload") ?? "");
  } catch {
    return new Response(null, { status: 400 });
  }
  if (!payload || typeof payload !== "object") return new Response(null, { status: 400 });
  try {
    return toResponse(await handleInteraction(payload as Parameters<typeof handleInteraction>[0], slackDepsFromEnv()));
  } catch {
    return new Response(null, { status: 200 });
  }
}
