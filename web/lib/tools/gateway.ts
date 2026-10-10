// Which requests each deployment serves (docs/SPEC.md F10). Gateway mode (MB_GATEWAY=1) serves only the Slack routes,
// /mcp, the OAuth routes its sign-in needs and the public brief (GET /brief/...); everything else is a 404. The
// dashboard deployment never serves the Slack, /mcp and OAuth routes (the brief passes there, behind Vercel
// Authentication).
// The public OAuth paths are /oauth/* and /.well-known/oauth-*; their handlers live under /mcp/oauth/ (B5's folder) and
// are reached only through these rewrites (a rewrite does not pass the middleware again).

export type GatewayDecision =
  | { action: "next" }
  | { action: "slack" }                       // verify Slack's signature, then next
  | { action: "rewrite"; target: string }
  | { action: "not_found" };

const SLACK_ROUTES = new Set(["/slack/commands", "/slack/interactions"]);
// The public daily brief (C2; docs/ws/c2.md): GET only, one market, one session date and a 128-bit token. The route
// checks the token against rm.brief; the allowlist only keeps everything else away from the gateway.
const BRIEF_ROUTE = /^\/brief\/(?:india|us)\/\d{4}-\d{2}-\d{2}-[0-9a-f]{32}$/;
const MCP_METHODS = ["POST", "GET", "DELETE"];   // GET and DELETE answer 405 (stateless server)
const OAUTH_ROUTES: Record<string, { method: string; target: string }> = {
  "/oauth/authorize": { method: "GET", target: "/mcp/oauth/authorize" },
  "/oauth/token": { method: "POST", target: "/mcp/oauth/token" },
  "/oauth/register": { method: "POST", target: "/mcp/oauth/register" },
  "/oauth/github/callback": { method: "GET", target: "/mcp/oauth/callback" },
  "/.well-known/oauth-protected-resource": { method: "GET", target: "/mcp/oauth/protected-resource" },
  "/.well-known/oauth-protected-resource/mcp": { method: "GET", target: "/mcp/oauth/protected-resource" },
  "/.well-known/oauth-authorization-server": { method: "GET", target: "/mcp/oauth/metadata" },
  "/.well-known/oauth-authorization-server/mcp": { method: "GET", target: "/mcp/oauth/metadata" },
};

function gatewayOnly(pathname: string): boolean {
  return pathname === "/slack" || pathname.startsWith("/slack/") || pathname === "/mcp" || pathname.startsWith("/mcp/") ||
    pathname === "/oauth" || pathname.startsWith("/oauth/") || pathname.startsWith("/.well-known/oauth-");
}

export function gatewayDecision(pathname: string, method: string, gateway: boolean): GatewayDecision {
  if (!gateway) return gatewayOnly(pathname) ? { action: "not_found" } : { action: "next" };
  if (SLACK_ROUTES.has(pathname)) return method === "POST" ? { action: "slack" } : { action: "not_found" };
  if (pathname === "/mcp" && MCP_METHODS.includes(method)) return { action: "next" };
  if (BRIEF_ROUTE.test(pathname)) return method === "GET" ? { action: "next" } : { action: "not_found" };
  const oauth = Object.hasOwn(OAUTH_ROUTES, pathname) ? OAUTH_ROUTES[pathname] : null;
  if (oauth && oauth.method === method) return { action: "rewrite", target: oauth.target };
  return { action: "not_found" };
}
