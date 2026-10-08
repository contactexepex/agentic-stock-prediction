// The platform reads (B4): the status page of a market (rm.status, serve mode status) and the markets list composed
// from both markets' status pages (api/openapi.yaml listMarkets).
import { createHash } from "node:crypto";
import { MARKET_PAGE_KEY, MARKETS } from "./constants.ts";
import { definePage, type ReadDeps, readRow } from "./handler.ts";
import { notFound, unavailable } from "./problem.ts";
import { freshness, isoDate, isoSecond, type StoredRow } from "./serve.ts";

export const STATUS_PAGE = definePage({ table: "status", serve: "status" });

type Json = Record<string, unknown>;

function field(payload: unknown, ...path: string[]): unknown {
  let node: unknown = payload;
  for (const key of path) node = typeof node === "object" && node !== null ? (node as Json)[key] : undefined;
  return node ?? null;
}

function newest(values: (string | null)[]): string | null {
  return values.filter((value): value is string => value !== null).sort().at(-1) ?? null;
}

/** One market's entry of the markets list. */
export function marketEntry(row: StoredRow, now: Date): Json {
  return {
    market: row.market,
    name: field(row.payload, "name"),
    currency: field(row.payload, "currency"),
    as_of: isoDate(row.as_of),
    last_daily_run_at: field(row.payload, "last_daily_run", "computed_at"),
    last_news_run_at: field(row.payload, "last_news_run", "ran_at"),
    freshness: freshness(row.built_at, now),
  };
}

/** The markets list: every market whose status page exists, with an envelope of the newest times. */
export async function marketsResponse(deps: ReadDeps): Promise<Response> {
  const rows: StoredRow[] = [];
  for (const market of MARKETS) {
    const row = await readRow(STATUS_PAGE, market, MARKET_PAGE_KEY, deps);
    if (row instanceof Response) {
      if (row.status === 503) return unavailable(market);
      continue;
    }
    rows.push(row);
  }
  if (!rows.length) return notFound("No market has a status page yet");
  const now = deps.now();
  const payload = { markets: rows.map((row) => marketEntry(row, now)) };
  const body = {
    market: "_all",
    page_key: MARKET_PAGE_KEY,
    as_of: newest(rows.map((row) => isoDate(row.as_of))),
    cutoff: newest(rows.map((row) => isoSecond(row.cutoff))),
    built_at: newest(rows.map((row) => isoSecond(row.built_at))),
    schema_version: rows[0].schema_version,
    source_commit: rows.length === 1 || rows.every((row) => row.source_commit === rows[0].source_commit)
      ? rows[0].source_commit : "mixed",
    payload_sha256: createHash("sha256").update(JSON.stringify(payload)).digest("hex"),
    payload,
  };
  return Response.json(body, { headers: { ETag: `"${body.payload_sha256}"`, "Cache-Control": "private, no-cache" } });
}
