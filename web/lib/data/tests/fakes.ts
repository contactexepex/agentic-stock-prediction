// Test doubles of the read side: an in-memory row store and a store whose warehouse is down.
import type { RowStore } from "../store.ts";
import { WarehouseUnavailable } from "../store.ts";
import type { StoredRow } from "../serve.ts";

export class MemoryRowStore implements RowStore {
  readonly rows = new Map<string, StoredRow>();
  readonly reads: string[] = [];

  put(table: string, row: StoredRow): this {
    this.rows.set(`${table}|${row.market}|${row.page_key}`, row);
    return this;
  }

  async read(table: string, market: string, pageKey: string): Promise<StoredRow | null> {
    this.reads.push(`${table}|${market}|${pageKey}`);
    return this.rows.get(`${table}|${market}|${pageKey}`) ?? null;
  }
}

export class DownRowStore implements RowStore {
  async read(): Promise<StoredRow | null> {
    throw new WarehouseUnavailable();
  }
}

export function row(overrides: Partial<StoredRow> = {}): StoredRow {
  return {
    market: "us", page_key: "_", as_of: "2026-10-06", cutoff: "2026-10-07T11:58:00Z", built_at: "2026-10-07T11:58:00Z",
    schema_version: "1.1.0", source_commit: "abc",
    payload_sha256: "a".repeat(64), payload: { market: "us", status: { market: "us" } }, ...overrides,
  };
}

export const NOW = new Date("2026-10-07T12:00:00Z");
