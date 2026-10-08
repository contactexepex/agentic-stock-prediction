// The market pages' read specs (B11: lib/data/news.ts, companies.ts): each reads its own rm
// table with one keyed read of page `_`, serves a 2.0 page payload (cutoff and built_at at the top, freshness in the
// status block), and answers 404 for an unknown market without a read.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readPage } from "../handler.ts";
import { COMPANIES_PAGE } from "../companies.ts";
import { NEWS_PAGE } from "../news.ts";
import { MemoryRowStore, NOW, row } from "./fakes.ts";

const PAGES = [
  ["news", NEWS_PAGE],
  ["companies", COMPANIES_PAGE],
] as const;
const request = () => new Request("https://app.test/api/v1/markets/india/x");

for (const [table, spec] of PAGES) {
  test(`${table}: serves rm.${table} page _ as a 2.0 page payload`, async () => {
    assert.deepEqual(spec, { table, serve: "page" });
    const store = new MemoryRowStore().put(table, row({ market: "india", payload: { market: "india", status: {} } }));
    const response = await readPage(request(), spec, "india", "_", { store, now: () => NOW });
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.payload.cutoff, "2026-10-07T11:58:00Z");
    assert.equal(body.payload.built_at, "2026-10-07T11:58:00Z");
    assert.equal(body.payload.status.freshness.state, "fresh");
    assert.deepEqual(store.reads, [`${table}|india|_`]);
  });

  test(`${table}: an unknown market is a 404 without a read`, async () => {
    const store = new MemoryRowStore();
    const response = await readPage(request(), spec, "eu", "_", { store, now: () => NOW });
    assert.equal(response.status, 404);
    assert.deepEqual(store.reads, []);
  });
}
