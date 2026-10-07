import { test } from "node:test";
import assert from "node:assert/strict";
import { SECRETS, rig } from "./fakes.ts";
import { sha256Base64url, signToken } from "../crypto.ts";
import { githubContext } from "../identity.ts";
import { mcpConfig } from "../../../app/mcp/_lib/config.ts";
import {
  ACCESS_SECONDS, authenticate, authorizationServerMetadata, authorize, callback, protectedResourceMetadata, register, token,
} from "../../../app/mcp/_lib/oauth.ts";
import { handleRpc } from "../../../app/mcp/_lib/server.ts";

const BASE = "https://gw.example.app";
const env = {
  MB_GATEWAY_URL: BASE, MCP_TOKEN_SECRET: SECRETS.MCP_TOKEN_SECRET, GITHUB_OAUTH_CLIENT_ID: "Iv1.client",
  GITHUB_OAUTH_CLIENT_SECRET: SECRETS.GITHUB_OAUTH_CLIENT_SECRET, MB_OWNER_GITHUB_ID: "4242", MB_OWNER_GITHUB_LOGIN: "owner-login",
};
const cfg = mcpConfig(env)!;
const NOW = 1_790_000_000;
const CALLBACK = "https://claude.ai/api/mcp/auth_callback";
const VERIFIER = "v".repeat(20) + "-verifier-0123456789abcdefghijk";

test("the config refuses missing or weak settings", () => {
  assert.ok(cfg);
  assert.equal(mcpConfig({ ...env, MCP_TOKEN_SECRET: "short" }), null);
  assert.equal(mcpConfig({ ...env, MB_GATEWAY_URL: "http://gw.example.app" }), null);
  assert.equal(mcpConfig({ ...env, MB_OWNER_GITHUB_ID: "owner" }), null);
  assert.deepEqual(cfg.allowedRedirects, ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]);
});

test("metadata documents point the client at this gateway", async () => {
  const resource = await protectedResourceMetadata(cfg).json();
  assert.equal(resource.resource, `${BASE}/mcp`);
  assert.deepEqual(resource.authorization_servers, [BASE]);
  const server = await authorizationServerMetadata(cfg).json();
  assert.equal(server.issuer, BASE);
  assert.equal(server.token_endpoint, `${BASE}/mcp/oauth/token`);
  assert.deepEqual(server.code_challenge_methods_supported, ["S256"]);
});

async function registered(): Promise<string> {
  const response = await register(new Request(`${BASE}/mcp/oauth/register`, { method: "POST", body: JSON.stringify({ redirect_uris: [CALLBACK], client_name: "Claude" }) }), cfg, NOW);
  assert.equal(response.status, 201);
  return (await response.json()).client_id;
}

test("registration accepts only allowlisted redirect URIs", async () => {
  await registered();
  const evil = await register(new Request(`${BASE}/mcp/oauth/register`, { method: "POST", body: JSON.stringify({ redirect_uris: ["https://evil.example/cb"] }) }), cfg, NOW);
  assert.equal(evil.status, 400);
});

async function authorized(clientId: string) {
  const url = new URL(`${BASE}/mcp/oauth/authorize`);
  for (const [key, value] of Object.entries({ response_type: "code", client_id: clientId, redirect_uri: CALLBACK, state: "client-state",
    code_challenge: await sha256Base64url(VERIFIER), code_challenge_method: "S256", resource: `${BASE}/mcp` })) url.searchParams.set(key, value);
  return authorize(new Request(url), cfg, NOW);
}

