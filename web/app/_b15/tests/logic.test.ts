// Company pages' presentation logic (B15): sums, groupings, chart geometry and ranking, on the mockups' example data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { chartGeometry, niceTicks, barAt } from "../chart-geometry.ts";
import {
  horizonOfId, nextCompanyEvent, openSummary, referencePrediction, settledSummary, tradeMarks, whyScale, whySegments,
} from "../company-logic.ts";
import { agreementAt, bestOf, expectedGainMoney, pooledRows, rankedIds } from "../strategies-logic.ts";
import type { ScoreRow, SettledTrade } from "../types.ts";

const root = fileURLToPath(new URL("../../../../", import.meta.url));
// The mockups' data.json files carry Python's NaN for a few missing strings; read it as null.
const readMock = (path: string) => JSON.parse(readFileSync(root + path, "utf8").replace(/:\s*NaN\b/g, ": null"));
const mock03 = readMock("design/mockups/03-company/data.json");
const mock04 = readMock("design/mockups/04-stock-strategies/data.json");
const india = mock03.markets.india, reliance = india.pages.RELIANCE;

test("settled summary counts settled rows only and keeps skipped statuses apart", () => {
  const s = settledSummary(reliance.settled);
  const done = reliance.settled.filter((t: SettledTrade) => t.status === "settled");
  assert.equal(s.trades, done.length);
  assert.equal(s.skipped, reliance.settled.length - done.length);
  assert.equal(s.won, done.filter((t: SettledTrade) => (t.net_pnl ?? 0) > 0).length);
  assert.ok(Math.abs(s.net - done.reduce((a: number, t: SettledTrade) => a + (t.net_pnl ?? 0), 0)) < 1e-9);
});

test("a null measure never turns a sum into NaN", () => {
  const t = { ...reliance.settled[0], net_pnl: null, market_pct: null };
  assert.equal(settledSummary([t]).net, 0);
  assert.equal(openSummary([{ ...reliance.open_trades[0], unrealised_pnl: null }], []).unrealisedKnown, 0);
  assert.ok(Number.isFinite(whyScale([t])));
});

test("why segments: positive parts right of the centre, negative left, total width on the shared scale", () => {
  const t = { ...reliance.settled[0], market_pct: 1, sector_pct: -2, news_pct: 3, company_pct: 0 } as SettledTrade;
  const seg = whySegments(t, 6);
  assert.deepEqual(seg.map(s => s.key), ["market", "sector", "news"]);
  assert.ok(seg[0].x === 55 && seg[2].x > 55, "positive parts stack right");
  assert.ok(seg[1].x + seg[1].width <= 55, "negative part left of the centre");
  assert.ok(Math.abs(seg[2].width - 25) < 1e-9, "3 of 6 is half of the 50 units");
});

test("trade marks group settled entries and exits (actual exit first) and open entries", () => {
  const m = tradeMarks(reliance.settled, reliance.open_trades);
  const entries = [...m.entries.values()].reduce((a, l) => a + l.length, 0);
  assert.equal(entries, settledSummary(reliance.settled).trades);
  assert.equal([...m.open.values()].reduce((a, l) => a + l.length, 0), reliance.open_trades.length);
});

test("ids carry their horizon; the reference prediction is picked per horizon", () => {
  assert.equal(horizonOfId("h2h:x:rule.model_news.v1:2026-09-29-RELIANCE-3d"), 3);
  assert.equal(horizonOfId("rule.a:2026-09-29-RELIANCE-4d@20261006T121500Z"), 4);
  assert.equal(horizonOfId("no-horizon"), null);
  const r = referencePrediction(reliance.predictions, india.reference_strategy, 1);
  assert.ok(r && r.strategy_id === india.reference_strategy && r.horizon_days === 1);
});

