// B16's page logic (05 Strategy lab, 08 Track record; shared scoreboard helpers), offline, on the mockups' data.json
// payloads (design/mockups/<page>/data.json, the approved contract) and on small hand-made rows.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  figure, luckOf, luckScale, luckVerdict, niceTicks, rowsOf, type LuckTest, type ScoreboardRow,
} from "../scoreboard.ts";
import {
  colouredSeries, compactProfit, cumulativeSeries, defaultSelection, fmtParam, heatShares, heatWeeks, kpiPicks,
  ranking, type StrategyLabPayload,
} from "../strategy-lab.ts";
import {
  basisLabel, calibrationLayout, groupByKey, horizonRows, intervalClass, keyWords, selectedBasis, symmetricSpan,
  verdictKind, weeklyOf,
} from "../track-record.ts";
import type { TrackRecordPayload } from "../track-record-types.ts";

const REPO = fileURLToPath(new URL("../../../../", import.meta.url));
const mockup = <T>(page: string, market = "india"): T =>
  JSON.parse(readFileSync(`${REPO}design/mockups/${page}/data.json`, "utf8")).markets[market] as T;

const luck = (lo: number, hi: number, clo: number | null, chi: number | null): LuckTest =>
  ({ n: 5, m: 3, low_pct: lo, high_pct: hi, corrected_low_pct: clo, corrected_high_pct: chi, corrected: null });

test("luck verdict: edge only above zero after correction, loss wholly below, else luck?", () => {
  assert.equal(luckVerdict(luck(0.1, 2, 0.05, 2.5)), "edge");
  assert.equal(luckVerdict(luck(-2, -0.1, -2.5, -0.05)), "loss");
  assert.equal(luckVerdict(luck(0.1, 2, -0.2, 2.5)), "luck?");
  assert.equal(luckVerdict(luck(0.1, 2, null, null)), "luck?");
});

test("luck scale covers zero and both intervals", () => {
  const x = luckScale(luck(1, 2, 0.5, 3), 88);
  assert.equal(x(0), 4);
  assert.equal(x(3), 92);
});

test("figure never falls back to the market figure on the your-cost view", () => {
  const row = { net_pnl: 10, win_rate: 0.5, your_cost: { net_pnl: 7 } } as unknown as ScoreboardRow;
  assert.equal(figure(row, "net_pnl", "market"), 10);
  assert.equal(figure(row, "net_pnl", "your"), 7);
  assert.equal(figure(row, "win_rate", "your"), null);
  assert.equal(luckOf(row, "your"), null);
});

test("nice ticks are round steps inside the span", () => {
  assert.deepEqual(niceTicks(-10500, 1200, 4), [-10000, -8000, -6000, -4000, -2000, 0]);
  assert.deepEqual(niceTicks(0, 0, 4), [0]);
});

test("ranking: by market-cost profit, then trades; rowless strategies follow by family then id", () => {
  const p = mockup<StrategyLabPayload>("05-strategy-lab");
  const slice = { view: "accuracy" as const, basis: "forward" as const, horizon: "all" as const };
  const { ids, byId } = ranking(p, slice);
  assert.equal(ids.length, Object.keys(p.strategies).length);
  const ranked = ids.filter((id) => byId.has(id)).map((id) => byId.get(id)!.net_pnl as number);
  assert.deepEqual(ranked, ranked.slice().sort((a, b) => b - a));
  const rest = ids.filter((id) => !byId.has(id)).map((id) => p.strategies[id].family);
  const order = { rule: 0, baseline: 1, ai: 2 };
  assert.deepEqual(rest, rest.slice().sort((a, b) => order[a] - order[b]));
  assert.equal(defaultSelection(p, slice), ids[0]);
});

test("a missing profit ranks after every number and beats no baseline", () => {
  const p = structuredClone(mockup<StrategyLabPayload>("05-strategy-lab"));
  const slice = { view: "accuracy" as const, basis: "forward" as const, horizon: "all" as const };
  const top = ranking(p, slice).ids[0];
  const row = p.rows.find((r) => r.scope === "strategy" && r.view === "accuracy" && r.basis === "forward" && r.horizon_days === "all" && r.strategy_id === top)!;
  row.net_pnl = null;
  const { ids, byId } = ranking(p, slice);
  const withRow = ids.filter((id) => byId.has(id));
  assert.equal(withRow[withRow.length - 1], top);
  // the null-profit baseline is no longer the best yardstick: the next baseline (Always buy, −₹9,309) is, and the two
  // AI traders at −₹4,784 beat it; Model + news (−₹9,309, equal) does not
  const picks = kpiPicks(p, slice);
  assert.equal(picks.bestBaseline!.strategy_id, "base.always_up.v1");
  assert.equal(picks.beat, 2);
});

test("forward and back-test rows are never pooled", () => {
  const p = mockup<StrategyLabPayload>("05-strategy-lab");
  const forward = rowsOf(p.rows, "strategy", "all", "accuracy", "forward");
  const back = rowsOf(p.rows, "strategy", "all", "accuracy", "backtest");
  assert.ok(forward.length > 0 && back.length > 0);
  assert.ok(forward.every((row) => row.basis === "forward") && back.every((row) => row.basis === "backtest"));
  const { byId } = ranking(p, { view: "accuracy", basis: "backtest", horizon: "all" });
  for (const row of byId.values()) assert.equal(row.basis, "backtest");
});

