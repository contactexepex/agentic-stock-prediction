// POST /slack/commands: /company, /trade, /ask (gateway deployment only; web/middleware.ts).
import { value } from "../../../lib/tools/env.ts";
import { verifiedBody } from "../_lib/verify.ts";
import { handleCommand } from "../_lib/commands.ts";
import { FAILED, REFUSED, nowSeconds, slackDepsFromEnv, toResponse } from "../_lib/deps.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const raw = await verifiedBody(request, value(process.env, "SLACK_SIGNING_SECRET"), nowSeconds());
  if (raw === null) return REFUSED();
  try {
    return toResponse(await handleCommand(new URLSearchParams(raw), slackDepsFromEnv()));
  } catch {
    return toResponse(FAILED);
  }
}
