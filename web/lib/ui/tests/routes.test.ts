import assert from "node:assert/strict";
import { test } from "node:test";
import { apiPath, companyPath, isMarket, lifecyclePath, marketOfPath, pageOfPath, pagePath, PAGES, switchMarketPath } from "../routes.ts";

test("every page of SPEC section 6 has one route and a mockup", () => {
  const spec = PAGES.filter((p) => p.mockup);
  assert.equal(spec.length, 12);
  assert.equal(new Set(PAGES.map((p) => p.segment)).size, PAGES.length);
  assert.deepEqual(spec.map((p) => p.mockup.slice(0, 2)), ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]);
});

test("page paths", () => {
  assert.equal(pagePath("india", "home"), "/india");
  assert.equal(pagePath("us", "track"), "/us/track-record");
  assert.equal(companyPath("india", "M&M"), "/india/stocks/M%26M");
  assert.equal(lifecyclePath("us", "AAPL", "2026-10-07"), "/us/stocks/AAPL/lifecycle/2026-10-07");
  assert.throws(() => pagePath("india", "nope"));
});

test("the page of a path", () => {
  assert.equal(pageOfPath("/india").key, "home");
  assert.equal(pageOfPath("/india/watchlist").key, "watchlist");
  assert.equal(pageOfPath("/us/stocks/AAPL").key, "company");
  assert.equal(pageOfPath("/us/stocks/AAPL/strategies").key, "strategies");
  assert.equal(pageOfPath("/us/stocks/AAPL/lifecycle/2026-10-07").key, "company");
  assert.equal(pageOfPath("/us/help").key, "help");
  assert.equal(pageOfPath("/us/gallery").key, "gallery");
  assert.equal(marketOfPath("/us/news"), "us");
  assert.equal(marketOfPath("/mars"), null);
  assert.ok(isMarket("india") && !isMarket("IN"));
});

test("the market switch keeps the page, except per-stock pages", () => {
  assert.equal(switchMarketPath("/india/news", "us"), "/us/news");
  assert.equal(switchMarketPath("/india", "us"), "/us");
  assert.equal(switchMarketPath("/india/stocks/RELIANCE/strategies", "us"), "/us/watchlist");
  assert.equal(switchMarketPath("/elsewhere", "us"), "/us");
});

test("api paths check the ticker", () => {
  assert.equal(apiPath("india", "home"), "/api/v1/markets/india/home");
  assert.equal(apiPath("us", "stocks/{ticker}/strategies", { ticker: "BRK.B" }), "/api/v1/markets/us/stocks/BRK.B/strategies");
  assert.throws(() => apiPath("us", "stocks/{ticker}", { ticker: "../x" }));
  assert.throws(() => apiPath("us", "stocks/{ticker}", {}));
});
