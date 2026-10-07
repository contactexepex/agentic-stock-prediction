// Every environment variable of the tool layer, the Slack routes and /mcp (documented in docs/ws/b5.md). Server-side
// only: nothing here is NEXT_PUBLIC_, so no value reaches a client bundle. Secrets are never logged or echoed.

export type Env = Record<string, string | undefined>;

export const SECRET_VARIABLES = [
  "MOTHERDUCK_READ_TOKEN",
  "MOTHERDUCK_INBOX_TOKEN",
  "GITHUB_DISPATCH_TOKEN",
  "SLACK_SIGNING_SECRET",
  "SLACK_BOT_TOKEN",
  "GITHUB_OAUTH_CLIENT_SECRET",
  "MCP_TOKEN_SECRET",
  "ANTHROPIC_API_KEY",
] as const;

export function value(env: Env, name: string): string | null {
  const raw = env[name];
  return raw && raw.trim() ? raw.trim() : null;
}

export function gatewayMode(env: Env): boolean {
  return value(env, "MB_GATEWAY") === "1";
}

export function secretValues(env: Env): string[] {
  return SECRET_VARIABLES.map((name) => value(env, name)).filter((secret): secret is string => secret !== null);
}

export function killSwitch(env: Env): string[] {
  return (value(env, "MB_KILL_SWITCH") ?? "").split(",").map((item) => item.trim()).filter(Boolean);
}
