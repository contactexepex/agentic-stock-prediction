// The read side of the warehouse (ARCHITECTURE.md section 6): one parameterised keyed SELECT per read, over B5's
// MotherDuck Postgres client (pool size 1, statement timeout 5 s, TLS verified, no retries). The table name is the
// page's own constant, checked against TABLE_PATTERN; it never comes from a request. Errors carry no driver text.
import { pgQuery } from "../tools/motherduck.ts";
import { MOTHERDUCK_PG_HOST, READ_DATABASE } from "../tools/constants.ts";
import { READ_MODEL_COLUMNS, TABLE_PATTERN } from "./constants.ts";
import type { StoredRow } from "./serve.ts";

export interface RowStore {
  /** The stored row of (table, market, page_key), or null when there is none. Throws WarehouseUnavailable. */
  read(table: string, market: string, pageKey: string): Promise<StoredRow | null>;
}

export class WarehouseUnavailable extends Error {
  constructor() {
    super("warehouse unavailable");
    this.name = "WarehouseUnavailable";
  }
}

type Query = (text: string, values: unknown[]) => Promise<{ rows: Record<string, unknown>[] }>;

function text(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return value instanceof Date ? value.toISOString() : String(value);
}

export function rowFrom(record: Record<string, unknown>): StoredRow {
  const asOf = record.as_of;
  return {
    market: String(record.market),
    page_key: String(record.page_key),
    as_of: asOf instanceof Date ? asOf.toISOString().slice(0, 10) : text(asOf),
    cutoff: text(record.cutoff),
    built_at: text(record.built_at),
    schema_version: text(record.schema_version),
    source_commit: text(record.source_commit),
    payload_sha256: text(record.payload_sha256),
    payload: typeof record.payload === "string" ? JSON.parse(record.payload) : (record.payload ?? null),
  };
}

export class SqlRowStore implements RowStore {
  readonly query: Query;

  constructor(query: Query) {
    this.query = query;
  }

  async read(table: string, market: string, pageKey: string): Promise<StoredRow | null> {
    if (!TABLE_PATTERN.test(table)) throw new Error("bad read-model table");
    try {
      const { rows } = await this.query(
        `SELECT ${READ_MODEL_COLUMNS} FROM rm.${table} WHERE market = $1 AND page_key = $2`, [market, pageKey]);
      return rows[0] ? rowFrom(rows[0]) : null;
    } catch {
      throw new WarehouseUnavailable();   // the driver's text (and anything in it) never leaves this function
    }
  }
}

/** The production store: MotherDuck's market_brief with MOTHERDUCK_READ_TOKEN (server env only). */
export function motherDuckStore(env: Record<string, string | undefined> = process.env): RowStore {
  const token = env.MOTHERDUCK_READ_TOKEN?.trim() || null;
  return new SqlRowStore(pgQuery({ host: MOTHERDUCK_PG_HOST, database: READ_DATABASE, token }));
}
