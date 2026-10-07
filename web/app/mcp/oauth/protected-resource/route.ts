// Served at /.well-known/oauth-protected-resource[/mcp] (rewritten by web/middleware.ts in gateway mode).
import { protectedResourceMetadata } from "../../_lib/oauth.ts";
import { withConfig } from "../../_lib/http.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(): Promise<Response> {
  return withConfig((cfg) => protectedResourceMetadata(cfg));
}
