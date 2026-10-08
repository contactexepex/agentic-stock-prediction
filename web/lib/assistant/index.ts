// Wiring of the assistant from the environment (route handlers only; tests build AssistantExplainer with fakes).
// ANTHROPIC_API_KEY (both Vercel projects) and MOTHERDUCK_INBOX_TOKEN (the conversation log in market_brief_inbox).
import { ToolLayer } from "../tools/executor.ts";
import { allowlistedFetch } from "../tools/http.ts";
import { pgQuery } from "../tools/motherduck.ts";
import { hexOf } from "../tools/crypto.ts";
import { type Env, secretValues, value } from "../tools/env.ts";
import { INBOX_DATABASE, MOTHERDUCK_PG_HOST } from "../tools/constants.ts";
import type { ToolDeps } from "../tools/types.ts";
import { AssistantExplainer } from "./explainer.ts";
import { anthropicModel } from "./model.ts";
import { MotherDuckConversationStore } from "./store.ts";

export { AssistantExplainer } from "./explainer.ts";
export { formatSlackAnswer, ASK_USAGE, ASK_WORKING } from "./slack.ts";
export type * from "./types.ts";

let cached: { env: Env; store: MotherDuckConversationStore; explainer: AssistantExplainer } | null = null;

function fromEnv(env: Env) {
  if (cached && cached.env === env) return cached;
  const store = new MotherDuckConversationStore(pgQuery({ host: MOTHERDUCK_PG_HOST, database: INBOX_DATABASE,
    token: value(env, "MOTHERDUCK_INBOX_TOKEN") }));
  const key = value(env, "ANTHROPIC_API_KEY");
  const explainer = new AssistantExplainer({
    store,
    model: key ? anthropicModel(key, allowlistedFetch(fetch, 45000)) : null,
    clock: () => new Date(),
    secrets: secretValues(env),
    newId: () => hexOf(crypto.getRandomValues(new Uint8Array(5))),
  });
  cached = { env, store, explainer };
  return cached;
}

export function assistantFromEnv(env: Env = process.env): AssistantExplainer {
  return fromEnv(env).explainer;
}

export function conversationStoreFromEnv(env: Env = process.env): MotherDuckConversationStore {
  return fromEnv(env).store;
}

/** The tool layer with the explain tool answered by the assistant (B5's ToolDeps.explainer hook). */
export function withAssistant(layer: ToolLayer, env: Env = process.env): ToolLayer {
  return new ToolLayer({ ...layer.deps, explainer: assistantFromEnv(env) } as ToolDeps);
}
