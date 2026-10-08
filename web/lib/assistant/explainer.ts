// The explain tool (docs/SPEC.md F11; mcp/tools.yaml `explain`): one question answered from the stored data through
// the read tools of B5's tool layer, with citations checked and the budget enforced before every model call.
//
// Order: kill switch (agent `assistant` in inbox.controls) -> API key -> a question that asks for advice is declined
// without a model call -> the question's cost (QUESTION_USD) is reserved against the day's and the month's caps in
// one statement (over budget: refused, nothing called) -> at most MAX_ROUNDS model calls, each made only when its
// cost ceiling fits in what is left of the reservation -> citations verified, advice replaced by the decline -> the
// answer and its real cost logged. Research only: no tool here writes anything outside the conversation log.
import Anthropic from "@anthropic-ai/sdk";
import type { CallContext, ToolArgs, ToolOutcome } from "../tools/types.ts";
import type { ReadData } from "../tools/reads.ts";
import { redact } from "../tools/text.ts";
import {
  DAILY_USD, DEADLINE_MS, MAX_ROUNDS, MAX_TOKENS, MAX_TOOL_CALLS, MODEL, MONTHLY_USD, QUESTION_USD, RETENTION_DAYS,
  READ_TOOLS, TOOL_RESULT_MAX_CHARS,
} from "./constants.ts";
import {
  NO_TOKENS, type TokenUse, addTokens, budgetLine, budgetState, callCeilingUsd, costUsd, tokensOf, utcDayStart,
  utcMonthStart,
} from "./budget.ts";
import { ANSWER_SCHEMA, SYSTEM_PROMPT, readToolDefinitions, userTurn } from "./prompt.ts";
import { ADVICE_DECLINE, type ReadText, asksForAdvice, quotedQuestion, readsAsAdvice, verifyCitations } from "./guard.ts";
import type {
  AnswerRecord, AnswerRow, AnswerSource, AnswerStatus, BudgetState, ConversationStore, ExplainAnswer, Explainer,
  ModelClient, ReadTool,
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
  "Stopped before an answer: this question needed more reading than one answer may cost. Ask about one company, " +
  "one strategy or one day.";
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
  calls: number;
  toolCalls: number;
  sources: AnswerSource[];
  error: string | null;
  /** A model call ended without an API answer (a timeout or a lost connection), so it may still be billed. */
  uncertain: boolean;
}

const MARKETS = new Set(["india", "us"]);

function cut(text: string): string {
  return text.length <= TOOL_RESULT_MAX_CHARS ? text : `${text.slice(0, TOOL_RESULT_MAX_CHARS)} [cut]`;
}

