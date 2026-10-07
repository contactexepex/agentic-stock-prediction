// Which requests each deployment serves (docs/SPEC.md F10). Gateway mode (MB_GATEWAY=1) serves only the Slack routes,
// /mcp and the OAuth routes its sign-in needs; everything else is a 404. The dashboard deployment never serves them.

export type GatewayDecision =
  | { action: "next" }
  | { action: "slack" }                       // verify Slack's signature, then next
  | { action: "rewrite"; target: string }
  | { action: "not_found" };

const SLACK_ROUTES = new Set(["/slack/commands", "/slack/interactions"]);
const MCP_ROUTES: Record<string, string[]> = {
  "/mcp": ["POST", "GET", "DELETE"],          // GET and DELETE answer 405 (stateless server)
  "/mcp/oauth/authorize": ["GET"],
  "/mcp/oauth/callback": ["GET"],
  "/mcp/oauth/token": ["POST"],
  "/mcp/oauth/register": ["POST"],
  "/mcp/oauth/metadata": ["GET"],
  "/mcp/oauth/protected-resource": ["GET"],
};
const WELL_KNOWN: Record<string, string> = {
  "/.well-known/oauth-protected-resource": "/mcp/oauth/protected-resource",
  "/.well-known/oauth-protected-resource/mcp": "/mcp/oauth/protected-resource",
  "/.well-known/oauth-authorization-server": "/mcp/oauth/metadata",
  "/.well-known/oauth-authorization-server/mcp": "/mcp/oauth/metadata",
};

function gatewayOnly(pathname: string): boolean {
  return pathname === "/slack" || pathname.startsWith("/slack/") || pathname === "/mcp" || pathname.startsWith("/mcp/") ||
    pathname.startsWith("/.well-known/oauth-");
}

export function gatewayDecision(pathname: string, method: string, gateway: boolean): GatewayDecision {
  if (!gateway) return gatewayOnly(pathname) ? { action: "not_found" } : { action: "next" };
  if (SLACK_ROUTES.has(pathname)) return method === "POST" ? { action: "slack" } : { action: "not_found" };
  if (MCP_ROUTES[pathname]?.includes(method)) return { action: "next" };
  if (WELL_KNOWN[pathname] && method === "GET") return { action: "rewrite", target: WELL_KNOWN[pathname] };
  return { action: "not_found" };
}
