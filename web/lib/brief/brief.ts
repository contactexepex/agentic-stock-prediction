// The public daily brief (C2 batch 2; owner decision 2026-10-10; docs/ws/c2.md): GET /brief/{market}/{session}-{token}
// serves one report day's reader page, read-only, through the gateway (no login). The slug is checked (market, ISO
// date, 32 lowercase hex) before any read; the one keyed read of rm.brief (page_key = the session) returns the page
// and the SHA-256 of its token (scripts/marketbrief/presentation/reader/links.py: HMAC of BRIEF_LINK_SECRET, never
// stored); the token's SHA-256 is compared in constant time. Anything else is a plain 404. The page is the
// self-contained HTML of html_report.py (inline style and script, no requests), so the CSP allows nothing else.
import { createHash, timingSafeEqual } from "node:crypto";
import type { RowStore } from "../data/store.ts";
import { WarehouseUnavailable } from "../data/store.ts";

export const BRIEF_TABLE = "brief";
const MARKETS = new Set(["india", "us"]);
const SLUG = /^(\d{4}-\d{2}-\d{2})-([0-9a-f]{32})$/;
const SHA256_HEX = /^[0-9a-f]{64}$/;

export const BRIEF_HEADERS: Record<string, string> = {
  "Content-Type": "text/html; charset=utf-8",
  "X-Robots-Tag": "noindex, nofollow",
  "Cache-Control": "private, no-store",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
    "img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
};
const PLAIN = { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" };

export interface BriefRequest { market: string; session: string; token: string }

/** The checked request, or null when the market or slug is malformed (no read happens then). */
export function parseBrief(market: string, slug: string): BriefRequest | null {
  if (!MARKETS.has(market)) return null;
  const match = SLUG.exec(slug);
  if (!match) return null;
  const [, session] = match;
  if (Number.isNaN(Date.parse(`${session}T00:00:00Z`))) return null;
  return { market, session, token: match[2] };
}

/** True when the token's SHA-256 equals the stored one (constant time over the 32-byte digests). */
export function tokenMatches(token: string, storedSha256: unknown): boolean {
  if (typeof storedSha256 !== "string" || !SHA256_HEX.test(storedSha256)) return false;
  const given = createHash("sha256").update(token).digest();
  return timingSafeEqual(given, Buffer.from(storedSha256, "hex"));
}

export const notFound = () => new Response("Not Found", { status: 404, headers: PLAIN });

/** The brief's response for a request path's market and slug. */
export async function briefResponse(store: RowStore, market: string, slug: string): Promise<Response> {
  const request = parseBrief(market, slug);
  if (!request) return notFound();
  let stored;
  try {
    stored = await store.read(BRIEF_TABLE, request.market, request.session);
  } catch (error) {
    if (error instanceof WarehouseUnavailable) {
      return new Response("The brief is unavailable right now. The report file in Slack has the same page.",
        { status: 503, headers: PLAIN });
    }
    throw error;
  }
  const payload = (stored?.payload ?? null) as { session?: unknown; token_sha256?: unknown; html?: unknown } | null;
  if (!payload || payload.session !== request.session || typeof payload.html !== "string" ||
      !tokenMatches(request.token, payload.token_sha256)) {
    return notFound();
  }
  return new Response(payload.html, { status: 200, headers: BRIEF_HEADERS });
}