function textOf(message: Anthropic.Message): string {
  return message.content.filter((block): block is Anthropic.TextBlock => block.type === "text").map((block) => block.text).join("");
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
    const reserved = advice ? 0 : QUESTION_USD;
    const id = `ask-${market}-${askedAt.slice(0, 10)}-${this.deps.newId()}`;
    const dayStart = utcDayStart(now);
    const monthStart = utcMonthStart(now);
    const ticker = typeof args.ticker === "string" ? args.ticker : null;
    const strategyId = typeof args.strategy_id === "string" ? args.strategy_id.slice(0, 80) : null;
    let admitted: boolean;
    try {
      admitted = await store.reserve({
        id, market, channel: ctx.channel, actor: ctx.actor, agent: ctx.agent, question, ticker, strategy_id: strategyId,
        asked_at: askedAt, reserved_usd: reserved,
      }, { dayStart, monthStart, dayUsd: DAILY_USD, monthUsd: MONTHLY_USD });
    } catch {
      return { result: "failed", refusal_code: null, message: LOG_DOWN, data: null };
    }
    if (!admitted) {
      const budget = await this.budget(now, enabled);
      const message = `Over budget: nothing was asked. ${budget ? budgetLine(budget) : ""}`.trim();
      return { result: "refused", refusal_code: "budget_exceeded", message, data: { budget } };
    }
    await store.purge(new Date(now.getTime() - RETENTION_DAYS * 86400000).toISOString()).catch(() => undefined);

    const run: Run = advice
      ? { outcome: { status: "declined", text: ADVICE_DECLINE, cited: [], not_in_data: false, declined: "advice" },
        tokens: NO_TOKENS, calls: 0, toolCalls: 0, sources: [], error: null, uncertain: false }
      : await this.run(model, read, market as "india" | "us", askedAt, question, ticker, strategyId);
    // A call that ended without an API answer may still be billed (a timeout the API finished), so such a failure
    // keeps at least the reservation counted.
    const cost = run.uncertain ? Math.max(costUsd(run.tokens), reserved) : costUsd(run.tokens);
    const text = redact(run.outcome.text, secrets).slice(0, 4000);
    const row: AnswerRow = {
      id, status: run.outcome.status, text, cited: run.outcome.cited, sources: run.sources,
      not_in_data: run.outcome.not_in_data, declined: run.outcome.declined, model: MODEL, ...run.tokens,
      model_calls: run.calls, tool_calls: run.toolCalls, cost_usd: cost, completed_at: clock().toISOString(),
    };
    // A failed log write keeps the reservation counted (the safe side of the budget); the answer is still returned.
    const logged = await store.answer(row).then(() => true, () => false);
    const budget = await this.budget(now, enabled);
    const answer: AnswerRecord = {
      id, market: market as "india" | "us", channel: ctx.channel, asked_at: askedAt, question, text,
      cited_ids: run.outcome.cited.map((item) => item.id), cited: run.outcome.cited, as_of: askedAt,
      not_in_data: run.outcome.not_in_data, declined: run.outcome.declined, status: run.outcome.status,
      sources: run.sources, cost_usd: cost,
    };
    const data = { answer, budget, logged };
    if (run.outcome.status === "failed") return { result: "failed", refusal_code: null, message: run.error ?? text, data };
    return { result: "accepted", refusal_code: null, message: run.outcome.status.replace(/_/g, " "), data };
  }

  /** The budget state now, or null when the log cannot be read. */
  async budget(at: Date, enabled: boolean | null): Promise<BudgetState | null> {
    try {
      return budgetState(await this.deps.store.spend(utcDayStart(at), utcMonthStart(at)), at, enabled);
    } catch {
      return null;
    }
  }

  private async run(model: ModelClient, read: ReadTool, market: "india" | "us", askedAt: string, question: string,
    ticker: string | null, strategyId: string | null): Promise<Run> {
    const started = this.deps.clock().getTime();
    const tools = readToolDefinitions();
    const messages: Anthropic.MessageParam[] = [
      { role: "user", content: userTurn({ market, askedAt, question, ticker, strategyId }) },
    ];
    const reads: ReadText[] = [];
    const sources: AnswerSource[] = [];
    let tokens = NO_TOKENS;
    let calls = 0;
    let toolCalls = 0;
    let uncertain = false;
    const result = (outcome: Outcome, error: string | null = null): Run => ({ outcome, tokens, calls, toolCalls, sources, error, uncertain });
    const failed = (text: string) => result({ status: "failed", text, cited: [], not_in_data: false, declined: null }, text);
    for (let round = 1; round <= MAX_ROUNDS; round += 1) {
      const last = round === MAX_ROUNDS || toolCalls >= MAX_TOOL_CALLS;
      const params: Anthropic.MessageCreateParamsNonStreaming = {
        model: MODEL,
        max_tokens: MAX_TOKENS,
        system: [{ type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }],
        tools,
        tool_choice: last ? { type: "none" } : { type: "auto" },
        messages,
        output_config: { effort: "low", format: { type: "json_schema", schema: ANSWER_SCHEMA as unknown as Record<string, unknown> } },
      };
      if (costUsd(tokens) + callCeilingUsd(params) > QUESTION_USD || this.deps.clock().getTime() - started > DEADLINE_MS) {
        return result({ status: "stopped", text: STOPPED, cited: [], not_in_data: true, declined: null });
      }
      let response: Anthropic.Message;
      try {
        response = await model.create(params);
      } catch (error) {
        uncertain = !(error instanceof Anthropic.APIError && typeof error.status === "number");
        return failed(modelError(error));
      }
      calls += 1;
      tokens = addTokens(tokens, tokensOf(response.usage));
      if (response.stop_reason === "refusal") {
        return result({ status: "declined", text: MODEL_DECLINED, cited: [], not_in_data: false, declined: "refused" });
      }
      const uses = response.content.filter((block): block is Anthropic.ToolUseBlock => block.type === "tool_use");
      if (response.stop_reason === "tool_use" && uses.length && !last) {
        messages.push({ role: "assistant", content: response.content });
        const results: Anthropic.ToolResultBlockParam[] = [];
        for (const use of uses) {
          if (toolCalls >= MAX_TOOL_CALLS) {
            results.push({ type: "tool_result", tool_use_id: use.id, is_error: true,
              content: "Not read: this question has used its tool calls; answer from what was read." });
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
