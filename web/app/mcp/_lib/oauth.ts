// OAuth for /mcp (MCP authorization spec; RFC 9728, 8414, 7591, 7636): this gateway is both the protected resource and
// the authorization server, and federates sign-in to GitHub. Only the owner's GitHub account is accepted (decision 22):
// its numeric id MB_OWNER_GITHUB_ID and its login MCP_ALLOWED_GITHUB_LOGIN must both match.
// Public paths (web/middleware.ts rewrites them to these handlers under /mcp/oauth/): /oauth/authorize, /oauth/token,
// /oauth/register, /oauth/github/callback and /.well-known/oauth-*.
// Stateless (no store on Vercel): client ids, the GitHub state, authorization codes and tokens are HMAC-signed
// (crypto.ts) with SESSION_SECRET. PKCE S256 is required; redirect URIs must be on the allowlist. The GitHub access
// token is used once to read the account and then discarded.
import { randomKey, sha256Base64url, signToken, verifyToken } from "../../../lib/tools/crypto.ts";
import type { FetchLike } from "../../../lib/tools/http.ts";
import { type McpConfig, githubCallbackUrl, resourceMetadataUrl, resourceUrl } from "./config.ts";

export const CODE_SECONDS = 120;
export const ACCESS_SECONDS = 3600;
export const REFRESH_SECONDS = 30 * 24 * 3600;
const STATE_SECONDS = 600;
const CLIENT_SECONDS = 365 * 24 * 3600;
const NONCE_COOKIE = "mb_oauth_nonce";
const COOKIE_PATH = "/oauth";
const CHALLENGE = /^[A-Za-z0-9_-]{43,128}$/;
const VERIFIER = /^[A-Za-z0-9._~-]{43,128}$/;

const noStore = { "Cache-Control": "no-store", Pragma: "no-cache" };

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...noStore, ...headers } });
}

function oauthError(error: string, description: string, status = 400): Response {
  return json({ error, error_description: description }, status);
}

function page(text: string, status: number): Response {
  const safe = text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);
  return new Response(`<!doctype html><meta charset="utf-8"><title>market-brief</title><p>${safe}</p>`, {
    status, headers: { "Content-Type": "text/html; charset=utf-8", ...noStore },
  });
}

export function protectedResourceMetadata(cfg: McpConfig): Response {
  return json({
    resource: resourceUrl(cfg), authorization_servers: [cfg.baseUrl], bearer_methods_supported: ["header"],
    scopes_supported: ["mcp"], resource_name: "market-brief (research only)",
  });
}

export function authorizationServerMetadata(cfg: McpConfig): Response {
  return json({
    issuer: cfg.baseUrl,
    authorization_endpoint: `${cfg.baseUrl}/oauth/authorize`,
    token_endpoint: `${cfg.baseUrl}/oauth/token`,
    registration_endpoint: `${cfg.baseUrl}/oauth/register`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none"],
    scopes_supported: ["mcp"],
  });
}

/** Dynamic client registration: a public client whose redirect URIs are all on the allowlist. */
export async function register(request: Request, cfg: McpConfig, nowSeconds: number): Promise<Response> {
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return oauthError("invalid_client_metadata", "body must be JSON");
  }
  const uris = Array.isArray(body?.redirect_uris) ? body.redirect_uris : [];
  if (!uris.length || uris.length > 5 || !uris.every((uri) => typeof uri === "string" && cfg.allowedRedirects.includes(uri))) {
    return oauthError("invalid_redirect_uri", "redirect_uris must be on the gateway's allowlist");
  }
  const clientId = await signToken(cfg.tokenSecret, { typ: "client", redirect_uris: uris, exp: nowSeconds + CLIENT_SECONDS });
  return json({
    client_id: clientId, client_id_issued_at: nowSeconds, redirect_uris: uris, token_endpoint_auth_method: "none",
    grant_types: ["authorization_code", "refresh_token"], response_types: ["code"],
    client_name: typeof body.client_name === "string" ? body.client_name.slice(0, 100) : "MCP client",
  }, 201);
}

async function client(cfg: McpConfig, clientId: string | null, nowSeconds: number): Promise<string[] | null> {
  if (!clientId) return null;
  const payload = await verifyToken(cfg.tokenSecret, clientId, nowSeconds);
  return payload?.typ === "client" && Array.isArray(payload.redirect_uris) ? (payload.redirect_uris as string[]) : null;
}

