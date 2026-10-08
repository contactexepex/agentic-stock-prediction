// The company pages' reads (lib/data/company.ts): each page reads one row of its own table by the ticker (or `_`).
import { test } from "node:test";
import assert from "node:assert/strict";
import { COMPANY_BARS, COMPANY_PAGE, STOCK_STRATEGIES_PAGE, TRADES_PAGE, tradesResponse } from "../company.ts";
import { readTickerPage } from "../handler.ts";
import { DownRowStore, MemoryRowStore, NOW, row } from "./fakes.ts";

const page = (pageKey: string, payload: Record<string, unknown>) => row({ page_key: pageKey, payload });

test("the company page is rm.stock of the ticker, served as a 2.0 page (cutoff, built_at, status.freshness)", async () => {
  const store = new MemoryRowStore().put("stock", page("NVDA", { market: "us", ticker: "NVDA", status: { market: "us" } }));
  const response = await readTickerPage(new Request("http://x/api"), COMPANY_PAGE, "us", "NVDA", { store, now: () => NOW });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.page_key, "NVDA");
  assert.equal(body.payload.cutoff, "2026-10-07T11:58:00Z");
  assert.equal(body.payload.status.freshness.state, "fresh");
  assert.deepEqual(store.reads, ["stock|us|NVDA"]);
});

test("bars and strategies read their own tables; bars are verbatim", async () => {
  const store = new MemoryRowStore()
    .put("bars", page("AAPL", { market: "us", ticker: "AAPL", as_of: "2026-10-06", bars: [] }))
    .put("stock_strategies", page("AAPL", { market: "us", ticker: "AAPL", status: { market: "us" } }));
  const deps = { store, now: () => NOW };
  const bars = await (await readTickerPage(new Request("http://x"), COMPANY_BARS, "us", "AAPL", deps)).json();
  assert.deepEqual(bars.payload, { market: "us", ticker: "AAPL", as_of: "2026-10-06", bars: [] });
  const strategies = await (await readTickerPage(new Request("http://x"), STOCK_STRATEGIES_PAGE, "us", "AAPL", deps)).json();
  assert.equal(strategies.payload.status.freshness.state, "fresh");
  assert.deepEqual(store.reads, ["bars|us|AAPL", "stock_strategies|us|AAPL"]);
});

test("trades: without a ticker the market's page `_`, with one the company's; a bad ticker or market is a 404", async () => {
  const store = new MemoryRowStore()
    .put("trades", page("_", { market: "us", open_trades: [] }))
    .put("trades", page("JPM", { market: "us", ticker: "JPM", open_trades: [] }));
  const deps = { store, now: () => NOW };
  assert.equal((await (await tradesResponse(new Request("http://x/trades"), "us", deps)).json()).page_key, "_");
  assert.equal((await (await tradesResponse(new Request("http://x/trades?ticker=JPM"), "us", deps)).json()).page_key, "JPM");
  assert.equal((await tradesResponse(new Request("http://x/trades?ticker=bad%20one"), "us", deps)).status, 404);
  assert.equal((await tradesResponse(new Request("http://x/trades"), "eu", deps)).status, 404);
  assert.equal((await tradesResponse(new Request("http://x/trades?ticker=AAPL"), "us", deps)).status, 404);
  assert.deepEqual(store.reads, ["trades|us|_", "trades|us|JPM", "trades|us|AAPL"]);
  assert.equal(TRADES_PAGE.table, "trades");
});

test("the warehouse down is a 503 with the static reports as fallback", async () => {
  const response = await readTickerPage(new Request("http://x"), COMPANY_PAGE, "india", "RELIANCE",
    { store: new DownRowStore(), now: () => NOW });
  assert.equal(response.status, 503);
  assert.ok((await response.json()).fallback_links.length > 0);
});
