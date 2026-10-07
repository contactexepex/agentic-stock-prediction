import { callback } from "../../_lib/oauth.ts";
import { nowSeconds, withConfig } from "../../_lib/http.ts";
import { allowlistedFetch } from "../../../../lib/tools/http.ts";
import { toolLayerFromEnv } from "../../../../lib/tools/index.ts";
import { githubContext } from "../../../../lib/tools/identity.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function onRefused(login: string | null): Promise<void> {
  const ctx = githubContext(login && /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(login) ? login : "unknown");
  await toolLayerFromEnv().record(ctx, { tool: null, kind: null, market: null, args: {}, result: "refused",
    code: "unknown_actor", message: "A GitHub account that is not the owner's tried to sign in to /mcp" });
}

export function GET(request: Request): Promise<Response> {
  return withConfig((cfg) => callback(request, cfg, { fetcher: allowlistedFetch(), onRefused }, nowSeconds()));
}
