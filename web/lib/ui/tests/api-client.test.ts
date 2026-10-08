import assert from "node:assert/strict";
import { test } from "node:test";
import { EnvelopeCache, readPage } from "../api-client.ts";

const envelope = { market: "india", page_key: "_", payload: { a: 1 } };
const ok = (etag?: string) => new Response(JSON.stringify(envelope), { status: 200, headers: etag ? { ETag: etag } : {} });

test("a read returns the envelope and revalidates with its ETag", async () => {
  const cache = new EnvelopeCache();
  const seen: (string | null)[] = [];
  const fetchImpl = (async (_url: string, init: RequestInit) => {
    const inm = (init.headers as Record<string, string>)["If-None-Match"] ?? null;
    seen.push(inm);
    return inm ? new Response(null, { status: 304 }) : ok('"abc"');
  }) as unknown as typeof fetch;
  const first = await readPage("/api/v1/markets/india/home", { fetchImpl, cache });
  assert.ok(first.ok && !first.notModified && (first.envelope.payload as { a: number }).a === 1);
  const second = await readPage("/api/v1/markets/india/home", { fetchImpl, cache });
  assert.ok(second.ok && second.notModified);
  assert.deepEqual(seen, [null, '"abc"']);
});

test("problems keep their fallback links; other failures get plain titles", async () => {
  const problem = { title: "Data service unavailable", status: 503, fallback_links: ["https://x/india/dashboard.html"] };
  const r503 = await readPage("/u", { cache: new EnvelopeCache(), fetchImpl: (async () => new Response(JSON.stringify(problem), { status: 503 })) as unknown as typeof fetch });
  assert.ok(!r503.ok && r503.problem.status === 503 && r503.problem.fallback_links?.length === 1);
  const r501 = await readPage("/u", { cache: new EnvelopeCache(), fetchImpl: (async () => new Response("nope", { status: 501 })) as unknown as typeof fetch });
  assert.ok(!r501.ok && r501.problem.title === "Not built yet");
  const down = await readPage("/u", { cache: new EnvelopeCache(), fetchImpl: (async () => { throw new TypeError("network"); }) as unknown as typeof fetch });
  assert.ok(!down.ok && down.problem.status === 0);
  const junk = await readPage("/u", { cache: new EnvelopeCache(), fetchImpl: (async () => new Response("<html>", { status: 200 })) as unknown as typeof fetch });
  assert.ok(!junk.ok && junk.problem.title === "Unreadable answer");
});

test("an aborted read rejects instead of returning a problem", async () => {
  const fetchImpl = (async () => { throw Object.assign(new Error("aborted"), { name: "AbortError" }); }) as unknown as typeof fetch;
  await assert.rejects(readPage("/u", { fetchImpl, cache: new EnvelopeCache() }));
});

test("the cache keeps at most its limit, oldest out first", () => {
  const cache = new EnvelopeCache(2);
  for (const k of ["a", "b", "c"]) cache.set(k, { etag: k, envelope: envelope as never });
  assert.equal(cache.get("a"), undefined);
  assert.equal(cache.get("c")?.etag, "c");
});
