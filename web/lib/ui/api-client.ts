// The browser's read client over /api/v1 (B7): one GET per page read, revalidated with the row's ETag (the routes
// answer 304 when If-None-Match matches, web/lib/data/handler.ts), errors as RFC 9457 problems with the static
// fallback links the API gives. Pure apart from the injected fetch; the React hooks (use-api.ts) wrap it.
import type { Envelope, Problem } from "./types.ts";

export type ReadResult<P> = { ok: true; envelope: Envelope<P>; notModified: boolean } | { ok: false; problem: Problem };

export interface CacheEntry {
  etag: string;
  envelope: Envelope<unknown>;
}

/** A small per-tab cache of the last envelope per URL (only for ETag revalidation; nothing is persisted). */
export class EnvelopeCache {
  private entries = new Map<string, CacheEntry>();
  private readonly limit: number;
  constructor(limit = 64) {
    this.limit = limit;
  }
  get(url: string): CacheEntry | undefined {
    return this.entries.get(url);
  }
  set(url: string, entry: CacheEntry): void {
    this.entries.delete(url);
    this.entries.set(url, entry);
    while (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value as string);
  }
  clear(): void {
    this.entries.clear();
  }
}

export const sharedCache = new EnvelopeCache();

const PROBLEM_TITLES: Record<number, string> = {
  404: "Not found",
  501: "Not built yet",
  503: "Data service unavailable",
};

function isProblem(value: unknown): value is Problem {
  return typeof value === "object" && value !== null && typeof (value as Problem).title === "string";
}

async function problemOf(response: Response): Promise<Problem> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (isProblem(body)) return { ...body, status: typeof body.status === "number" ? body.status : response.status };
  return { title: PROBLEM_TITLES[response.status] ?? "Request failed", status: response.status };
}

/** GET one read-model page. A 304 returns the cached envelope; any failure returns a problem (status 0 = no answer). */
export async function readPage<P>(
  url: string,
  options: { fetchImpl?: typeof fetch; cache?: EnvelopeCache; signal?: AbortSignal } = {},
): Promise<ReadResult<P>> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const cache = options.cache ?? sharedCache;
  const cached = cache.get(url);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (cached) headers["If-None-Match"] = cached.etag;
  let response: Response;
  try {
    response = await fetchImpl(url, { headers, signal: options.signal, credentials: "same-origin" });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    return { ok: false, problem: { title: "No answer from the data service", status: 0, detail: "Check the connection and try again." } };
  }
  if (response.status === 304 && cached) return { ok: true, envelope: cached.envelope as Envelope<P>, notModified: true };
  if (!response.ok) return { ok: false, problem: await problemOf(response) };
  let envelope: Envelope<P>;
  try {
    envelope = (await response.json()) as Envelope<P>;
  } catch {
    return { ok: false, problem: { title: "Unreadable answer", status: response.status, detail: "The data service sent something that is not JSON." } };
  }
  if (typeof envelope !== "object" || envelope === null || !("payload" in envelope)) {
    return { ok: false, problem: { title: "Unreadable answer", status: response.status, detail: "The answer has no payload." } };
  }
  const etag = response.headers.get("ETag");
  if (etag) cache.set(url, { etag, envelope: envelope as Envelope<unknown> });
  return { ok: true, envelope, notModified: false };
}
