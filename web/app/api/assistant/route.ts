// /api/assistant: the chat panel and page 11 (docs/SPEC.md F11; logic in web/lib/assistant/api.ts).
import { toolLayerFromEnv } from "../../../lib/tools/index.ts";
import { gatewayMode } from "../../../lib/tools/env.ts";
import { APP_URL } from "../../../lib/tools/constants.ts";
import { conversationStoreFromEnv, withAssistant } from "../../../lib/assistant/index.ts";
import { type AssistantApiDeps, getConversation, postQuestion } from "../../../lib/assistant/api.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

function deps(): AssistantApiDeps {
  return {
    tools: withAssistant(toolLayerFromEnv()),
    store: conversationStoreFromEnv(),
    clock: () => new Date(),
    gatewayMode: gatewayMode(process.env),
    origins: [APP_URL],
  };
}

export async function POST(request: Request): Promise<Response> {
  return postQuestion(request, deps());
}

export async function GET(request: Request): Promise<Response> {
  return getConversation(request, deps());
}
