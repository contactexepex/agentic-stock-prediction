// The explain tool (docs/SPEC.md F11; mcp/tools.yaml `explain`): one question answered from the stored data through
// the read tools of B5's tool layer, with citations checked and every answer's cost logged.
//
// Order: kill switch (agent `assistant` in inbox.controls) -> API key -> the question logged (a question that asks
// for advice is declined without a model call) -> at most MAX_ROUNDS model calls, none started after DEADLINE_MS ->
// citations verified, advice replaced by the decline -> the answer and its real cost logged. No money budget in code
// (owner decision 2026-10-08): the Anthropic console's workspace spend limit is the only one; the spend is shown. A refusal is retried server-side on FALLBACK_MODEL (owner decision 2026-10-08); each
// attempt is charged at its own model's price. A question may continue a conversation: its last HISTORY_TURNS
// questions and answers go before it as plain text. Research only: no tool here writes anything outside the conversation log.
import Anthropic from "@anthropic-ai/sdk";
import type { CallContext, ToolArgs, ToolOutcome } from "../tools/types.ts";
import type { ReadData } from "../tools/reads.ts";
import { redact } from "../tools/text.ts";
import {
  CONVERSATION_PATTERN, DEADLINE_MS, FALLBACK_BETA, FALLBACK_MODEL, HISTORY_ANSWER_CHARS, HISTORY_TURNS,
  MAX_ROUNDS, MAX_TOKENS, MAX_TOOL_CALLS, MODEL, READ_TOOLS, RETENTION_DAYS,
  SLACK_CONVERSATION_MINUTES, TOOL_RESULT_MAX_CHARS,
} from "./constants.ts";
import {
  NO_TOKENS, type TokenUse, addTokens, responseCostUsd, spendState, tokensOf, utcDayStart, utcMonthStart,
} from "./cost.ts";
import { ANSWER_SCHEMA, SYSTEM_PROMPT, historyTurns, readToolDefinitions, userTurn } from "./prompt.ts";
import { ADVICE_DECLINE, type ReadText, asksForAdvice, quotedQuestion, readsAsAdvice, verifyCitations } from "./guard.ts";
import type {
  AnswerRecord, AnswerRow, AnswerSource, AnswerStatus, ConversationStore, ExplainAnswer, Explainer,
  HistoryTurn, ModelClient, ReadTool, SpendState,
} from "./types.ts";

export interface ExplainerDeps {
  store: ConversationStore;
  /** null when ANTHROPIC_API_KEY is not set: every question then fails before anything is reserved. */
  model: ModelClient | null;
  clock: () => Date;
  secrets: string[];
  newId: () => string;
}

export const NOT_CONFIGURED = "The assistant is not set up yet (no Claude API key), so nothing was asked.";
export const SWITCHED_OFF = "The assistant is switched off by the owner, so nothing was asked.";
export const LOG_DOWN = "The conversation log is unavailable, so nothing was asked.";
export const STOPPED =
  "Stopped before an answer: this question needed more reading than one answer has time for. Ask about one " +
  "company, one strategy or one day.";
export const UNCITED =
  "Not in the data: the answer could not be tied to a stored record, so it is not shown.";
export const MODEL_DECLINED = "The model declined to answer this question.";

interface Outcome {
  status: AnswerStatus;
  text: string;
  cited: AnswerRecord["cited"];
  not_in_data: boolean;
  declined: AnswerRecord["declined"];
}

interface Run {
  outcome: Outcome;
  tokens: TokenUse;
  /** Each attempt at its own model's price (cost.ts responseCostUsd). */
  cost: number;
  /** The model that produced the last response (MODEL, or the fallback model). */
  model: string;
  calls: number;
  toolCalls: number;
  sources: AnswerSource[];
  error: string | null;
}

const MARKETS = new Set(["india", "us"]);

function cut(text: string): string {
  return text.length <= TOOL_RESULT_MAX_CHARS ? text : `${text.slice(0, TOOL_RESULT_MAX_CHARS)} [cut]`;
}

function textOf(message: Anthropic.Beta.BetaMessage): string {
  return message.content.filter((block): block is Anthropic.Beta.BetaTextBlock => block.type === "text").map((block) => block.text).join("");
}