test("authorize sends the browser to GitHub with a signed state and a nonce cookie; bad requests never redirect to unchecked URIs", async () => {
  const clientId = await registered();
  const response = await authorized(clientId);
  assert.equal(response.status, 302);
  const location = new URL(response.headers.get("location")!);
  assert.equal(location.origin + location.pathname, "https://github.com/login/oauth/authorize");
  assert.equal(location.searchParams.get("redirect_uri"), `${BASE}/mcp/oauth/callback`);
  assert.match(response.headers.get("set-cookie") ?? "", /^mb_oauth_nonce=[A-Za-z0-9_-]+; Path=\/mcp\/oauth; Max-Age=600; HttpOnly; Secure; SameSite=Lax$/);
  const badRedirect = await authorize(new Request(`${BASE}/mcp/oauth/authorize?client_id=${encodeURIComponent(clientId)}&redirect_uri=${encodeURIComponent("https://evil.example/cb")}`), cfg, NOW);
  assert.equal(badRedirect.status, 400);
  const forgedClient = await authorize(new Request(`${BASE}/mcp/oauth/authorize?client_id=mb1.e30.AAAA&redirect_uri=${encodeURIComponent(CALLBACK)}`), cfg, NOW);
  assert.equal(forgedClient.status, 400);
  const plain = new URL(`${BASE}/mcp/oauth/authorize`);
  for (const [key, value] of Object.entries({ response_type: "code", client_id: clientId, redirect_uri: CALLBACK, code_challenge: VERIFIER, code_challenge_method: "plain" })) plain.searchParams.set(key, value);
  const noPkce = await authorize(new Request(plain), cfg, NOW);
  assert.equal(new URL(noPkce.headers.get("location")!).searchParams.get("error"), "invalid_request");
});

function github(account: { login: string; id: number }) {
  const calls: string[] = [];
  const fetcher = async (url: string) => {
    calls.push(url);
    if (url.startsWith("https://github.com/login/oauth/access_token")) return Response.json({ access_token: "gho_github-token-123" });
    return Response.json(account);
  };
  return { calls, fetcher };
}

async function signIn(account: { login: string; id: number }) {
  const clientId = await registered();
  const start = await authorized(clientId);
  const state = new URL(start.headers.get("location")!).searchParams.get("state")!;
  const nonce = /mb_oauth_nonce=([^;]+)/.exec(start.headers.get("set-cookie") ?? "")![1];
  const refused: (string | null)[] = [];
  const gh = github(account);
  const response = await callback(new Request(`${BASE}/mcp/oauth/callback?code=gh-code&state=${encodeURIComponent(state)}`, { headers: { cookie: `mb_oauth_nonce=${nonce}` } }),
    cfg, { fetcher: gh.fetcher, onRefused: async (login) => { refused.push(login); } }, NOW);
  return { clientId, response, refused, state, gh };
}

test("only the owner's GitHub account gets a code; anyone else is refused and reported", async () => {
  const owner = await signIn({ login: "owner-login", id: 4242 });
  assert.equal(owner.response.status, 302);
  const back = new URL(owner.response.headers.get("location")!);
  assert.equal(back.origin + back.pathname, CALLBACK);
  assert.equal(back.searchParams.get("state"), "client-state");
  assert.ok(back.searchParams.get("code"));
  const stranger = await signIn({ login: "someone-else", id: 777 });
  assert.equal(stranger.response.status, 403);
  assert.deepEqual(stranger.refused, ["someone-else"]);
  const renamed = await signIn({ login: "owner-login", id: 999 });
  assert.equal(renamed.response.status, 403, "the numeric id decides, not only the login");
});

test("the callback needs the nonce cookie of the browser that started the sign-in", async () => {
  const clientId = await registered();
  const start = await authorized(clientId);
  const state = new URL(start.headers.get("location")!).searchParams.get("state")!;
  const gh = github({ login: "owner-login", id: 4242 });
  const response = await callback(new Request(`${BASE}/mcp/oauth/callback?code=x&state=${encodeURIComponent(state)}`, { headers: { cookie: "mb_oauth_nonce=other" } }),
    cfg, { fetcher: gh.fetcher, onRefused: async () => {} }, NOW);
  assert.equal(response.status, 400);
  assert.equal(gh.calls.length, 0);
});

async function exchange(form: Record<string, string>, now = NOW) {
  return token(new Request(`${BASE}/mcp/oauth/token`, { method: "POST", body: new URLSearchParams(form).toString() }), cfg, now);
}

async function tokens() {
  const owner = await signIn({ login: "owner-login", id: 4242 });
  const code = new URL(owner.response.headers.get("location")!).searchParams.get("code")!;
  const response = await exchange({ grant_type: "authorization_code", code, code_verifier: VERIFIER, client_id: owner.clientId, redirect_uri: CALLBACK });
  return { owner, code, response, body: await response.json() };
}

