// The route's serve rules (lib/data/serve.ts) against the fixture shared with the Python mirror
// (scripts/marketbrief/warehouse/contract.py; tests/test_api_contract.py reads the same file).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { serve, type StoredRow } from "../serve.ts";
import type { ServeMode } from "../constants.ts";

const fixture = JSON.parse(readFileSync(new URL("./serve.fixture.json", import.meta.url), "utf8")) as {
  now: string;
  cases: { name: string; mode: ServeMode; row: StoredRow; expected: unknown }[];
};

for (const item of fixture.cases) {
  test(`serve: ${item.name}`, () => {
    assert.deepEqual(serve(item.row, item.mode, new Date(fixture.now)), item.expected);
  });
}

test("serve: a payload stored as JSON text is parsed", () => {
  const row = { ...fixture.cases[0].row, payload: JSON.stringify(fixture.cases[0].row.payload) };
  assert.deepEqual(serve(row, "page", new Date(fixture.now)), fixture.cases[0].expected);
});
