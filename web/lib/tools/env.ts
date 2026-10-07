// The environment variables of the tool layer, the Slack routes and /mcp, exactly as the orchestrator fixed them
// (docs/ws/b5.md lists them per Vercel project). Server-side only: nothing is NEXT_PUBLIC_. Secrets are never logged.

export type Env = Record<string, string | undefined>;

export const SECRET_VARIABLES = [
  "MOTHERDUCK_READ_TOKEN",
  "MOTHERDUCK_INBOX_TOKEN",
  "GITHUB_DISPATCH_TOKEN",
  "GITHUB_OAUTH_CLIENT_SECRET",
  "SESSION_SECRET",
  "SLACK_SIGNING_SECRET",
  "SLACK_BOT_TOKEN",
  "REVALIDATE_SECRET",
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
