// What a route returns for a stored read-model row (ARCHITECTURE.md 4.3: the only request-time arithmetic is the
// freshness age). The same rules as scripts/marketbrief/warehouse/contract.py `serve`; the shared fixture
// tests/serve.fixture.json keeps the two equal.
//   verbatim  the payload as stored (1.0 pages)
//   page      plus `cutoff` and `built_at` at the top and `freshness` in the `status` block (2.0 page payloads)
//   status    plus `freshness` at the top (the status page)
import { FRESH_MINUTES, type ServeMode } from "./constants.ts";

export interface StoredRow {
  market: string;
  page_key: string;
  as_of: string | null;
  cutoff: string | null;
  built_at: string | null;
  schema_version: string | null;
  source_commit: string | null;
  payload_sha256: string | null;
  payload: unknown;
}

export interface Freshness {
  state: "fresh" | "stale" | "unknown";
  built_at: string | null;
  age_minutes: number | null;
}

type Json = Record<string, unknown>;

/** ISO UTC to the second with a Z (2026-10-07T12:00:00Z), or null. */
export function isoSecond(value: string | Date | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const time = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(time.getTime())) return null;
  return time.toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** YYYY-MM-DD of a date (a Date from the driver is read in UTC), or null. */
export function isoDate(value: string | Date | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return value instanceof Date ? value.toISOString().slice(0, 10) : String(value).slice(0, 10);
}

export function freshness(builtAt: string | null, now: Date): Freshness {
  const built = builtAt === null ? null : new Date(builtAt);
  if (built === null || Number.isNaN(built.getTime())) return { state: "unknown", built_at: null, age_minutes: null };
  const age = Math.max(Math.floor((now.getTime() - built.getTime()) / 60000), 0);
  return { state: age <= FRESH_MINUTES ? "fresh" : "stale", built_at: isoSecond(built), age_minutes: age };
}

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function servedPayload(row: StoredRow, mode: ServeMode, now: Date): unknown {
  const payload = typeof row.payload === "string" ? JSON.parse(row.payload) : row.payload;
  if (mode === "verbatim" || !isObject(payload)) return payload;
  const fresh = freshness(row.built_at, now);
  if (mode === "status") return { ...payload, freshness: fresh };
  const out: Json = { ...payload, cutoff: isoSecond(row.cutoff), built_at: isoSecond(row.built_at) };
  if (isObject(out.status)) out.status = { ...out.status, freshness: fresh };
  return out;
}

/** The response body: the envelope (ReadModelMeta, times to the second) and the served payload. */
export function serve(row: StoredRow, mode: ServeMode, now: Date): Json {
  return {
    market: row.market,
    page_key: row.page_key,
    as_of: isoDate(row.as_of),
    cutoff: isoSecond(row.cutoff),
    built_at: isoSecond(row.built_at),
    schema_version: row.schema_version,
    source_commit: row.source_commit,
    payload_sha256: row.payload_sha256,
    payload: servedPayload(row, mode, now),
  };
}
