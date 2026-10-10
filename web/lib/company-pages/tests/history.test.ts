// The company page's forecast history (B15 on B12's rm.stock `forecast_history`), on a real stored sample:
// HDFCBANK's runs built by warehouse/company_history.forecast_history at the cut-off 2026-10-10T06:00Z (the page
// build's window: as-of 2026-09-24..2026-10-08; the stored runs fall on 2026-10-06..2026-10-08) (fixtures/forecast-history-hdfcbank.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  centreMovePct, historyAt, historyEntries, historyGeometry, rangeChangeWords, scoreChangeWords, scoreParts, type HistoryEntry,
} from "../history-logic.ts";
import type { ForecastHistory, HistoryRange, HistoryScore } from "../types.ts";

const asRange = (e: HistoryEntry) => e as Extract<HistoryEntry, { kind: "range" }>;
const asScore = (e: HistoryEntry) => e as Extract<HistoryEntry, { kind: "score" }>;
const hdfc: ForecastHistory = JSON.parse(readFileSync(new URL("./fixtures/forecast-history-hdfcbank.json", import.meta.url), "utf8"));

test("runs of one horizon in time order; nothing without a history", () => {
  const { ranges, scores } = historyAt(hdfc, 1);
  assert.deepEqual(ranges.map((r) => r.made_at), ["2026-10-08T02:26:06Z", "2026-10-09T02:26:28Z"]);
  assert.equal(scores.length, 5);
  assert.ok(scores.every((s, i) => i === 0 || s.computed_at > scores[i - 1].computed_at));
  assert.ok([...ranges, ...scores].every((r) => r.horizon_days === 1));
  assert.deepEqual(historyAt(null, 1), { ranges: [], scores: [] });
  assert.deepEqual(historyAt(hdfc, 9), { ranges: [], scores: [] });
});

test("entries: newest first, each paired with the run its change was taken against", () => {
  const { ranges, scores } = historyAt(hdfc, 5);
  const list = historyEntries(ranges, scores);
  assert.equal(list.length, ranges.length + scores.length);
  assert.ok(list.every((e, i) => i === 0 || e.at <= list[i - 1].at));
  for (const e of list) {
    if (!e.row.change) assert.equal(e.previous, null);
    else assert.equal(e.previous?.id, e.row.change.from_id);
  }
});

test("range change words: B12's example (HDFCBANK N+5, 8 Oct against 7 Oct: target -1.2983%, new calibration)", () => {
  const { ranges } = historyAt(hdfc, 5);
  const [first, second] = historyEntries(ranges, []).reverse();
  assert.deepEqual(rangeChangeWords(asRange(first)), ["first range run in the window"]);
  assert.deepEqual(rangeChangeWords(asRange(second)), ["new close", "target −1.30%", "80% range narrower by 0.52%", "new calibration"]);
  const r = second.row as HistoryRange;
  assert.ok(Math.abs(r.base_close * (1 + (centreMovePct(r) as number) / 100) - r.target_price) < 0.01, "target = base close x exp(center)");
});

test("range change words name the regime and the inputs that changed, and a revision of the same close", () => {
  const before = { ...hdfc.ranges[0], regime: "CALM", inputs: ["cue"] } as HistoryRange;
  const after = { ...before, made_at: "2026-10-08T21:30:00Z", regime: "TRENDING", inputs: ["beta"],
    change: { from_id: before.id, from_made_at: before.made_at, target_pct: 0, width80_pct: 0.5, changed: ["regime", "inputs"] } } as HistoryRange;
  const [e] = historyEntries([before, after], []);
  assert.deepEqual(rangeChangeWords(asRange(e)), ["revised for the same close", "target 0.00%", "80% range wider by 0.50%", "regime CALM → TRENDING", "range inputs changed: added beta; dropped cue"]);
});

test("score change words: B12's example (HDFCBANK, 9 Oct re-score after the news append)", () => {
  const { scores } = historyAt(hdfc, 5);
  const last = asScore(historyEntries([], scores)[0]);
  assert.equal(last.at, "2026-10-09T02:21:45Z");
  assert.deepEqual(scoreChangeWords(last), ["re-scored for the same close", "P(up) −0.2 pts", "points moved: news −0.23 pts", "3 news items added"]);
  const refit = { ...last.row, model_version: "logit-v2", change: { ...(last.row as HistoryScore).change!, changed: ["model_version", "trained_until"] } } as HistoryScore;
  assert.deepEqual(scoreChangeWords({ row: refit, previous: last.previous as HistoryScore }).slice(-2), ["model logit-v1 → logit-v2", "trained until 2026-10-01"]);
});

test("score parts: base rate plus the group points give P(up) (explain.py), zero groups left out", () => {
  for (const s of hdfc.scores) {
    const { base, parts, sum } = scoreParts(s);
    assert.ok(base != null && sum != null);
    assert.ok(parts.every(([, v]) => v !== 0));
    assert.ok(Math.abs(sum - (s.prob_up as number) * 100) < 0.1, `${s.id} ${s.computed_at}: ${sum} vs ${s.prob_up}`);
  }
});

test("geometry: one time axis for both panels, bands around the target, P(up) points, day labels on the market clock", () => {
  const { ranges, scores } = historyAt(hdfc, 1);
  const g = historyGeometry(ranges, scores, 900, 330)!;
  assert.equal(g.target.length, 2);
  assert.equal(g.prob.length, 5);
  for (let i = 0; i < ranges.length; i++) {
    assert.ok(g.py(ranges[i].hi80) <= g.target[i].y && g.target[i].y <= g.py(ranges[i].lo80), "target inside its 80% band");
  }
  const xs = [...g.target, ...g.prob].map((q) => q.x);
  assert.ok(Math.min(...xs) >= g.L && Math.max(...xs) <= g.W - g.R, "points inside the plot");
  assert.ok(g.prob.every((q) => q.y >= g.QT && q.y <= g.QT + g.QH), "P(up) inside its panel");
  assert.ok(g.half >= g.QT && g.half <= g.QT + g.QH);
  assert.deepEqual(g.days.map((d) => d.label), ["7 Oct", "8 Oct", "9 Oct"]);
  assert.equal(historyGeometry([], [], 900), null);
  const one = historyGeometry(ranges.slice(0, 1), [], 390)!;
  assert.ok(one.QH === 0 && one.target[0].x > one.L && one.target[0].x < one.W - one.R, "a single run sits inside the plot");
});
