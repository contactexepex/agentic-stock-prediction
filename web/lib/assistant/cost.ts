// Cost of model calls and the spend of the UTC day and month (shown, never enforced: owner decision 2026-10-08, no
// money budget in code). Every figure is in USD.
import type Anthropic from "@anthropic-ai/sdk";
import { MODEL, PRICES, type Price, UNKNOWN_MODEL_PRICE } from "./constants.ts";
import type { SpendState } from "./types.ts";

export interface TokenUse {
  input_tokens: number;
  cache_write_tokens: number;
  cache_read_tokens: number;
  output_tokens: number;
}

export const NO_TOKENS: TokenUse = { input_tokens: 0, cache_write_tokens: 0, cache_read_tokens: 0, output_tokens: 0 };

type Usage = Anthropic.Beta.BetaUsage | Anthropic.Usage | null | undefined;

function tokensOfEntry(usage: { input_tokens?: number | null; cache_creation_input_tokens?: number | null;
  cache_read_input_tokens?: number | null; output_tokens?: number | null } | null | undefined): TokenUse {
  return {
    input_tokens: usage?.input_tokens ?? 0,
    cache_write_tokens: usage?.cache_creation_input_tokens ?? 0,
    cache_read_tokens: usage?.cache_read_input_tokens ?? 0,
    output_tokens: usage?.output_tokens ?? 0,
  };
}

/** Every attempt of one response with the model that ran it: `usage.iterations` when present (a fallback reports the
 * declined attempt and the serving one apart; top-level usage covers only the latter; an entry without a model is the
 * requested MODEL's), else the top-level usage, run by `served` (the response's model). */
export function attemptsOf(usage: Usage, served: string): { model: string; tokens: TokenUse }[] {
  const iterations = usage && "iterations" in usage && Array.isArray(usage.iterations) ? usage.iterations : null;
  if (!iterations || iterations.length === 0) return [{ model: served, tokens: tokensOfEntry(usage) }];
  return iterations.map((entry) => ({
    model: "model" in entry && typeof entry.model === "string" ? entry.model : MODEL,
    tokens: tokensOfEntry(entry as Parameters<typeof tokensOfEntry>[0]),
  }));
}

export function tokensOf(usage: Usage, served: string = MODEL): TokenUse {
  return attemptsOf(usage, served).reduce((sum, attempt) => addTokens(sum, attempt.tokens), NO_TOKENS);
}

/** The cost of one response: each attempt at its own model's price, an unlisted model at the dearest price. */
export function responseCostUsd(usage: Usage, served: string = MODEL): number {
  return attemptsOf(usage, served).reduce((sum, attempt) => sum + costUsd(attempt.tokens, PRICES[attempt.model] ?? UNKNOWN_MODEL_PRICE), 0);
}

export function addTokens(a: TokenUse, b: TokenUse): TokenUse {
  return {
    input_tokens: a.input_tokens + b.input_tokens,
    cache_write_tokens: a.cache_write_tokens + b.cache_write_tokens,
    cache_read_tokens: a.cache_read_tokens + b.cache_read_tokens,
    output_tokens: a.output_tokens + b.output_tokens,
  };
}

export function costUsd(use: TokenUse, price: Price = PRICES[MODEL]): number {
  return (use.input_tokens * price.input + use.cache_write_tokens * price.cache_write +
    use.cache_read_tokens * price.cache_read + use.output_tokens * price.output) / 1e6;
}

export function utcDayStart(at: Date): string {
  return `${at.toISOString().slice(0, 10)}T00:00:00Z`;
}

export function utcMonthStart(at: Date): string {
  return `${at.toISOString().slice(0, 7)}-01T00:00:00Z`;
}

const micro = (amount: number) => Math.round(amount * 1e6) / 1e6;

export function spendState(spent: { day: number; month: number }, at: Date, enabled: boolean | null): SpendState {
  return {
    day: { spent_usd: micro(spent.day), starts_at: utcDayStart(at) },
    month: { spent_usd: micro(spent.month), starts_at: utcMonthStart(at) },
    enabled,
  };
}

export function usd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/** The plain-words spend line (panel, Slack answer). */
export function spendLine(state: SpendState): string {
  return `Assistant spend: ${usd(state.day.spent_usd)} today and ${usd(state.month.spent_usd)} this month (UTC).`;
}
