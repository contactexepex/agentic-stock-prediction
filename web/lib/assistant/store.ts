// The conversation log in MotherDuck market_brief_inbox, schema `app` (app.sql), through B5's Postgres-endpoint query
// function (pool size 1, statement timeout 5 s, TLS verified). Errors never carry driver text out.
import { AGENT } from "./constants.ts";
import { APP_SQL as SQL } from "./sql.ts";
import type { AnswerRecord, AnswerRow, AnswerStatus, ConversationStore, HistoryTurn, QuestionRow } from "./types.ts";

export type Query = (text: string, values: unknown[]) => Promise<{ rows: Record<string, unknown>[] }>;

function iso(value: unknown): string {
  return value instanceof Date ? value.toISOString() : String(value ?? "");
}

function list(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

const truthy = (value: unknown) => value === true || value === "true" || value === "t";

/** A stored question with its answer (or none yet) as the page and the panel show it. */
export function recordFrom(row: Record<string, unknown>): AnswerRecord {
  const status = (row.status === null || row.status === undefined ? "pending" : String(row.status)) as AnswerStatus;
  const cited = list(row.cited) as AnswerRecord["cited"];
  const declined = row.declined === "advice" || row.declined === "refused" ? row.declined : null;
  const askedAt = iso(row.asked_at);
  return {
    id: String(row.id), market: String(row.market) as AnswerRecord["market"], channel: String(row.channel),
    asked_at: askedAt, question: String(row.question), text: row.text === null || row.text === undefined ? "" : String(row.text),
    cited_ids: cited.map((item) => item.id), cited, as_of: askedAt, not_in_data: truthy(row.not_in_data), declined, status,
    sources: list(row.sources) as AnswerRecord["sources"], cost_usd: Number(row.cost_usd ?? 0),
    conversation_id: row.conversation_id ? String(row.conversation_id) : String(row.id), history_turns: 0,
  };
}

export class MotherDuckConversationStore implements ConversationStore {
  readonly query: Query;

  constructor(query: Query) {
    this.query = query;
  }

  async reserve(row: QuestionRow, caps: { dayStart: string; monthStart: string; dayUsd: number; monthUsd: number }): Promise<boolean> {
    const { rows } = await this.query(SQL.reserve, [row.id, row.market, row.channel, row.actor, row.agent, row.question,
      row.ticker, row.strategy_id, row.asked_at, row.reserved_usd, caps.dayStart, caps.monthStart, caps.dayUsd, caps.monthUsd,
      row.conversation_id]);
    return rows.length > 0;
  }

  async answer(row: AnswerRow): Promise<void> {
    await this.query(SQL.answer, [row.id, row.status, row.text, JSON.stringify(row.cited), JSON.stringify(row.sources),
      row.not_in_data, row.declined, row.model, row.input_tokens, row.cache_write_tokens, row.cache_read_tokens,
      row.output_tokens, row.model_calls, row.tool_calls, row.cost_usd, row.completed_at]);
  }

  async spend(dayStart: string, monthStart: string): Promise<{ day: number; month: number }> {
    const { rows } = await this.query(SQL.spend, [dayStart, monthStart]);
    return { day: Number(rows[0]?.day ?? 0), month: Number(rows[0]?.month ?? 0) };
  }

  async enabled(): Promise<boolean | null> {
    const { rows } = await this.query(SQL.enabled, [AGENT]);
    const value = rows[0]?.enabled;
    return value === null || value === undefined ? null : truthy(value);
  }

  async owns(id: string, actor: string, market: string): Promise<boolean> {
    const { rows } = await this.query(SQL.owns, [id, actor, market]);
    return Number(rows[0]?.n ?? 0) > 0;
  }

  async latestConversation(actor: string, market: string, since: string): Promise<string | null> {
    const { rows } = await this.query(SQL.latestConversation, [actor, market, since]);
    return rows[0] ? String(rows[0].conversation_id) : null;
  }

  async history(conversationId: string, actor: string, market: string, limit: number): Promise<HistoryTurn[]> {
    const { rows } = await this.query(SQL.history, [conversationId, actor, market, limit]);
    return rows.map((row) => ({ id: String(row.id), asked_at: iso(row.asked_at), question: String(row.question),
      text: String(row.text ?? "") })).reverse();
  }

  async list(market: string, since: string, limit: number): Promise<AnswerRecord[]> {
    const { rows } = await this.query(SQL.list, [market, since, limit]);
    return rows.map(recordFrom);
  }

  async purge(before: string): Promise<void> {
    await this.query(SQL.purgeAnswers, [before]);
    await this.query(SQL.purgeQuestions, [before]);
  }
}
