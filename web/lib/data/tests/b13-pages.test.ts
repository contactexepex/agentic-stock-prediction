// B13's page specs (Strategy lab, Rule vs AI, research reviews, Paper portfolios, Track record): each reads its own rm table at the market's page `_` and is served
// in page mode (cutoff, built_at and status.freshness added); a missing page is a 404.
import { test } from "node:test";
import assert from "node:assert/strict";
import { MARKET_PAGE_KEY } from "../constants.ts";
import { readPage } from "../handler.ts";
import { PAPER_PORTFOLIOS_PAGE, PORTFOLIO_SESSION_PAGE, portfolioFinishedResponse, portfolioHoldResponse, portfolioSessionResponse } from "../paper-portfolios.ts";
import { REVIEW_PAGE } from "../review.ts";
import { RULE_VS_AI_PAGE } from "../rule-vs-ai.ts";
import { STRATEGY_LAB_PAGE } from "../strategy-lab.ts";
import { TRACK_RECORD_PAGE } from "../track-record.ts";
import { MemoryRowStore, NOW, row } from "./fakes.ts";

const request = () => new Request("https://app.test/api/v1/markets/us/x");

for (const [spec, table] of [
  [STRATEGY_LAB_PAGE, "strategies"], [RULE_VS_AI_PAGE, "compare"], [REVIEW_PAGE, "review"], [PAPER_PORTFOLIOS_PAGE, "portfolio"], [TRACK_RECORD_PAGE, "track_record"],
] as const) {
  test(`${table}: one keyed read of rm.${table}/_, served as a page`, async () => {
    const store = new MemoryRowStore().put(table, row());
    const response = await readPage(request(), spec, "us", MARKET_PAGE_KEY, { store, now: () => NOW });
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.payload.built_at, "2026-10-07T11:58:00Z");
    assert.equal(body.payload.status.freshness.state, "fresh");
    assert.deepEqual(store.reads, [`${table}|us|_`]);
  });

  test(`${table}: a market without the page is a 404`, async () => {
    const response = await readPage(request(), spec, "india", MARKET_PAGE_KEY,
      { store: new MemoryRowStore(), now: () => NOW });
    assert.equal(response.status, 404);
  });
}

test("portfolio sessions: the page `trades:<date>` of rm.portfolio, verbatim; a bad or unstored date is a 404", async () => {
  const store = new MemoryRowStore().put("portfolio", row({ page_key: "trades:2026-10-12", payload: { market: "us", session_date: "2026-10-12" } }));
  const deps = { store, now: () => NOW };
  const ok = await portfolioSessionResponse(new Request("http://x"), "us", "2026-10-12", deps);
  assert.equal(ok.status, 200);
  assert.equal((await ok.json()).page_key, "trades:2026-10-12");
  assert.equal((await portfolioSessionResponse(new Request("http://x"), "us", "2026-10-09", deps)).status, 404);
  assert.equal((await portfolioSessionResponse(new Request("http://x"), "us", "12 Oct", deps)).status, 404);
  assert.deepEqual(store.reads, ["portfolio|us|trades:2026-10-12", "portfolio|us|trades:2026-10-09"]);
  assert.equal(PORTFOLIO_SESSION_PAGE.table, "portfolio");
});

test("portfolio holds (UX3): the page `open:<k>` of rm.portfolio, verbatim; a hold outside 1-5 or without a page is a 404", async () => {
  const store = new MemoryRowStore().put("portfolio", row({ page_key: "open:3", payload: { market: "us", horizon_days: 3 } }));
  const deps = { store, now: () => NOW };
  const ok = await portfolioHoldResponse(new Request("http://x"), "us", "3", deps);
  assert.equal(ok.status, 200);
  assert.equal((await ok.json()).page_key, "open:3");
  assert.equal((await portfolioHoldResponse(new Request("http://x"), "us", "2", deps)).status, 404);
  for (const bad of ["0", "6", "12", "x", "3d"]) assert.equal((await portfolioHoldResponse(new Request("http://x"), "us", bad, deps)).status, 404);
  assert.deepEqual(store.reads, ["portfolio|us|open:3", "portfolio|us|open:2"]);
});

test("portfolio finished sessions (UX3): the page `finished:<date>` of rm.portfolio, verbatim; a bad or unstored date is a 404", async () => {
  const store = new MemoryRowStore().put("portfolio", row({ page_key: "finished:2026-10-13", payload: { market: "us", session_date: "2026-10-13" } }));
  const deps = { store, now: () => NOW };
  const ok = await portfolioFinishedResponse(new Request("http://x"), "us", "2026-10-13", deps);
  assert.equal(ok.status, 200);
  assert.equal((await ok.json()).page_key, "finished:2026-10-13");
  assert.equal((await portfolioFinishedResponse(new Request("http://x"), "us", "2026-10-12", deps)).status, 404);
  assert.equal((await portfolioFinishedResponse(new Request("http://x"), "us", "13 Oct", deps)).status, 404);
  assert.deepEqual(store.reads, ["portfolio|us|finished:2026-10-13", "portfolio|us|finished:2026-10-12"]);
});