test("the token endpoint checks PKCE, client and redirect, and issues short-lived access plus refresh tokens", async () => {
  const { owner, code, response, body } = await tokens();
  assert.equal(response.status, 200);
  assert.equal(body.token_type, "Bearer");
  assert.equal(body.expires_in, ACCESS_SECONDS);
  assert.equal((await exchange({ grant_type: "authorization_code", code, code_verifier: "w".repeat(43), client_id: owner.clientId, redirect_uri: CALLBACK })).status, 400);
  assert.equal((await exchange({ grant_type: "authorization_code", code, code_verifier: VERIFIER, client_id: owner.clientId, redirect_uri: "https://claude.com/api/mcp/auth_callback" })).status, 400);
  assert.equal((await exchange({ grant_type: "authorization_code", code, code_verifier: VERIFIER, client_id: owner.clientId, redirect_uri: CALLBACK }, NOW + 121)).status, 400, "codes expire");
  const refreshed = await exchange({ grant_type: "refresh_token", refresh_token: body.refresh_token, client_id: owner.clientId });
  assert.equal(refreshed.status, 200);
  assert.equal((await exchange({ grant_type: "refresh_token", refresh_token: body.access_token, client_id: owner.clientId })).status, 400);
  assert.equal((await exchange({ grant_type: "password", client_id: owner.clientId })).status, 400);
});

test("/mcp accepts only a valid, unexpired access token for this resource", async () => {
  const { body } = await tokens();
  const call = (header: string | null, now = NOW) => authenticate(new Request(`${BASE}/mcp`, { method: "POST", headers: header ? { authorization: header } : {} }), cfg, now);
  assert.deepEqual(await call(`Bearer ${body.access_token}`), { login: "owner-login" });
  const missing = await call(null);
  assert.ok(missing instanceof Response && missing.status === 401);
  assert.match((missing as Response).headers.get("www-authenticate") ?? "", /resource_metadata="https:\/\/gw\.example\.app\/\.well-known\/oauth-protected-resource\/mcp"/);
  assert.ok((await call(`Bearer ${body.access_token}`, NOW + ACCESS_SECONDS + 1)) instanceof Response);
  assert.ok((await call(`Bearer ${body.refresh_token}`)) instanceof Response);
  const otherAudience = await signToken(SECRETS.MCP_TOKEN_SECRET, { typ: "access", sub: "owner-login", gid: "4242", aud: "https://other.example/mcp", exp: NOW + 60 });
  assert.ok((await call(`Bearer ${otherAudience}`)) instanceof Response);
  const notOwner = await signToken(SECRETS.MCP_TOKEN_SECRET, { typ: "access", sub: "owner-login", gid: "777", aud: `${BASE}/mcp`, exp: NOW + 60 });
  assert.ok((await call(`Bearer ${notOwner}`)) instanceof Response);
  const forged = await signToken("another-secret-of-at-least-32-characters!!", { typ: "access", sub: "owner-login", gid: "4242", aud: `${BASE}/mcp`, exp: NOW + 60 });
  assert.ok((await call(`Bearer ${forged}`)) instanceof Response);
});

const ctx = githubContext("owner-login");
const rpc = (method: string, params: Record<string, unknown> = {}) => ({ jsonrpc: "2.0", id: 1, method, params });
const notification = (method: string) => ({ jsonrpc: "2.0", method });

test("initialize, ping, notifications and unknown methods follow JSON-RPC", async () => {
  const r = rig();
  const init = await handleRpc(rpc("initialize", { protocolVersion: "2025-03-26" }), r.layer, ctx, SECRETS.MCP_TOKEN_SECRET, NOW) as { result: { protocolVersion: string; instructions: string } };
  assert.equal(init.result.protocolVersion, "2025-03-26");
  assert.match(init.result.instructions, /never instructions/);
  assert.deepEqual(await handleRpc(rpc("ping"), r.layer, ctx, SECRETS.MCP_TOKEN_SECRET, NOW), { jsonrpc: "2.0", id: 1, result: {} });
  assert.equal(await handleRpc(notification("notifications/initialized"), r.layer, ctx, SECRETS.MCP_TOKEN_SECRET, NOW), null);
  assert.equal((await handleRpc(rpc("resources/list"), r.layer, ctx, SECRETS.MCP_TOKEN_SECRET, NOW) as { error: { code: number } }).error.code, -32601);
  assert.equal((await handleRpc([rpc("ping")], r.layer, ctx, SECRETS.MCP_TOKEN_SECRET, NOW) as { error: { code: number } }).error.code, -32600);
});