test("KPI picks: leader, best baseline, how many beat it, nearest to go-live", () => {
  const p = mockup<StrategyLabPayload>("05-strategy-lab");
  const k = kpiPicks(p, { view: "accuracy", basis: "forward", horizon: "all" });
  assert.equal(p.strategies[k.leader!.strategy_id].name, "Model without news");
  assert.equal(k.bestBaseline!.strategy_id, k.leader!.strategy_id);
  assert.equal(k.beat, 0);
  assert.equal(k.contenders, 3);
  assert.equal(p.strategies[k.nearest!.strategy_id].name, "Model + news");
});

test("compact heatmap profit: three significant digits, lakh and crore for rupees", () => {
  assert.equal(compactProfit("INR", -3805.2), "−3.81k");
  assert.equal(compactProfit("INR", 1016), "+1.02k");
  assert.equal(compactProfit("INR", 254300), "+2.54L");
  assert.equal(compactProfit("INR", -31_200_000), "−3.12Cr");
  assert.equal(compactProfit("USD", 1_234_567), "+1.23M");
  assert.equal(compactProfit("USD", 640), "+640");
  assert.equal(compactProfit("USD", 0.2), "0");
});

test("heat shares: the largest absolute value is darkest (60), a missing cell 0", () => {
  assert.deepEqual(heatShares([{ n: 1, net: -10, win: 0 }, { n: 1, net: 5, win: 1 }, null], "net"), [60, 30, 0]);
});

test("heat weeks: the week picker falls back to all weeks", () => {
  const p = mockup<StrategyLabPayload>("05-strategy-lab");
  const all = heatWeeks(p.cells, "accuracy", "forward", "2099-W01");
  assert.equal(all.week, "all");
  assert.deepEqual(all.weeks, ["2026-W40", "2026-W41"]);
  assert.equal(heatWeeks(p.cells, "accuracy", "backtest", "all").cells.length, 0);
});

test("cumulative series carry each running total flat between its dates", () => {
  const line = (series: string, date: string, cumulative: number) =>
    ({ market: "india", view: "accuracy" as const, basis: "forward" as const, series, date, net_pnl: 0, cumulative_net_pnl: cumulative });
  const { dates, series } = cumulativeSeries([line("a", "2026-10-01", 5), line("b", "2026-10-02", -3), line("a", "2026-10-03", 8)], "accuracy", "forward");
  assert.deepEqual(dates, ["2026-10-01", "2026-10-02", "2026-10-03"]);
  assert.deepEqual(series.find((s) => s.id === "a")!.points, [5, 5, 8]);
  assert.deepEqual(series.find((s) => s.id === "b")!.points, [0, -3, -3]);
  assert.deepEqual(colouredSeries(series, "b", ["b", "a"]), ["b", "a"]);
  assert.equal(cumulativeSeries([line("a", "2026-10-01", 5)], "accuracy", "backtest").dates.length, 0);
});

test("strategy settings in words", () => {
  assert.equal(fmtParam(["confirmed_primary", "corroborated"]), "confirmed primary, corroborated");
  assert.equal(fmtParam(false), "no");
  assert.equal(fmtParam(0.5), "0.5");
});

test("track record words and verdict colours", () => {
  assert.equal(keyWords("1d close_to_close"), "1 session · close→close");
  assert.equal(keyWords("5d open_to_close"), "5 sessions · open→close");
  assert.equal(keyWords("other"), "other");
  assert.equal(basisLabel("open_to_close"), "open→close");
  assert.equal(verdictKind("not distinguishable"), "neutral");
  assert.equal(verdictKind("beats the baseline"), "success");
  assert.equal(verdictKind("loses to the baseline"), "danger");
  assert.equal(intervalClass(0.51, 0.6, 0.5), "up");
  assert.equal(intervalClass(0.4, 0.49, 0.5), "down");
  assert.equal(intervalClass(0.45, 0.55, 0.5), "");
  assert.equal(symmetricSpan(-0.92, 0.01, -0.44), 1.1);
});

test("track record basis rows, back-test groups, calibration frame and the weekly series", () => {
  const p = mockup<TrackRecordPayload>("08-track-record");
  const basis = selectedBasis(p.track.calls, null)!;
  assert.equal(basis.key, "close_to_close");
  const rows = horizonRows(basis);
  assert.equal(rows[0].name, "All horizons");
  assert.ok(rows.slice(1).every((row) => row.legacy));
  const groups = groupByKey(p.track.backtest!.strategy);
  assert.deepEqual(groups.map(([key]) => key), ["1d open_to_close", "5d open_to_close"]);
  const frame = calibrationLayout(basis.all.reliability, 600);
  assert.equal(frame.x(0.5), frame.left);
  assert.equal(frame.x(0.9), frame.width - frame.right);
  assert.equal(frame.y(1), frame.top);
  const weekly = [{ basis: "close_to_close", key: "close_to_close", label: "close→close", weeks: [] },
    { basis: "open_to_close", key: "open_to_close", label: "open→close", weeks: [] }];
  assert.equal(weeklyOf(weekly, "open_to_close")!.key, "open_to_close");
  assert.equal(weeklyOf(weekly, "open_to_close legacy_5d_d4"), null);
  assert.equal(weeklyOf(undefined, "close_to_close"), null);
});
