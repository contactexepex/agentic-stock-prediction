// Help's data selection equals the mockup's (design/mockups/12-help/data.json) when read from the Strategy lab and
// Companies mockups, i.e. from the endpoints' approved payloads.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { agreementExample, aiHorizons, goLiveChecks, referenceGoLive } from "../help.ts";

const mockups = join(import.meta.dirname, "..", "..", "..", "..", "design", "mockups");
const read = (page: string) => JSON.parse(readFileSync(join(mockups, page, "data.json"), "utf8").replace(/: NaN\b/g, ": null"));
const help = read("12-help"), lab = read("05-strategy-lab"), companies = read("10-companies");

for (const market of ["india", "us"]) {
  test(`help data for ${market} matches the approved mockup`, () => {
    const want = help.markets[market];
    assert.deepEqual(referenceGoLive(lab.markets[market]), want.go_live_detail);
    assert.deepEqual(agreementExample(companies.markets[market]), want.agreement_example);
    assert.equal(companies.markets[market].default_amount, want.default_amount);
    const ref = Object.values(want.strategies as Record<string, { family: string; compared_to: string | null; id: string }>).find((s) => s.family === "rule" && !s.compared_to);
    assert.equal(lab.markets[market].reference_strategy, ref?.id);
    for (const [id, s] of Object.entries(want.strategies as Record<string, Record<string, unknown>>)) {
      const got = lab.markets[market].strategies[id];
      for (const key of ["name", "family", "description", "compared_to", "differs_in", "threshold"]) assert.deepEqual(got[key], s[key], `${id}.${key}`);
    }
    assert.deepEqual(aiHorizons(lab.markets[market].strategies), [1, 3, 5]);
  });
}

test("go-live checks", () => {
  const checks = goLiveChecks({ proven: false, months_forward: 2.1, trades_needed: 0, beats_best_baseline: null, drawdown_within_limit: true }, 2);
  assert.deepEqual(checks.map((c) => c.passed), [true, true, null, true, null]);
});
