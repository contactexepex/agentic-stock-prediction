// /mcp: remote MCP over HTTP for the Claude app (gateway deployment only; GitHub OAuth, the owner's account only).
import { toolLayerFromEnv } from "../../lib/tools/index.ts";
import { withAssistant } from "../../lib/assistant/index.ts";
import { githubContext } from "../../lib/tools/identity.ts";
import { authenticate } from "./_lib/oauth.ts";
import { handleRpc } from "./_lib/server.ts";
import { nowSeconds, withConfig } from "./_lib/http.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;   // explain waits for B8's model call
const MAX_BODY = 1_000_000;

export function POST(request: Request): Promise<Response> {
  return withConfig(async (cfg) => {
    const auth = await authenticate(request, cfg, nowSeconds());
    if (auth instanceof Response) return auth;
    const text = await request.text();
    if (text.length > MAX_BODY) return new Response(null, { status: 413 });
    let message: unknown;
    try {
      message = JSON.parse(text);
    } catch {
      return Response.json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }, { status: 400 });
    }
    try {
      const reply = await handleRpc(message, withAssistant(toolLayerFromEnv()), githubContext(auth.login), cfg.tokenSecret, nowSeconds());
      return reply === null ? new Response(null, { status: 202 }) : Response.json(reply, { headers: { "Cache-Control": "no-store" } });
    } catch {
      return Response.json({ jsonrpc: "2.0", id: null, error: { code: -32603, message: "internal error" } }, { status: 500 });
    }
  });
}

const notAllowed = () => new Response(null, { status: 405, headers: { Allow: "POST" } });
export const GET = notAllowed;     // no server-initiated stream (stateless server)
export const DELETE = notAllowed;  // no sessions to end