/** GET /oauth/authorize: checks the client, redirect URI and PKCE, then sends the browser to GitHub. */
export async function authorize(request: Request, cfg: McpConfig, nowSeconds: number): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const clientId = params.get("client_id");
  const redirectUri = params.get("redirect_uri") ?? "";
  const registered = await client(cfg, clientId, nowSeconds);
  if (!registered || !registered.includes(redirectUri) || !cfg.allowedRedirects.includes(redirectUri)) {
    return page("This sign-in request is not valid (unknown client or redirect).", 400); // never redirect to an unchecked URI
  }
  const back = (error: string) => {
    const url = new URL(redirectUri);
    url.searchParams.set("error", error);
    if (params.get("state")) url.searchParams.set("state", params.get("state") ?? "");
    return Response.redirect(url.toString(), 302);
  };
  if (params.get("response_type") !== "code") return back("unsupported_response_type");
  const challenge = params.get("code_challenge") ?? "";
  if (params.get("code_challenge_method") !== "S256" || !CHALLENGE.test(challenge)) return back("invalid_request");
  const resource = params.get("resource");
  if (resource && resource !== resourceUrl(cfg)) return back("invalid_target");
  const nonce = randomKey("", 16);
  const state = await signToken(cfg.tokenSecret, {
    typ: "state", client_id: clientId, redirect_uri: redirectUri, state: (params.get("state") ?? "").slice(0, 500),
    code_challenge: challenge, nonce, exp: nowSeconds + STATE_SECONDS,
  });
  const github = new URL("https://github.com/login/oauth/authorize");
  github.searchParams.set("client_id", cfg.githubClientId);
  github.searchParams.set("redirect_uri", githubCallbackUrl(cfg));
  github.searchParams.set("state", state);
  github.searchParams.set("allow_signup", "false");
  return new Response(null, {
    status: 302,
    headers: {
      Location: github.toString(), ...noStore,
      "Set-Cookie": `${NONCE_COOKIE}=${nonce}; Path=${COOKIE_PATH}; Max-Age=${STATE_SECONDS}; HttpOnly; Secure; SameSite=Lax`,
    },
  });
}

function cookie(request: Request, name: string): string | null {
  const header = request.headers.get("cookie") ?? "";
  for (const part of header.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return null;
}

export interface CallbackDeps {
  fetcher: FetchLike;
  /** Logs and reports a sign-in by a GitHub account that is not the owner's. */
  onRefused: (login: string | null) => Promise<void>;
}

/** GET /oauth/github/callback: GitHub's answer. Exchanges the code, reads the account, accepts only the owner. */
export async function callback(request: Request, cfg: McpConfig, deps: CallbackDeps, nowSeconds: number): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const state = await verifyToken(cfg.tokenSecret, params.get("state") ?? "", nowSeconds);
  if (!state || state.typ !== "state" || cookie(request, NONCE_COOKIE) !== state.nonce) {
    return page("This sign-in expired or was not started here. Start again from the Claude app.", 400);
  }
  const code = params.get("code");
  if (!code) return page("GitHub sign-in was cancelled.", 400);
  let login: string | null = null;
  let id: string | null = null;
  try {
    const exchange = await deps.fetcher("https://github.com/login/oauth/access_token", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", "User-Agent": "market-brief-gateway" },
      body: JSON.stringify({ client_id: cfg.githubClientId, client_secret: cfg.githubClientSecret, code,
        redirect_uri: githubCallbackUrl(cfg) }),
    });
    const token = ((await exchange.json()) as { access_token?: string }).access_token;
    if (!token) return page("GitHub did not accept the sign-in.", 502);
    const user = await deps.fetcher("https://api.github.com/user", {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "User-Agent": "market-brief-gateway" },
    });
    const account = (await user.json()) as { login?: unknown; id?: unknown };
    login = typeof account.login === "string" ? account.login : null;
    id = typeof account.id === "number" || typeof account.id === "string" ? String(account.id) : null;
  } catch {
    return page("GitHub could not be reached.", 502);
  }
  const loginOk = login?.toLowerCase() === cfg.ownerGithubLogin.toLowerCase();
  if (!login || id !== cfg.ownerGithubId || !loginOk) {
    await deps.onRefused(login);
    return page("Only the owner's GitHub account can use this connector.", 403);
  }
  const ourCode = await signToken(cfg.tokenSecret, {
    typ: "code", client_id: state.client_id, redirect_uri: state.redirect_uri, code_challenge: state.code_challenge,
    sub: login, gid: id, nonce: randomKey("", 8), exp: nowSeconds + CODE_SECONDS,
  });
  const url = new URL(String(state.redirect_uri));
  url.searchParams.set("code", ourCode);
  if (state.state) url.searchParams.set("state", String(state.state));
  return new Response(null, {
    status: 302,
    headers: { Location: url.toString(), ...noStore, "Set-Cookie": `${NONCE_COOKIE}=; Path=${COOKIE_PATH}; Max-Age=0; HttpOnly; Secure; SameSite=Lax` },
  });
}

