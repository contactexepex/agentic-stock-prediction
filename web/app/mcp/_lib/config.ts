// Settings of /mcp and its OAuth routes (docs/ws/b5.md lists every variable). The gateway's URL is fixed
// (https://market-brief-gateway.vercel.app), never taken from the Host header.
import { type Env, value } from "../../../lib/tools/env.ts";
import { ALLOWED_REDIRECTS, GATEWAY_URL } from "../../../lib/tools/constants.ts";

export interface McpConfig {
  baseUrl: string;                 // the gateway's public origin (OAuth issuer; the resource is <baseUrl>/mcp)
  tokenSecret: string;             // SESSION_SECRET, >= 32 characters; rotating it signs everyone out
  githubClientId: string;          // GITHUB_OAUTH_CLIENT_ID
  githubClientSecret: string;      // GITHUB_OAUTH_CLIENT_SECRET
  ownerGithubId: string;           // MB_OWNER_GITHUB_ID, the owner's numeric GitHub user id (a login can be renamed and re-registered)
  ownerGithubLogin: string;        // MCP_ALLOWED_GITHUB_LOGIN, the owner's GitHub username; both must match
  allowedRedirects: string[];
}

const GITHUB_LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;

/** The settings, or null when anything required is missing or malformed (the routes then answer 503). */
export function mcpConfig(env: Env, baseUrl: string = GATEWAY_URL): McpConfig | null {
  const tokenSecret = value(env, "SESSION_SECRET");
  const githubClientId = value(env, "GITHUB_OAUTH_CLIENT_ID");
  const githubClientSecret = value(env, "GITHUB_OAUTH_CLIENT_SECRET");
  const ownerGithubId = value(env, "MB_OWNER_GITHUB_ID");
  const ownerGithubLogin = value(env, "MCP_ALLOWED_GITHUB_LOGIN");
  if (!tokenSecret || tokenSecret.length < 32 || !githubClientId || !githubClientSecret) return null;
  if (!ownerGithubId || !/^\d{1,20}$/.test(ownerGithubId)) return null;
  if (!ownerGithubLogin || !GITHUB_LOGIN.test(ownerGithubLogin)) return null;
  return {
    baseUrl, tokenSecret, githubClientId, githubClientSecret, ownerGithubId, ownerGithubLogin,
    allowedRedirects: ALLOWED_REDIRECTS,
  };
}

export const resourceUrl = (cfg: McpConfig) => `${cfg.baseUrl}/mcp`;
export const resourceMetadataUrl = (cfg: McpConfig) => `${cfg.baseUrl}/.well-known/oauth-protected-resource/mcp`;
export const githubCallbackUrl = (cfg: McpConfig) => `${cfg.baseUrl}/oauth/github/callback`;
