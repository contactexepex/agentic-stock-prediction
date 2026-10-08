// POST /api/v1/internal/revalidate (ARCHITECTURE.md section 7): after a build commits, the sync sends the keys
// whose payload changed (or that were deleted); each key's cache tag is invalidated. The secret is REVALIDATE_SECRET,
// compared in constant time; the body is checked against api/openapi.yaml RevalidateRequest. An unknown table only
// invalidates a tag nobody uses.
import { timingSafeEqual } from "node:crypto";
import { cacheTag, MARKETS, PAGE_KEY_PATTERN, TABLE_PATTERN } from "./constants.ts";
import { invalid, unauthorized } from "./problem.ts";

export const SECRET_HEADER = "x-revalidate-secret";
export const MAX_KEYS = 200;
const MAX_BODY_BYTES = 64_000;
const MARKET_VALUES = [...MARKETS, "_all"];

export interface RevalidateKey {
  table: string;
  market: string;
  page_key: string;
}

export function secretMatches(given: string | null, expected: string | null): boolean {
  if (!given || !expected) return false;
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

/** The body's keys, or a reason it is refused. */
export function parseKeys(body: unknown): { keys: RevalidateKey[] } | { error: string } {
  if (typeof body !== "object" || body === null) return { error: "body must be an object" };
  const { build_id: buildId, keys } = body as { build_id?: unknown; keys?: unknown };
  if (typeof buildId !== "string" || !buildId) return { error: "build_id is required" };
  if (!Array.isArray(keys) || keys.length > MAX_KEYS) return { error: `keys must be a list of at most ${MAX_KEYS}` };
  const out: RevalidateKey[] = [];
  for (const key of keys) {
    const { table, market, page_key: pageKey } = (key ?? {}) as Record<string, unknown>;
    if (typeof table !== "string" || !TABLE_PATTERN.test(table)) return { error: "bad table" };
    if (typeof market !== "string" || !MARKET_VALUES.includes(market)) return { error: "bad market" };
    if (typeof pageKey !== "string" || !PAGE_KEY_PATTERN.test(pageKey)) return { error: "bad page_key" };
    out.push({ table, market, page_key: pageKey });
  }
  return { keys: out };
}

export async function handleRevalidate(
  request: Request, secret: string | null, revalidate: (tag: string) => void,
): Promise<Response> {
  if (!secretMatches(request.headers.get(SECRET_HEADER), secret)) return unauthorized();
  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) return invalid("body too large");
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return invalid("body is not JSON");
  }
  const parsed = parseKeys(body);
  if ("error" in parsed) return invalid(parsed.error);
  const tags = new Set(parsed.keys.map((key) => cacheTag(key.table, key.market, key.page_key)));
  for (const tag of tags) revalidate(tag);
  return Response.json({ revalidated: tags.size }, { headers: { "Cache-Control": "no-store" } });
}