async function issue(cfg: McpConfig, sub: string, gid: string, clientId: string, nowSeconds: number): Promise<Response> {
  const common = { sub, gid, client_id: clientId, aud: resourceUrl(cfg) };
  return json({
    access_token: await signToken(cfg.tokenSecret, { typ: "access", ...common, exp: nowSeconds + ACCESS_SECONDS }),
    token_type: "Bearer", expires_in: ACCESS_SECONDS, scope: "mcp",
    refresh_token: await signToken(cfg.tokenSecret, { typ: "refresh", ...common, nonce: randomKey("", 8), exp: nowSeconds + REFRESH_SECONDS }),
  });
}

/** POST /oauth/token: authorization_code (with the PKCE verifier) or refresh_token. */
export async function token(request: Request, cfg: McpConfig, nowSeconds: number): Promise<Response> {
  const form = new URLSearchParams(await request.text());
  const clientId = form.get("client_id") ?? "";
  if (!(await client(cfg, clientId, nowSeconds))) return oauthError("invalid_client", "unknown client", 401);
  const grant = form.get("grant_type");
  if (grant === "authorization_code") {
    const code = await verifyToken(cfg.tokenSecret, form.get("code") ?? "", nowSeconds);
    const verifier = form.get("code_verifier") ?? "";
    if (!code || code.typ !== "code" || code.client_id !== clientId || code.redirect_uri !== form.get("redirect_uri")) {
      return oauthError("invalid_grant", "the code is not valid");
    }
    if (!VERIFIER.test(verifier) || (await sha256Base64url(verifier)) !== code.code_challenge) {
      return oauthError("invalid_grant", "PKCE check failed");
    }
    if (code.gid !== cfg.ownerGithubId) return oauthError("invalid_grant", "not the owner");
    return issue(cfg, String(code.sub), String(code.gid), clientId, nowSeconds);
  }
  if (grant === "refresh_token") {
    const refresh = await verifyToken(cfg.tokenSecret, form.get("refresh_token") ?? "", nowSeconds);
    if (!refresh || refresh.typ !== "refresh" || refresh.client_id !== clientId || refresh.gid !== cfg.ownerGithubId) {
      return oauthError("invalid_grant", "the refresh token is not valid");
    }
    return issue(cfg, String(refresh.sub), String(refresh.gid), clientId, nowSeconds);
  }
  return oauthError("unsupported_grant_type", "authorization_code or refresh_token");
}

export function unauthorized(cfg: McpConfig, invalid: boolean): Response {
  const error = invalid ? ', error="invalid_token"' : "";
  return json({ error: invalid ? "invalid_token" : "unauthorized" }, 401, {
    "WWW-Authenticate": `Bearer resource_metadata="${resourceMetadataUrl(cfg)}"${error}`,
  });
}

/** The owner's GitHub login from a valid access token for this resource, or a 401 response. */
export async function authenticate(request: Request, cfg: McpConfig, nowSeconds: number): Promise<{ login: string } | Response> {
  const header = request.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(\S+)$/i.exec(header);
  if (!match) return unauthorized(cfg, false);
  const payload = await verifyToken(cfg.tokenSecret, match[1], nowSeconds);
  if (!payload || payload.typ !== "access" || payload.aud !== resourceUrl(cfg) || payload.gid !== cfg.ownerGithubId) {
    return unauthorized(cfg, true);
  }
  const login = String(payload.sub ?? "");
  if (login.toLowerCase() !== cfg.ownerGithubLogin.toLowerCase()) return unauthorized(cfg, true);
  return { login };
}
