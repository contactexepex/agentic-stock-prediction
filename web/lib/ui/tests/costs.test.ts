import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { pageSlice, pickCandidate, viableLine, yourViable, type Pick } from "../costs.ts";

const home = JSON.parse(readFileSync(join(import.meta.dirname, "..", "..", "..", "..", "design", "mockups", "01-home", "data.json"), "utf8").replace(/: NaN\b/g, ": null"));

test("cost views of the Home mockup's picks", () => {
  const picked = (home.markets.india.head_to_head as (Pick & { status: string })[]).filter((k) => k.status === "picked");
  assert.ok(picked.length > 0);
  const k = picked[0];
  assert.equal(pickCandidate(k)?.horizon_days, k.horizon_days);
  assert.equal(typeof yourViable(k), "boolean");
  assert.match(viableLine(picked), /^(none clears|\d+ clears?) market costs · /);
});

test("viable line words", () => {
  const base = { prob_up: 0.6, move_pct: 2, loss_pct: 1, costs_pct: 0.5, amount: 1000 };
  const a: Pick = { ...base, horizon_days: 1, expected_gain_pct: 0.3, candidates: [{ horizon_days: 1, cost_viable: true }] };
  const b: Pick = { ...base, horizon_days: 2, expected_gain_pct: -0.1, candidates: [{ horizon_days: 2, cost_viable: false }] };
  assert.equal(viableLine([a, b]), "1 clears market costs · 1 viable at your cost");
  assert.equal(viableLine([b]), "none clears market costs · none viable at your cost");
  assert.equal(viableLine([{ ...b, candidates: [] }]), "none clears market costs · your-cost view not stored");
});

test("page slices", () => {
  const items = Array.from({ length: 23 }, (_, i) => i);
  assert.deepEqual(pageSlice(items, 3, 10), { page: 3, pages: 3, rows: [20, 21, 22] });
  assert.equal(pageSlice(items, 9, 10).page, 3);
  assert.deepEqual(pageSlice([], 1, 10), { page: 1, pages: 1, rows: [] });
});