test("the next company event is the company's own first event", () => {
  const e = nextCompanyEvent(reliance.events, "RELIANCE");
  if (e) assert.equal(e.ticker, "RELIANCE");
  assert.equal(nextCompanyEvent([], "RELIANCE"), null);
});

test("chart geometry: every bar inside the plot, the fan starts at the last close, phone keeps 30 sessions", () => {
  const ref = reliance.predictions.filter((r: { strategy_id: string }) => r.strategy_id === india.reference_strategy);
  const at = reliance.predictions.filter((r: { horizon_days: number }) => r.horizon_days === 1);
  const g = chartGeometry({ bars: reliance.bars, width: 1000, horizons: india.horizons, horizon: 1, reference: ref, atHorizon: at, tagWidth: 60 });
  assert.ok(g);
  for (const b of g.bars) { assert.ok(g.y(b.high) >= g.T - 1e-9 && g.y(b.low) <= g.PB + 1e-9); }
  assert.ok(g.fan80 && g.fan80.startsWith(`${g.x(g.bars.length - 1)},${g.y(g.bars[g.bars.length - 1].close)}`));
  assert.equal(g.targets.filter(t => t.on).length, 1);
  assert.ok(g.spread && g.spread.count === at.filter((r: { target_price: number | null }) => r.target_price != null).length);
  assert.ok(g.x(g.bars.length + 5) < g.W - g.R / 2, "the N+5 slot stays inside the chart, before the tag middle (as the mockup draws it)");
  const phone = chartGeometry({ bars: reliance.bars, width: 390, horizons: india.horizons, horizon: 1, reference: ref, atHorizon: at, tagWidth: 60 });
  assert.ok(phone && phone.phone && phone.bars.length === Math.min(30, reliance.bars.length));
  assert.equal(barAt(g, -1000), 0);
  assert.equal(barAt(g, 1e6), g.bars.length - 1);
});

test("chart geometry without predictions or bars", () => {
  assert.equal(chartGeometry({ bars: [], width: 800, horizons: [1], horizon: 1, reference: [], atHorizon: [], tagWidth: 50 }), null);
  const g = chartGeometry({ bars: reliance.bars, width: 800, horizons: [1, 2], horizon: 1, reference: [], atHorizon: [], tagWidth: 50 });
  assert.ok(g && g.fan80 === null && g.spread === null && g.targetTagY === null);
});

test("nice ticks are round and inside the span", () => {
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  for (const v of niceTicks(1131.4, 1240.7, 5)) assert.ok(v >= 1131.4 && v <= 1240.7 && v % 20 === 0);
  assert.deepEqual(niceTicks(5, 5, 5), [5]);
});

test("ranking: profit after costs, then trades, then id; unranked strategies after, by id", () => {
  const rows: ScoreRow[] = [
    { strategy_id: "b", horizon_days: "all", trades: 3, net_pnl: 10 }, { strategy_id: "a", horizon_days: "all", trades: 5, net_pnl: 10 },
    { strategy_id: "c", horizon_days: "all", trades: 9, net_pnl: -4 }, { strategy_id: "z", horizon_days: "all", trades: 0, net_pnl: 0 },
  ];
  assert.deepEqual(rankedIds(["y", "c", "b", "x", "a", "z"], rows), ["a", "b", "z", "c", "x", "y"]);
  assert.equal(bestOf(rows)?.strategy_id, "a");
  assert.equal(bestOf([{ strategy_id: "z", horizon_days: "all", trades: 0, net_pnl: 5 }]), null);
});

test("stock strategies example: pooled rows, agreement per horizon, expected gain in money", () => {
  const p = mock04.markets.india;
  assert.ok(pooledRows(p.on_company).every(r => r.horizon_days === "all"));
  const a = agreementAt(p.agreement, 1);
  assert.ok(a && a.buy <= a.of);
  assert.equal(agreementAt({}, 3), null);
  assert.equal(expectedGainMoney(0.5, 100000), 500);
  assert.equal(expectedGainMoney(null, 100000), null);
});
