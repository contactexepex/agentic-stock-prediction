// The Claude API client of the assistant: the official SDK, its requests sent through B5's HTTPS host allowlist
// (web/lib/tools/http.ts). No retry and CALL_TIMEOUT_MS per call (constants.ts says how that fits the route's 60 s);
// non-streaming (MAX_TOKENS is small).
import Anthropic from "@anthropic-ai/sdk";
import type { FetchLike } from "../tools/http.ts";
import type { ModelClient } from "./types.ts";
import { CALL_TIMEOUT_MS } from "./constants.ts";

export function anthropicModel(apiKey: string, fetcher: FetchLike): ModelClient {
  const client = new Anthropic({
    apiKey,
    maxRetries: 0,
    timeout: CALL_TIMEOUT_MS,
    fetch: (input, init) => fetcher(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, init),
  });
  return { create: (params) => client.beta.messages.create(params) };
}
