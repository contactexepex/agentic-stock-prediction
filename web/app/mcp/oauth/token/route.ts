import { token } from "../../_lib/oauth.ts";
import { nowSeconds, withConfig } from "../../_lib/http.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function POST(request: Request): Promise<Response> {
  return withConfig((cfg) => token(request, cfg, nowSeconds()));
}
