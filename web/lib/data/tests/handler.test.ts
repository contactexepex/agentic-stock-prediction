// The /api/v1 read-route helper (lib/data/handler.ts) with an in-memory store: envelope plus served payload, ETag
// and 304, 404 for an unknown market, page or ticker, 503 with fallback links when the warehouse is down or the row
// is of another major contract version, and one keyed read per request.
import { test } from "node:test";
import assert from "node:assert/strict";
import { definePage, readPage, readTickerPage } from "../handler.ts";
import { DownRowStore, MemoryRowStore, NOW, row } from "./fakes.ts";

const PAGE = definePage({ table: "example", serve: "page" });
const request = (headers: Record<string, string> = {}) => new Request("https://app.test/api/v1/x", { headers });
const deps = (store: MemoryRowStore | DownRowStore) => ({ store, now: () => NOW });

test("a stored page is served with its envelope, ETag, Last-Modified and no-cache", async () => {
  const store = new MemoryRowStore().put("example", row());
  const response = await readPage(request(), PAGE, "us", "_", deps(store));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("etag"), `"${"a".repeat(64)}"`);
  assert.equal(response.headers.get("cache-control"), "private, no-cache");
  assert.equal(response.headers.get("last-modified"), "Wed, 07 Oct 2026 11:58:00 GMT");
  const body = await response.json();
  assert.equal(body.payload_sha256, "a".repeat(64));
  assert.equal(body.payload.cutoff, "2026-10-07T11:58:00Z");
  assert.deepEqual(body.payload.status.freshness, { state: "fresh", built_at: "2026-10-07T11:58:00Z", age_minutes: 2 });
  assert.deepEqual(store.reads, ["example|us|_"]);
});

test("If-None-Match with the row's ETag answers 304 without a body", async () => {
  const store = new MemoryRowStore().put("example", row());
  const response = await readPage(request({ "if-none-match": `W/"x", "${"a".repeat(64)}"` }), PAGE, "us", "_",
    deps(store));
  assert.equal(response.status, 304);
  assert.equal(await response.text(), "");
});

test("an unknown market or page key is a 404 without a read", async () => {
  const store = new MemoryRowStore().put("example", row());
  for (const [market, key] of [["eu", "_"], ["us", "bad key; drop"], ["us", ""]]) {
    const response = await readPage(request(), PAGE, market, key, deps(store));
    assert.equal(response.status, 404);
    assert.equal(response.headers.get("content-type"), "application/problem+json");
  }
  assert.deepEqual(store.reads, []);
});

test("a missing page is a 404; a malformed ticker is refused before the read", async () => {
  const store = new MemoryRowStore();
  assert.equal((await readPage(request(), PAGE, "us", "_", deps(store))).status, 404);
  assert.equal((await readTickerPage(request(), PAGE, "us", "nvda", deps(store))).status, 404);
  assert.deepEqual(store.reads, ["example|us|_"]);
});

test("a ticker page reads its ticker key", async () => {
  const store = new MemoryRowStore().put("example", row({ page_key: "M&M", market: "india" }));
  const response = await readTickerPage(request(), PAGE, "india", "M&M", deps(store));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).page_key, "M&M");
});

test("the warehouse down is a 503 with the static reports as fallback links and no driver text", async () => {
  const response = await readPage(request(), PAGE, "india", "_", deps(new DownRowStore()));
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("cache-control"), "no-store");
  const body = await response.json();
  assert.deepEqual(body.fallback_links, [
    "https://agentic-stock-prediction-reports.vercel.app/india/dashboard.html",
    "https://agentic-stock-prediction-reports.vercel.app/india/index.html",
  ]);
  assert.equal(body.status, 503);
});

test("a row of another major contract version is refused with 503", async () => {
  const store = new MemoryRowStore().put("example", row({ schema_version: "1.1.0" }));
  assert.equal((await readPage(request(), PAGE, "us", "_", deps(store))).status, 503);
});

test("definePage refuses a table name that is not a plain identifier", () => {
  assert.throws(() => definePage({ table: "rm.x; drop", serve: "page" }));
});