function parseAnswer(raw: string): { text: string; cited: { id: string; kind: string }[]; not_in_data: boolean; declined: string } | null {
  try {
    const value = JSON.parse(raw) as Record<string, unknown>;
    if (typeof value.text !== "string" || !Array.isArray(value.cited) || typeof value.not_in_data !== "boolean") return null;
    const cited = value.cited.filter((item): item is { id: string; kind: string } =>
      !!item && typeof item === "object" && typeof (item as { id?: unknown }).id === "string" &&
      typeof (item as { kind?: unknown }).kind === "string");
    return { text: value.text, cited, not_in_data: value.not_in_data, declined: String(value.declined ?? "none") };
  } catch {
    return null;
  }
}

function sourcesOf(outcome: ToolOutcome): { sources: AnswerSource[]; parts: ReadText["sources"] } {
  const data = outcome.data as ReadData | undefined;
  const list = Array.isArray(data?.sources) ? data.sources : [];
  const sources = list.map((item) => ({ read_model: item.read_model, page_key: item.page_key, found: item.found, as_of: item.as_of }));
  return { sources, parts: list.map((item, index) => ({ source: sources[index], text: JSON.stringify(item.payload ?? null) })) };
}

/** A model error in words that carry no driver or key text out. */
function modelError(error: unknown): string {
  if (error instanceof Anthropic.RateLimitError) return "The Claude API is rate limited now; try again in a minute.";
  if (error instanceof Anthropic.AuthenticationError || error instanceof Anthropic.PermissionDeniedError) {
    return "The Claude API refused the key; the owner can check it.";
  }
  if (error instanceof Anthropic.APIError && typeof error.status === "number") {
    return `The Claude API answered ${error.status}; try again later.`;
  }
  return "The Claude API could not be reached; try again later.";
}

export class AssistantExplainer implements Explainer {
  readonly deps: ExplainerDeps;

  constructor(deps: ExplainerDeps) {
    this.deps = deps;
  }

  async explain(ctx: CallContext, args: ToolArgs, read: ReadTool): Promise<ExplainAnswer> {
    const { store, clock, secrets } = this.deps;
    const market = String(args.market);
    if (!MARKETS.has(market)) return { result: "refused", refusal_code: "validation_failed", message: "Unknown market", data: null };
    const question = redact(quotedQuestion(String(args.question ?? "")), secrets);
    if (!question) return { result: "refused", refusal_code: "validation_failed", message: "Ask a question", data: null };
    let enabled: boolean | null;
    try {
      enabled = await store.enabled();
    } catch {
      return { result: "failed", refusal_code: null, message: LOG_DOWN, data: null };
    }
    if (enabled === false) return { result: "refused", refusal_code: "kill_switch", message: SWITCHED_OFF, data: null };
    const model = this.deps.model;
    if (!model) return { result: "failed", refusal_code: null, message: NOT_CONFIGURED, data: null };

    const now = clock();
    const askedAt = now.toISOString();
    const advice = asksForAdvice(question);
    const id = `ask-${market}-${askedAt.slice(0, 10)}-${this.deps.newId()}`;
    const ticker = typeof args.ticker === "string" ? args.ticker : null;
    const strategyId = typeof args.strategy_id === "string" ? args.strategy_id.slice(0, 80) : null;
    let conversationId = id;
    let history: HistoryTurn[] = [];
    try {
      conversationId = await this.conversation(ctx, market, args.conversation_id, now) ?? id;
      if (conversationId !== id) history = await store.history(conversationId, ctx.actor, market, HISTORY_TURNS);
      await store.ask({
        id, market, channel: ctx.channel, actor: ctx.actor, agent: ctx.agent, question, ticker, strategy_id: strategyId,
        asked_at: askedAt, conversation_id: conversationId,
      });
    } catch {
      return { result: "failed", refusal_code: null, message: LOG_DOWN, data: null };
    }
    await store.purge(new Date(now.getTime() - RETENTION_DAYS * 86400000).toISOString()).catch(() => undefined);

    const run: Run = advice
      ? { outcome: { status: "declined", text: ADVICE_DECLINE, cited: [], not_in_data: false, declined: "advice" },
        tokens: NO_TOKENS, cost: 0, model: MODEL, calls: 0, toolCalls: 0, sources: [], error: null }
      : await this.run(model, read, market as "india" | "us", askedAt, question, ticker, strategyId, history, now.getTime());
    // A call that ended without an API answer (a timeout, a lost connection) has no usage to log; the Anthropic console
    // shows what it billed.
    const cost = run.cost;
    const text = redact(run.outcome.text, secrets).slice(0, 4000);
    const row: AnswerRow = {
      id, status: run.outcome.status, text, cited: run.outcome.cited, sources: run.sources,
      not_in_data: run.outcome.not_in_data, declined: run.outcome.declined, model: run.model, ...run.tokens,
      model_calls: run.calls, tool_calls: run.toolCalls, cost_usd: cost, completed_at: clock().toISOString(),
    };
    // A failed log write still returns the answer; the question stays in the log as pending.
    const logged = await store.answer(row).then(() => true, () => false);
    const spend = await this.spend(now, enabled);
    const answer: AnswerRecord = {
      id, market: market as "india" | "us", channel: ctx.channel, asked_at: askedAt, question, text,
      cited_ids: run.outcome.cited.map((item) => item.id), cited: run.outcome.cited, as_of: askedAt,
      not_in_data: run.outcome.not_in_data, declined: run.outcome.declined, status: run.outcome.status,
      sources: run.sources, cost_usd: cost, conversation_id: conversationId, history_turns: history.length,
    };
    const data = { answer, spend, logged };
    if (run.outcome.status === "failed") return { result: "failed", refusal_code: null, message: run.error ?? text, data };
    return { result: "accepted", refusal_code: null, message: run.outcome.status.replace(/_/g, " "), data };
  }

