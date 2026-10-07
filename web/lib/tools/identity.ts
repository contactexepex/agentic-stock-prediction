// Identity is injected from the channel's authentication, never taken from arguments or prompt text (F10).
// Only the channel adapters build a CallContext, and only from what their auth verified.
import type { CallContext, Channel } from "./types.ts";

const SLACK_USER = /^[UW][A-Z0-9]{2,20}$/;
const GITHUB_LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;

/** A Slack user from a request whose signature was verified (web/app/slack/). */
export function slackContext(userId: string, agent = "slack-gateway"): CallContext {
  if (!SLACK_USER.test(userId)) throw new Error("not a Slack user id");
  return Object.freeze({ channel: "slack" as Channel, actor: `slack:${userId}`, agent });
}

/** The owner's GitHub account from a verified /mcp access token (web/app/mcp/). */
export function githubContext(login: string): CallContext {
  if (!GITHUB_LOGIN.test(login)) throw new Error("not a GitHub login");
  return Object.freeze({ channel: "claude_app" as Channel, actor: `github:${login}`, agent: "claude-app" });
}

/** The dashboard owner behind Vercel Authentication (session B4's /api/v1 write routes; refused in gateway mode). */
export function dashboardContext(agent = "dashboard"): CallContext {
  return Object.freeze({ channel: "dashboard" as Channel, actor: "dashboard:owner", agent });
}

/** True when the actor has the form its channel's auth produces. */
export function actorMatchesChannel(ctx: CallContext): boolean {
  switch (ctx.channel) {
    case "slack":
      return /^slack:[UW][A-Z0-9]{2,20}$/.test(ctx.actor);
    case "claude_app":
      return /^github:[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(ctx.actor);
    case "dashboard":
      return ctx.actor === "dashboard:owner";
    default:
      return false; // Claude Code uses the CLIs directly (ARCHITECTURE.md 9.1), not the web tier
  }
}
