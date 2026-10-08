// Stored-data fixtures of B16's pages (05-08): each market's payload as B13's builders made it from the repository's
// stored data on 2026-10-08 (cut-off 2026-10-08T14:00Z), served the way the route serves a 2.0 page (`cutoff`,
// `built_at` and `status.freshness` added; web/lib/data/serve.ts). Most lists are still empty in the stored data
// (no settled trade, pick or review yet), so these cases show the pages' empty states as they look today.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { envelope } from "../fixtures.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const CUTOFF = "2026-10-08T14:00:00Z";

/** The served payload of a stored file (`<market>-<table>.json`). */
export function storedPayload(market, table) {
  const payload = JSON.parse(readFileSync(join(here, `${market}-${table}.json`), "utf8"));
  const served = { ...payload, cutoff: CUTOFF, built_at: CUTOFF };
  if (served.status) served.status = { ...served.status, freshness: { state: "fresh", built_at: CUTOFF, age_minutes: 0 } };
  return served;
}

/** A case's `api` answering the endpoints of B16's pages from the stored files. */
export function storedApi(rest, market) {
  const table = { strategies: "strategies", compare: "compare", review: "review", portfolios: "portfolio", "track-record": "track_record" }[rest];
  if (!table) return undefined;
  return { status: 200, body: envelope(market, "_", storedPayload(market, table)) };
}