  /** The conversation a question continues, or null for a new one. An explicit id continues only a conversation of
   * the same asker and market (anything else starts a new one). Without one, Slack /ask continues the asker's latest
   * conversation in the market when its last question is under SLACK_CONVERSATION_MINUTES old (Slack has no way to
   * pass an id); the dashboard panel always sends one to continue. */
  private async conversation(ctx: CallContext, market: string, requested: unknown, now: Date): Promise<string | null> {
    if (typeof requested === "string" && CONVERSATION_PATTERN.test(requested)) {
      return (await this.deps.store.owns(requested, ctx.actor, market)) ? requested : null;
    }
    if (ctx.channel !== "slack") return null;
    const since = new Date(now.getTime() - SLACK_CONVERSATION_MINUTES * 60000).toISOString();
    return this.deps.store.latestConversation(ctx.actor, market, since);
  }

  /** The spend now, or null when the log cannot be read. */
  async spend(at: Date, enabled: boolean | null): Promise<SpendState | null> {
    try {
      return spendState(await this.deps.store.spend(utcDayStart(at), utcMonthStart(at)), at, enabled);
    } catch {
      return null;
    }
  }

  private async run(model: ModelClient, read: ReadTool, market: "india" | "us", askedAt: string, question: string,
    ticker: string | null, strategyId: string | null, history: HistoryTurn[], started: number): Promise<Run> {
    // `started` is when the question arrived (before its log statements), so the deadline covers them too.
    const tools = readToolDefinitions();
    const messages: Anthropic.Beta.BetaMessageParam[] = [
      ...historyTurns(history, HISTORY_ANSWER_CHARS),
      { role: "user", content: userTurn({ market, askedAt, question, ticker, strategyId }) },
    ];
    const reads: ReadText[] = [];
    const sources: AnswerSource[] = [];
    let tokens = NO_TOKENS;
    let cost = 0;
    let served: string = MODEL;
    let calls = 0;
    let toolCalls = 0;
    const result = (outcome: Outcome, error: string | null = null): Run => ({ outcome, tokens, cost, model: served, calls,
      toolCalls, sources, error });
    const failed = (text: string) => result({ status: "failed", text, cited: [], not_in_data: false, declined: null }, text);
    for (let round = 1; round <= MAX_ROUNDS; round += 1) {
      const last = round === MAX_ROUNDS || toolCalls >= MAX_TOOL_CALLS;
      const params: Anthropic.Beta.Messages.MessageCreateParamsNonStreaming = {
        model: MODEL,
        max_tokens: MAX_TOKENS,
        system: [{ type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }],
        tools,
        tool_choice: last ? { type: "none" } : { type: "auto" },
        messages,
        output_config: { effort: "low", format: { type: "json_schema", schema: ANSWER_SCHEMA as unknown as Record<string, unknown> } },
        betas: [FALLBACK_BETA],
        fallbacks: [{ model: FALLBACK_MODEL }],
      };
      if (this.deps.clock().getTime() - started > DEADLINE_MS) {
        return result({ status: "stopped", text: STOPPED, cited: [], not_in_data: true, declined: null });
      }
      let response: Anthropic.Beta.BetaMessage;
      try {
        response = await model.create(params);
      } catch (error) {
        return failed(modelError(error));
      }
      calls += 1;
      served = typeof response.model === "string" ? response.model : MODEL;
      tokens = addTokens(tokens, tokensOf(response.usage, served));
      cost += responseCostUsd(response.usage, served);
      if (response.stop_reason === "refusal") {
        return result({ status: "declined", text: MODEL_DECLINED, cited: [], not_in_data: false, declined: "refused" });
      }
      const uses = response.content.filter((block): block is Anthropic.Beta.BetaToolUseBlock => block.type === "tool_use");
      if (response.stop_reason === "tool_use" && uses.length && !last) {
        messages.push({ role: "assistant", content: response.content });
        const results: Anthropic.Beta.BetaToolResultBlockParam[] = [];
        for (const use of uses) {
          if (toolCalls >= MAX_TOOL_CALLS) {
            results.push({ type: "tool_result", tool_use_id: use.id, is_error: true,
              content: "Not read: this question has used its tool calls; answer from what was read." });
            continue;
          }
          if (this.deps.clock().getTime() - started > DEADLINE_MS) {
            results.push({ type: "tool_result", tool_use_id: use.id, is_error: true, content: "Not read: out of time." });
            continue;
          }
          if (!(READ_TOOLS as readonly string[]).includes(use.name)) {
            results.push({ type: "tool_result", tool_use_id: use.id, is_error: true,
              content: `Not read: ${use.name.slice(0, 40)} is not one of the assistant's read tools.` });
            continue;
          }
          toolCalls += 1;
          const input = use.input && typeof use.input === "object" ? (use.input as ToolArgs) : {};
          const outcome = await read(use.name, { ...input, market });
          if (outcome.result !== "accepted") {
            results.push({ type: "tool_result", tool_use_id: use.id, is_error: true, content: `Not read: ${outcome.message ?? outcome.result}` });
            continue;
          }
          const seen = sourcesOf(outcome);
          sources.push(...seen.sources);
          const text = cut(JSON.stringify(outcome.data ?? null));
          reads.push({ text, sources: seen.parts });
          results.push({ type: "tool_result", tool_use_id: use.id, content: text });
        }
        messages.push({ role: "user", content: results });
        continue;
      }
      if (response.stop_reason === "max_tokens") return failed("The answer was cut off at its length limit; ask a narrower question.");
      const parsed = parseAnswer(textOf(response));
      if (!parsed) return failed("The answer could not be read, so nothing is shown.");
      return result(this.checked(parsed, reads));
    }
    return result({ status: "stopped", text: STOPPED, cited: [], not_in_data: true, declined: null });
  }

  /** The deterministic checks on the model's answer (guard.ts). */
  private checked(parsed: NonNullable<ReturnType<typeof parseAnswer>>, reads: ReadText[]): Outcome {
    if (parsed.declined === "advice" || readsAsAdvice(parsed.text)) {
      return { status: "declined", text: ADVICE_DECLINE, cited: [], not_in_data: false, declined: "advice" };
    }
    const { kept, dropped } = verifyCitations(parsed.cited, reads);
    if (parsed.not_in_data) return { status: "not_in_data", text: parsed.text, cited: kept, not_in_data: true, declined: null };
    if (kept.length === 0) return { status: "not_in_data", text: UNCITED, cited: [], not_in_data: true, declined: null };
    const note = dropped.length ? " (Some cited ids were not in the data read and were removed.)" : "";
    return { status: "answered", text: parsed.text + note, cited: kept, not_in_data: false, declined: null };
  }
}
