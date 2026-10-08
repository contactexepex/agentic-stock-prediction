// The platform reads (lib/data/platform.ts): the markets list composed from both status pages.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { marketsResponse } from "../platform.ts";
import { DownRowStore, MemoryRowStore, NOW, row } from "./fakes.ts";

const statusRow = (market: string, builtAt: string, asOf: string) => row({
  market, as_of: asOf, built_at: builtAt, cutoff: builtAt,
  payload: { market, name: market === "us" ? "US (NYSE/Nasdaq)" : "India (NSE)", currency: market === "us" ? "USD" : "INR",
    last_daily_run: { as_of_date: asOf, computed_at: "2026-10-07T04:41:01Z" }, last_news_run: null },
});

test("the markets list has one entry per stored status page and the newest envelope times", async () => {
  const store = new MemoryRowStore()
    .put("status", statusRow("india", "2026-10-07T10:00:00Z", "2026-10-06"))
    .put("status", statusRow("us", "2026-10-07T11:00:00Z", "2026-10-06"));
  const response = await marketsResponse({ store, now: () => NOW });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.market, "_all");
  assert.equal(body.built_at, "2026-10-07T11:00:00Z");
  assert.equal(body.payload_sha256, createHash("sha256").update(JSON.stringify(body.payload)).digest("hex"));
  assert.deepEqual(body.payload.markets.map((m: { market: string }) => m.market), ["india", "us"]);
  assert.deepEqual(body.payload.markets[1], {
    market: "us", name: "US (NYSE/Nasdaq)", currency: "USD", as_of: "2026-10-06",
    last_daily_run_at: "2026-10-07T04:41:01Z", last_news_run_at: null,
    freshness: { state: "fresh", built_at: "2026-10-07T11:00:00Z", age_minutes: 60 },
  });
  assert.deepEqual(store.reads, ["status|india|_", "status|us|_"]);
});

test("a market without a status page is left out; none at all is a 404; the warehouse down is a 503", async () => {
  const one = new MemoryRowStore().put("status", statusRow("us", "2026-10-07T11:00:00Z", "2026-10-06"));
  const body = await (await marketsResponse({ store: one, now: () => NOW })).json();
  assert.deepEqual(body.payload.markets.map((m: { market: string }) => m.market), ["us"]);
  assert.equal((await marketsResponse({ store: new MemoryRowStore(), now: () => NOW })).status, 404);
  assert.equal((await marketsResponse({ store: new DownRowStore(), now: () => NOW })).status, 503);
});
