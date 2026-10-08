// The News page's computations against the approved mockup's example payload (design/mockups/09-news/data.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  agoWords, companiesWithNews, companyRail, dayGroups, filterNews, kindWord, missingSummaries, movers, NEWS_MOVERS_MAX,
  offsetMinutes, paginate, tone, type NewsItem,
} from "../news.ts";

// The mockup file carries a bare NaN (Python json.dump) where the API serves null.
const data = JSON.parse(readFileSync(new URL("../../../../design/mockups/09-news/data.json", import.meta.url), "utf8").replace(/\bNaN\b/g, "null"));

const item = (over: Partial<NewsItem> & { id: string }): NewsItem => ({
  tickers: [], primary_tickers: [], title: over.id, source: "s", source_domain: "s.example", url: "https://s.example/",
  published_at: "2026-10-07T10:00:00Z", first_seen_at: "2026-10-07T10:00:00Z", status: null, independent_origins: 1,
  scope: "company", enrichment: { event_type: "other", materiality: "low", sentiment: 0 }, ...over,
});

test("movers: flagged first, then market-wide, results, materiality, newest; duplicates once; capped", () => {
  const items = [
    item({ id: "low", enrichment: { event_type: "other", materiality: "low", sentiment: 0 } }),
    item({ id: "high-old", first_seen_at: "2026-10-06T00:00:00Z", enrichment: { event_type: "other", materiality: "high", sentiment: 0 } }),
    item({ id: "high-new", enrichment: { event_type: "other", materiality: "high", sentiment: 0 } }),
    item({ id: "results", enrichment: { event_type: "earnings", materiality: "medium", sentiment: 0 } }),
    item({ id: "market", scope: "market", enrichment: { event_type: "macro", materiality: "low", sentiment: 0 } }),
    item({ id: "flag", market_moving: true, enrichment: { event_type: "other", materiality: "medium", sentiment: 0 } }),
    item({ id: "dup", title: "high-new", enrichment: { event_type: "other", materiality: "high", sentiment: 0 } }),
  ];
  assert.deepEqual(movers(items).map((n) => n.id), ["flag", "market", "results", "high-new", "high-old"]);
  assert.deepEqual(movers(items, 2).map((n) => n.id), ["flag", "market"]);
});

test("filters, pages and the 24 h rule use the cut-off, never the viewer's clock", () => {
  const cutoff = "2026-10-08T00:00:00Z";
  const items = [
    item({ id: "a", published_at: "2026-10-07T01:00:00Z", status: "corroborated", tickers: ["TCS"] }),
    item({ id: "b", published_at: "2026-10-06T23:59:00Z", scope: "market", market_moving: true }),
    item({ id: "c", published_at: null }),
  ];
  assert.deepEqual(filterNews(items, "24h", cutoff, null).map((n) => n.id), ["a"]);
  assert.deepEqual(filterNews(items, "market", cutoff, null).map((n) => n.id), ["b"]);
  assert.deepEqual(filterNews(items, "moving", cutoff, null).map((n) => n.id), ["b"]);
  assert.deepEqual(filterNews(items, "carry", cutoff, null).map((n) => n.id), ["a"]);
  assert.deepEqual(filterNews(items, "company", cutoff, "TCS").map((n) => n.id), ["a"]);
  assert.equal(agoWords(cutoff, "2026-10-07T23:30:00Z"), "under an hour before the cut-off");
  assert.equal(agoWords(cutoff, "2026-10-07T01:00:00Z"), "23 h before the cut-off");
  assert.equal(agoWords(cutoff, "2026-10-06T00:00:00Z"), "2 days before the cut-off");
  assert.equal(agoWords(cutoff, "2026-10-06T23:00:00Z"), "1 day before the cut-off");
  const pg = paginate(Array.from({ length: 23 }, (_, i) => i), 9);
  assert.deepEqual([pg.page, pg.pages, pg.items], [3, 3, [20, 21, 22]]);
  assert.deepEqual(paginate([], 1), { page: 1, pages: 1, items: [] });
});

test("day groups follow the market-local date of first_seen_at and count the whole filtered list", () => {
  const off = offsetMinutes("2026-10-07T17:28:00+05:30");
  assert.equal(off, 330);
  const all = [
    item({ id: "1", first_seen_at: "2026-10-07T19:00:00Z" }), // 8 Oct IST
    item({ id: "2", first_seen_at: "2026-10-07T17:00:00Z" }), // 7 Oct IST
    item({ id: "3", first_seen_at: "2026-10-07T10:00:00Z" }),
  ];
  const g = dayGroups(all.slice(0, 2), all, "2026-10-07T20:00:00Z", off);
  assert.deepEqual(g.map((x) => [x.date, x.today, x.count, x.items.length]), [["2026-10-08", true, 1, 1], ["2026-10-07", false, 2, 1]]);
});

test("rail, kind words and tone", () => {
  const items = [
    item({ id: "1", tickers: ["B"], enrichment: { event_type: "x", materiality: "low", sentiment: 0.06 } }),
    item({ id: "2", tickers: ["B"], enrichment: { event_type: "x", materiality: "low", sentiment: -0.05 } }),
    item({ id: "3", tickers: ["A"], enrichment: { event_type: "x", materiality: "low", sentiment: -0.2 } }),
  ];
  const cos = [{ ticker: "A", name: "A", state: "active", open_trades: 0 }, { ticker: "B", name: "B", state: "active", open_trades: 1 }, { ticker: "C", name: "C", state: "active", open_trades: 0 }];
  assert.deepEqual(companyRail(cos, items).map((r) => [r.company.ticker, r.count, r.up, r.flat, r.down, r.latest.id]), [["B", 2, 1, 1, 0, "1"], ["A", 1, 0, 0, 1, "3"]]);
  assert.deepEqual(companiesWithNews(cos, items).map((c) => c.ticker), ["A", "B"]);
  assert.equal(tone(null), "flat");
  assert.equal(kindWord(item({ id: "m", scope: "market", category: "rates" })), "rates");
  assert.equal(kindWord(item({ id: "g", scope: "market", category: "general", enrichment: { event_type: "earnings", materiality: null, sentiment: null } })), "results");
  assert.equal(missingSummaries([item({ id: "x" }), item({ id: "y", summary: "s" })]), null);
  assert.equal(missingSummaries([item({ id: "x" }), item({ id: "y" }), item({ id: "z", summary: "s" })]), 2);
});

test("the mockup's payload: movers stay within the cap and every mover qualifies", () => {
  for (const market of ["india", "us"]) {
    const p = data.markets[market];
    const list = movers(p.news);
    assert.ok(list.length > 0 && list.length <= NEWS_MOVERS_MAX);
    assert.equal(new Set(list.map((n) => n.title)).size, list.length);
    for (const n of list) assert.ok(n.market_moving || n.scope === "market" || n.enrichment.event_type === "earnings" || n.enrichment.materiality === "high");
  }
});
