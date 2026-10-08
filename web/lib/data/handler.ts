// The /api/v1 read-route helper (ARCHITECTURE.md sections 6-7). A page route is a few lines:
//
//   const PAGE = definePage({ table: "home", serve: "page" });
//   export async function GET(request: Request, { params }: { params: Promise<{ market: string }> }) {
//     return readPage(request, PAGE, (await params).market, MARKET_PAGE_KEY, defaultDeps());
//   }
//
// (defaultDeps from ./deps.ts: MotherDuck behind the data cache; tests pass their own store.)
//
// It validates the market and the page key, reads the row (one keyed SELECT behind the data cache), answers 404
// for a missing row, 503 (with the static reports as fallback links) when the warehouse fails or the row is of
// another major contract version, 304 when If-None-Match equals the row's ETag, and otherwise the envelope plus the
// served payload (serve.ts) with ETag = "<payload_sha256>", Last-Modified = built_at, Cache-Control private, no-cache.
import { CONTRACT_MAJOR, MARKETS, PAGE_KEY_PATTERN, type ServeMode, TABLE_PATTERN, TICKER_PATTERN } from "./constants.ts";
import { notFound, unavailable } from "./problem.ts";
import { serve, type StoredRow } from "./serve.ts";
import { type RowStore, WarehouseUnavailable } from "./store.ts";

export interface PageSpec {
  /** The rm table (a constant of the page's module, never from input). */
  table: string;
  serve: ServeMode;
}

export interface ReadDeps {
  store: RowStore;
  now: () => Date;
}

export function definePage(spec: PageSpec): PageSpec {
  if (!TABLE_PATTERN.test(spec.table)) throw new Error(`bad read-model table ${spec.table}`);
  return Object.freeze({ ...spec });
}

export function isMarket(value: string): boolean {
  return (MARKETS as readonly string[]).includes(value);
}

export function isTicker(value: string): boolean {
  return TICKER_PATTERN.test(value);
}

/** The row of a page, or the problem response that stands in for it. */
export async function readRow(
  spec: PageSpec, market: string, pageKey: string, deps: ReadDeps,
): Promise<StoredRow | Response> {
  if (!isMarket(market)) return notFound("Unknown market");
  if (!PAGE_KEY_PATTERN.test(pageKey)) return notFound("Unknown page");
  let row: StoredRow | null;
  try {
    row = await deps.store.read(spec.table, market, pageKey);
  } catch (error) {
    if (error instanceof WarehouseUnavailable) return unavailable(market);
    throw error;
  }
  if (row === null) return notFound("No such page in the read model");
  if ((row.schema_version ?? "").split(".")[0] !== CONTRACT_MAJOR) return unavailable(market);
  return row;
}

function etagOf(row: StoredRow): string {
  return `"${row.payload_sha256 ?? ""}"`;
}

function headers(row: StoredRow): Record<string, string> {
  const out: Record<string, string> = { ETag: etagOf(row), "Cache-Control": "private, no-cache" };
  if (row.built_at) out["Last-Modified"] = new Date(row.built_at).toUTCString();
  return out;
}

export function notModified(request: Request, row: StoredRow): boolean {
  const asked = request.headers.get("if-none-match");
  if (!asked) return false;
  return asked.split(",").map((tag) => tag.trim().replace(/^W\//, "")).includes(etagOf(row));
}

/** The response of one read: 304, or the served row as JSON. */
export function respond(request: Request, spec: PageSpec, row: StoredRow, now: Date): Response {
  if (notModified(request, row)) return new Response(null, { status: 304, headers: headers(row) });
  return Response.json(serve(row, spec.serve, now), { headers: headers(row) });
}

export async function readPage(
  request: Request, spec: PageSpec, market: string, pageKey: string, deps: ReadDeps,
): Promise<Response> {
  const row = await readRow(spec, market, pageKey, deps);
  return row instanceof Response ? row : respond(request, spec, row, deps.now());
}

/** A per-ticker page: the ticker must look like one (a missing page is a 404 either way). */
export async function readTickerPage(
  request: Request, spec: PageSpec, market: string, ticker: string, deps: ReadDeps,
): Promise<Response> {
  if (!isTicker(ticker)) return notFound("Unknown ticker");
  return readPage(request, spec, market, ticker, deps);
}
