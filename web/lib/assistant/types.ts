// Types of the assistant (docs/SPEC.md F11; docs/DATA_CATALOGUE.md "Assistant answer"). Research only: an answer
// explains stored data and cites it; it never advises a real trade.
import type Anthropic from "@anthropic-ai/sdk";
import type { ToolArgs, ToolOutcome } from "../tools/types.ts";
import type { CitedKind } from "./constants.ts";

export interface CitedRecord {
  id: string;
  kind: CitedKind;
  /** The as-of time of the read model the id was found in (the data it was read from). */
  as_of: string | null;
  /** The read model and page key the id was found in. */
  source: string;
}

/** Where the answer's data came from: one row per read-model lookup the read tools made. */
export interface AnswerSource {
  read_model: string;
  page_key: string;
  found: boolean;
  as_of: string | null;
}

/** One answer, as the explain tool returns it and the page shows it (catalogue entity `assistant_answer`). */
export interface AnswerRecord {
  id: string;
  market: "india" | "us";
  channel: string;
  asked_at: string;
  question: string;
  text: string;
  cited_ids: string[];
  cited: CitedRecord[];
  /** The data time the answer reads up to: the moment it was asked (nothing later exists to read). */
  as_of: string;
  not_in_data: boolean;
  /** `advice`: asked for advice or a real trade; `refused`: the model declined; else null. */
  declined: "advice" | "refused" | null;
  /** answered | not_in_data | declined | stopped (budget per question) | failed */
  status: AnswerStatus;
  sources: AnswerSource[];
  cost_usd: number;
  /** The conversation (the id of its first question) and how many earlier turns this answer was given. */
  conversation_id: string;
  history_turns: number;
}

/** One earlier question and answer of a conversation, sent before a new question (multi-turn). */
export interface HistoryTurn {
  id: string;
  asked_at: string;
  question: string;
  text: string;
}

export type AnswerStatus = "answered" | "not_in_data" | "declined" | "stopped" | "failed" | "pending";

export interface SpendWindow {
  spent_usd: number;
  budget_usd: number;
  left_usd: number;
}

/** The budget state the panel shows (F11: "over budget the panel says so"). */
export interface BudgetState {
  day: SpendWindow & { starts_at: string };
  month: SpendWindow & { starts_at: string };
  /** The cost reserved per question; a question is refused when either window has less left. */
  question_usd: number;
  over_budget: boolean;
  /** false when the kill switch (agent `assistant`) is off; null when unknown. */
  enabled: boolean | null;
}

export interface QuestionRow {
  id: string;
  market: string;
  channel: string;
  actor: string;
  agent: string;
  question: string;
  ticker: string | null;
  strategy_id: string | null;
  asked_at: string;
  reserved_usd: number;
  conversation_id: string;
}

export interface AnswerRow {
  id: string;
  status: AnswerStatus;
  text: string;
  cited: CitedRecord[];
  sources: AnswerSource[];
  not_in_data: boolean;
  declined: string | null;
  model: string;
  input_tokens: number;
  cache_write_tokens: number;
  cache_read_tokens: number;
  output_tokens: number;
  model_calls: number;
  tool_calls: number;
  cost_usd: number;
  completed_at: string;
}

/** The conversation log and budget in MotherDuck schema `app` (market_brief_inbox; app.sql). */
export interface ConversationStore {
  /** Inserts the question unless the day's or the month's spend plus `reserved_usd` would pass its cap. */
  reserve(row: QuestionRow, caps: { dayStart: string; monthStart: string; dayUsd: number; monthUsd: number }): Promise<boolean>;
  answer(row: AnswerRow): Promise<void>;
  spend(dayStart: string, monthStart: string): Promise<{ day: number; month: number }>;
  /** The kill switch of the assistant agent in inbox.controls (newest row of `assistant` and of `*`). */
  enabled(): Promise<boolean | null>;
  /** Whether conversation `id` exists and was asked by this actor in this market. */
  owns(id: string, actor: string, market: string): Promise<boolean>;
  /** The conversation of the actor's newest question in the market asked at or after `since`, or null. */
  latestConversation(actor: string, market: string, since: string): Promise<string | null>;
  /** The last `limit` finished turns of a conversation by this actor and market, oldest first. */
  history(conversationId: string, actor: string, market: string, limit: number): Promise<HistoryTurn[]>;
  /** The market's answers asked since `since`, newest first, at most `limit`. */
  list(market: string, since: string, limit: number): Promise<AnswerRecord[]>;
  /** Deletes questions and answers asked before `before` (the 90-day retention). */
  purge(before: string): Promise<void>;
}

/** The part of the Anthropic client the assistant uses; tests pass a mock. */
export interface ModelClient {
  create(params: Anthropic.Beta.Messages.MessageCreateParamsNonStreaming): Promise<Anthropic.Beta.BetaMessage>;
}

/** The explain hook of B5's tool layer (ToolDeps.explainer) and its answer, defined in web/lib/tools/types.ts. */
export type { ExplainAnswer, Explainer } from "../tools/types.ts";

export type ReadTool = (tool: string, args: ToolArgs) => Promise<ToolOutcome>;
