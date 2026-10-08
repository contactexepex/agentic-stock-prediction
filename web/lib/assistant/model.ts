// The Claude API client of the assistant: the official SDK, its requests sent through B5's HTTPS host allowlist
// (web/lib/tools/http.ts). One retry, 40 s per attempt, non-streaming (MAX_TOKENS is small).
import Anthropic from "@anthropic-ai/sdk";
import type { FetchLike } from "../tools/http.ts";
import type { ModelClient } from "./types.ts";

export function anthropicModel(apiKey: string, fetcher: FetchLike): ModelClient {
  const client = new Anthropic({
    apiKey,
    maxRetries: 1,
    timeout: 40000,
    fetch: (input, init) => fetcher(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, init),
  });
  return { create: (params) => client.messages.create(params) };
}
