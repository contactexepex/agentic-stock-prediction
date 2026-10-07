// MotherDuck through its Postgres endpoint (ARCHITECTURE.md section 6): the read models in market_brief with
// MOTHERDUCK_READ_TOKEN, the inbox in market_brief_inbox with MOTHERDUCK_INBOX_TOKEN (its own service account).
// Pool size 1, statement timeout 5 s, TLS verified, no retries inside a request. Errors never carry driver text out.
import pg from "pg";
import type { AgentUsage, CommandLogRow, InboxRequest, InboxStore, ReadModelRow, ReadStore, StoredRequest } from "./types.ts";
import { READ_MODEL_TABLES } from "./reads.ts";
import { INBOX_SQL_STATEMENTS as SQL, READ_MODEL_COLUMNS } from "./sql.ts";

export interface PgSettings {
  host: string;
  database: string;
  token: string | null;
}

type Query = (text: string, values: unknown[]) => Promise<{ rows: Record<string, unknown>[] }>;

export function pgQuery(settings: PgSettings): Query {
  let pool: pg.Pool | null = null;
  return async (text, values) => {
    if (!settings.token) throw new Error("token not configured");
    pool ??= new pg.Pool({
      host: settings.host, port: 5432, user: "postgres", password: settings.token, database: settings.database,
      ssl: { rejectUnauthorized: true }, max: 1, statement_timeout: 5000, connectionTimeoutMillis: 5000,
      idleTimeoutMillis: 10000,
    });
    const result = await pool.query(text, values);
    return { rows: result.rows as Record<string, unknown>[] };
  };
}

function iso(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return value instanceof Date ? value.toISOString() : String(value);
}

function json(value: unknown): unknown {
  if (typeof value !== "string") return value ?? null;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

export class MotherDuckReadStore implements ReadStore {
  readonly query: Query;

  constructor(query: Query) {
    this.query = query;
  }

  async readModel(table: string, market: string, pageKey: string): Promise<ReadModelRow | null> {
    if (!(READ_MODEL_TABLES as readonly string[]).includes(table)) throw new Error("unknown read model");
    const { rows } = await this.query(
      `SELECT ${READ_MODEL_COLUMNS} FROM rm.${table} WHERE market = $1 AND page_key = $2`,
      [market, pageKey],
    );
    const row = rows[0];
    if (!row) return null;
    return {
      market: String(row.market), page_key: String(row.page_key), as_of: iso(row.as_of), cutoff: iso(row.cutoff),
      built_at: iso(row.built_at), schema_version: row.schema_version === null ? null : String(row.schema_version),
      source_commit: row.source_commit === null ? null : String(row.source_commit),
      payload_sha256: row.payload_sha256 === null ? null : String(row.payload_sha256), payload: json(row.payload),
    };
  }
}

function storedFrom(row: Record<string, unknown>): StoredRequest {
  return {
    inbox_id: String(row.inbox_id), tool: String(row.tool), submitted_by: String(row.submitted_by),
    command_id: String(row.command_id), args_sha256: String(row.args_sha256),
  };
}

/** Company commands go to B1's inbox.company_commands; every other write (add_paper_trade) to inbox.requests. */
export const COMPANY_KIND = "watchlist_events";

export class MotherDuckInboxStore implements InboxStore {
  readonly query: Query;

  constructor(query: Query) {
    this.query = query;
  }

  async usage(agent: string, sinceIso: string): Promise<AgentUsage> {
    const { rows } = await this.query(SQL.usage, [agent, sinceIso]);
    const row = rows[0] ?? {};
    return {
      writes: Number(row.writes ?? 0),
      reads: Number(row.reads ?? 0),
      enabled: row.enabled === null || row.enabled === undefined ? null : row.enabled === true || row.enabled === "true",
    };
  }

  async claimRequest(row: InboxRequest, budget: { sinceIso: string; limit: number }): Promise<{ claimed: boolean; existing: StoredRequest | null }> {
    const preview = row.preview === null ? null : JSON.stringify(row.preview);
    const insert = () => row.kind === COMPANY_KIND
      ? this.query(SQL.claimCompany,
        [row.inbox_id, row.market, row.tool, JSON.stringify(row.arguments), row.submitted_by, row.channel, row.submitted_at,
          row.command_id, preview, row.agent, row.args_sha256, budget.sinceIso, budget.limit, row.slack_channel, row.slack_ts])
      : this.query(SQL.claimRequest,
        [row.inbox_id, row.kind, row.tool, row.market, JSON.stringify(row.arguments), preview, row.channel, row.submitted_by,
          row.agent, row.command_id, row.submitted_at, row.args_sha256, budget.sinceIso, budget.limit, row.slack_channel,
          row.slack_ts]);
    let inserted;
    try {
      inserted = await insert();
    } catch (error) {
      // Two concurrent claims of one key: the second fails on the primary key. Answer with the stored row; any other
      // failure (or a failed lookup) rethrows the INSERT's own error.
      const stored = await this.query(SQL.existing, [row.inbox_id]).then(({ rows }) => rows[0] ?? null, () => null);
      if (stored) return { claimed: false, existing: storedFrom(stored) };
      throw error;
    }
    if (inserted.rows.length) return { claimed: true, existing: null };
    const { rows } = await this.query(SQL.existing, [row.inbox_id]);
    return { claimed: false, existing: rows[0] ? storedFrom(rows[0]) : null };
  }

  async appendCommand(row: CommandLogRow): Promise<void> {
    await this.query(SQL.append,
      [row.id, row.market, row.received_at, row.channel, row.actor, row.agent, row.tool, row.kind,
        JSON.stringify(row.arguments), row.idempotency_key, row.result, row.refusal_code, row.message,
        JSON.stringify(row.record_ids), row.budget_left, row.completed_at],
    );
  }

  async findCommand(id: string): Promise<CommandLogRow | null> {
    const { rows } = await this.query(SQL.find, [id]);
    const row = rows[0];
    if (!row) return null;
    const recordIds = json(row.record_ids);
    return {
      id: String(row.id), market: row.market === null ? null : String(row.market), received_at: iso(row.received_at) ?? "",
      channel: String(row.channel) as CommandLogRow["channel"], actor: String(row.actor), agent: String(row.agent),
      tool: row.tool === null ? null : String(row.tool), kind: row.kind as CommandLogRow["kind"], arguments: json(row.arguments),
      idempotency_key: row.idempotency_key === null ? null : String(row.idempotency_key),
      result: String(row.result) as CommandLogRow["result"], refusal_code: row.refusal_code as CommandLogRow["refusal_code"],
      message: row.message === null ? null : String(row.message),
      record_ids: Array.isArray(recordIds) ? recordIds.map(String) : [],
      budget_left: row.budget_left === null ? null : Number(row.budget_left), completed_at: iso(row.completed_at) ?? "",
    };
  }
}
