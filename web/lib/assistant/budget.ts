// Cost of model calls and the day / month windows of the budget (F11). Every figure is in USD.
import type Anthropic from "@anthropic-ai/sdk";
import { DAILY_USD, MAX_TOKENS, MONTHLY_USD, PRICE_PER_MTOK, QUESTION_USD } from "./constants.ts";
import type { BudgetState } from "./types.ts";

export interface TokenUse {
  input_tokens: number;
  cache_write_tokens: number;
  cache_read_tokens: number;
  output_tokens: number;
}

export const NO_TOKENS: TokenUse = { input_tokens: 0, cache_write_tokens: 0, cache_read_tokens: 0, output_tokens: 0 };

export function tokensOf(usage: Anthropic.Usage | null | undefined): TokenUse {
  return {
    input_tokens: usage?.input_tokens ?? 0,
    cache_write_tokens: usage?.cache_creation_input_tokens ?? 0,
    cache_read_tokens: usage?.cache_read_input_tokens ?? 0,
    output_tokens: usage?.output_tokens ?? 0,
  };
}

export function addTokens(a: TokenUse, b: TokenUse): TokenUse {
  return {
    input_tokens: a.input_tokens + b.input_tokens,
    cache_write_tokens: a.cache_write_tokens + b.cache_write_tokens,
    cache_read_tokens: a.cache_read_tokens + b.cache_read_tokens,
    output_tokens: a.output_tokens + b.output_tokens,
  };
}

export function costUsd(use: TokenUse): number {
  return (use.input_tokens * PRICE_PER_MTOK.input + use.cache_write_tokens * PRICE_PER_MTOK.cache_write +
    use.cache_read_tokens * PRICE_PER_MTOK.cache_read + use.output_tokens * PRICE_PER_MTOK.output) / 1e6;
}

/** An upper bound of one call's cost before it is made: every input byte counted as half a token (JSON and English
 * run at three or more bytes per token), all of it priced as a cache write (the dearest input), plus a fixed
 * allowance for the output schema the API adds, and the full MAX_TOKENS of output. */
export function callCeilingUsd(params: Anthropic.MessageCreateParamsNonStreaming): number {
  const { max_tokens: _max, ...request } = params;
  const inputTokens = Math.ceil(new TextEncoder().encode(JSON.stringify(request)).length / 2) + 1000;
  return (inputTokens * PRICE_PER_MTOK.cache_write + MAX_TOKENS * PRICE_PER_MTOK.output) / 1e6;
}

export function utcDayStart(at: Date): string {
  return `${at.toISOString().slice(0, 10)}T00:00:00Z`;
}

export function utcMonthStart(at: Date): string {
  return `${at.toISOString().slice(0, 7)}-01T00:00:00Z`;
}

const micro = (amount: number) => Math.round(amount * 1e6) / 1e6;

export function budgetState(spent: { day: number; month: number }, at: Date, enabled: boolean | null): BudgetState {
  const day = { spent_usd: micro(spent.day), budget_usd: DAILY_USD, left_usd: micro(Math.max(0, DAILY_USD - spent.day)),
    starts_at: utcDayStart(at) };
  const month = { spent_usd: micro(spent.month), budget_usd: MONTHLY_USD,
    left_usd: micro(Math.max(0, MONTHLY_USD - spent.month)), starts_at: utcMonthStart(at) };
  return { day, month, question_usd: QUESTION_USD,
    over_budget: day.left_usd < QUESTION_USD || month.left_usd < QUESTION_USD, enabled };
}

export function usd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/** The plain-words budget line (panel footer, Slack answer, refusal message). */
export function budgetLine(state: BudgetState): string {
  return `Assistant budget: ${usd(state.day.spent_usd)} of ${usd(state.day.budget_usd)} used today (UTC), ` +
    `${usd(state.month.spent_usd)} of ${usd(state.month.budget_usd)} this month.`;
}
