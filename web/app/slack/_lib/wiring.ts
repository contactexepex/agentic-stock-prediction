// The production SlackDeps without Next.js imports (deps.ts adds `after` as the deferral), so tests can check the wiring.
import { toolLayerFromEnv } from "../../../lib/tools/index.ts";
import { formatSlackAnswer, withAssistant } from "../../../lib/assistant/index.ts";
import { randomKey } from "../../../lib/tools/crypto.ts";
import { allowlistedFetch } from "../../../lib/tools/http.ts";
import { type Env, value } from "../../../lib/tools/env.ts";
import { SLACK_CHANNEL_ID } from "../../../lib/tools/constants.ts";
import { SlackWebApi } from "./api.ts";
import type { SlackDeps } from "./commands.ts";

export function slackDeps(env: Env, defer: SlackDeps["defer"]): SlackDeps {
  return {
    tools: withAssistant(toolLayerFromEnv(env), env),   // explain answered by B8's assistant (/ask)
    slack: new SlackWebApi(value(env, "SLACK_BOT_TOKEN"), allowlistedFetch()),
    defer,
    channelId: SLACK_CHANNEL_ID,
    newKey: () => randomKey("slk-"),
    formatAnswer: formatSlackAnswer,
  };
}