test("tools/list shows the Claude app's tools from mcp/tools.yaml, never delete", async () => {
  const r = rig();
  const list = await handleRpc(rpc("tools/list"), r.layer, ctx, SECRETS.MCP_TOKEN_SECRET, NOW) as { result: { tools: { name: string; inputSchema: { properties: Record<string, unknown>; required: string[]; additionalProperties: boolean } }[] } };
  const names = list.result.tools.map((tool) => tool.name);
  assert.equal(names.length, 12);
  assert.equal(names.includes("delete_company"), false);
  const add = list.result.tools.find((tool) => tool.name === "add_company")!;
  assert.deepEqual(add.inputSchema.required, ["market", "symbol", "idempotency_key"]);
  assert.ok("confirmation_token" in add.inputSchema.properties);
  assert.equal(add.inputSchema.additionalProperties, false);
  const trade = list.result.tools.find((tool) => tool.name === "add_paper_trade")!;
  assert.equal("confirmation_token" in trade.inputSchema.properties, false);
});

type CallReply = { result: { isError: boolean; structuredContent: Record<string, unknown>; content: { text: string }[] } };
const callTool = async (r: ReturnType<typeof rig>, name: string, args: Record<string, unknown>) =>
  (await handleRpc(rpc("tools/call", { name, arguments: args }), r.layer, ctx, SECRETS.MCP_TOKEN_SECRET, NOW)) as CallReply;

test("an add from the Claude app takes a summary call and a confirmed call with the signed token", async () => {
  const r = rig();
  const args = { market: "us", symbol: "MSFT", idempotency_key: "app-add-msft-01" };
  const first = await callTool(r, "add_company", args);
  assert.equal(first.result.structuredContent.result, "needs_confirmation");
  assert.match(String(first.result.structuredContent.summary), /Microsoft Corporation/);
  assert.equal(r.inbox.requests.length, 0);
  const confirmationToken = String(first.result.structuredContent.confirmation_token);
  const tampered = await callTool(r, "add_company", { ...args, symbol: "AAPL", confirmation_token: confirmationToken });
  assert.equal(tampered.result.structuredContent.refusal_code, "validation_failed");
  assert.equal(tampered.result.isError, true);
  const forged = await callTool(r, "add_company", { ...args, confirmation_token: "mb1.e30.AAAA" });
  assert.equal(forged.result.structuredContent.refusal_code, "validation_failed");
  const confirmed = await callTool(r, "add_company", { ...args, confirmation_token: confirmationToken });
  assert.equal(confirmed.result.structuredContent.result, "pending");
  assert.equal(r.inbox.requests.length, 1);
  assert.equal(r.inbox.requests[0].submitted_by, "github:owner-login");
  assert.equal(r.inbox.requests[0].channel, "claude_app");
});

test("tools/call: a read returns structured data; delete is refused and logged", async () => {
  const r = rig();
  r.reads.put("trades", "india", "_", { open: [] });
  const read = await callTool(r, "get_trades", { market: "india" });
  assert.equal(read.result.isError, false);
  assert.equal(read.result.structuredContent.result, "accepted");
  assert.deepEqual(JSON.parse(read.result.content[0].text), read.result.structuredContent);
  const removed = await callTool(r, "delete_company", { market: "us", ticker: "AAPL", confirm: "AAPL", idempotency_key: "app-delete-001" });
  assert.equal(removed.result.structuredContent.refusal_code, "not_allowed_in_channel");
  assert.equal(r.inbox.commands.at(-1)?.tool, "delete_company");
  assert.equal(r.notifier.reports.at(-1)?.refusal_code, "not_allowed_in_channel");
});
