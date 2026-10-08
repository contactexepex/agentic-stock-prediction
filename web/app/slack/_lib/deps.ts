// Production wiring of the Slack handlers (route handlers only; tests pass their own deps).
import { after } from "next/server";
import { type Env } from "../../../lib/tools/env.ts";
import type { SlackDeps, SlackReply } from "./commands.ts";
import { ephemeral } from "./views.ts";
import { slackDeps } from "./wiring.ts";

export function slackDepsFromEnv(env: Env = process.env): SlackDeps {
  return slackDeps(env, (task) => after(async () => {
    try {
      await task();
    } catch {
      // the command log and the owner report already carry what happened; never echo errors to Slack
    }
  }));
}

export function toResponse(reply: SlackReply): Response {
  return reply.body === null ? new Response(null, { status: reply.status }) : Response.json(reply.body, { status: reply.status });
}

export const FAILED: SlackReply = { status: 200, body: ephemeral("Something went wrong; nothing was written. The owner can see the log.") };
export const REFUSED = () => new Response("invalid request", { status: 401 });
export const nowSeconds = () => Math.floor(Date.now() / 1000);
