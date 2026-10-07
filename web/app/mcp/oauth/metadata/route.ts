// Served at /.well-known/oauth-authorization-server (rewritten by web/middleware.ts in gateway mode).
import { authorizationServerMetadata } from "../../_lib/oauth.ts";
import { withConfig } from "../../_lib/http.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(): Promise<Response> {
  return withConfig((cfg) => authorizationServerMetadata(cfg));
}
