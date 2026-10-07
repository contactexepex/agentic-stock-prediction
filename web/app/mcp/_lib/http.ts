// Shared bits of the /mcp route handlers.
import { mcpConfig, type McpConfig } from "./config.ts";

export const nowSeconds = () => Math.floor(Date.now() / 1000);

export function notConfigured(): Response {
  return new Response(JSON.stringify({ error: "temporarily_unavailable", error_description: "not configured" }), {
    status: 503, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export function withConfig(handler: (cfg: McpConfig) => Promise<Response> | Response): Promise<Response> {
  const cfg = mcpConfig(process.env);
  return Promise.resolve(cfg ? handler(cfg) : notConfigured());
}
