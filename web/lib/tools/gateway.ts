// Which requests each deployment serves (docs/SPEC.md F10). Gateway mode (MB_GATEWAY=1) serves only the Slack routes,
// /mcp and the OAuth routes its sign-in needs; everything else is a 404. The dashboard deployment never serves them.
// The public OAuth paths are /oauth/* and /.well-known/oauth-*; their handlers live under /mcp/oauth/ (B5's folder) and
// are reached only through these rewrites (a rewrite does not pass the middleware again).

export type GatewayDecision =
  | { action: "next" }
  | { action: "slack" }                       // verify Slack's signature, then next
  | { action: "rewrite"; target: string }
  | { action: "not_found" };

const SLACK_ROUTES = new Set(["/slack/commands", "/slack/interactions"]);
const MCP_METHODS = ["POST", "GET", "DELETE"];   // GET and DELETE answer 405 (stateless server)
/** The public daily brief (C2's handler web/app/brief/[market]/[slug]/route.ts): GET only, market, session date and a
 * 32-hex token; the handler answers 404 when the token does not match the stored one. Any other /brief path is a 404. */
const BRIEF_ROUTE = /^\/brief\/(india|us)\/\d{4}-\d{2}-\d{2}-[0-9a-f]{32}$/;
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
  if (method === "GET" && BRIEF_ROUTE.test(pathname)) return { action: "next" };
  const oauth = Object.hasOwn(OAUTH_ROUTES, pathname) ? OAUTH_ROUTES[pathname] : null;
  if (oauth && oauth.method === method) return { action: "rewrite", target: oauth.target };
  return { action: "not_found" };
}
