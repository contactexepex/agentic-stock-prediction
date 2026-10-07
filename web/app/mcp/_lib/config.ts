// Settings of /mcp and its OAuth routes, from the environment (docs/ws/b5.md lists every variable).
import { type Env, value } from "../../../lib/tools/env.ts";

export const DEFAULT_REDIRECTS = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"];

export interface McpConfig {
  baseUrl: string;                 // MB_GATEWAY_URL, e.g. https://market-brief-gateway.vercel.app (never from Host)
  tokenSecret: string;             // MCP_TOKEN_SECRET, >= 32 characters; rotating it signs everyone out
  githubClientId: string;
  githubClientSecret: string;
  ownerGithubId: string;           // MB_OWNER_GITHUB_ID, the owner's numeric GitHub user id
  ownerGithubLogin: string | null; // MB_OWNER_GITHUB_LOGIN, optional second check
  allowedRedirects: string[];      // MCP_ALLOWED_REDIRECT_URIS, comma-separated; default: the Claude app's callbacks
}

/** The settings, or null when anything required is missing or malformed (the routes then answer 503). */
export function mcpConfig(env: Env): McpConfig | null {
  const baseUrl = value(env, "MB_GATEWAY_URL")?.replace(/\/+$/, "") ?? null;
  const tokenSecret = value(env, "MCP_TOKEN_SECRET");
  const githubClientId = value(env, "GITHUB_OAUTH_CLIENT_ID");
  const githubClientSecret = value(env, "GITHUB_OAUTH_CLIENT_SECRET");
  const ownerGithubId = value(env, "MB_OWNER_GITHUB_ID");
  if (!baseUrl || !/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(baseUrl)) return null;
  if (!tokenSecret || tokenSecret.length < 32 || !githubClientId || !githubClientSecret) return null;
  if (!ownerGithubId || !/^\d{1,20}$/.test(ownerGithubId)) return null;
  const listed = value(env, "MCP_ALLOWED_REDIRECT_URIS");
  const allowedRedirects = listed ? listed.split(",").map((uri) => uri.trim()).filter((uri) => uri.startsWith("https://")) : DEFAULT_REDIRECTS;
  return {
    baseUrl, tokenSecret, githubClientId, githubClientSecret, ownerGithubId,
    ownerGithubLogin: value(env, "MB_OWNER_GITHUB_LOGIN"), allowedRedirects,
  };
}

export const resourceUrl = (cfg: McpConfig) => `${cfg.baseUrl}/mcp`;
export const resourceMetadataUrl = (cfg: McpConfig) => `${cfg.baseUrl}/.well-known/oauth-protected-resource/mcp`;
