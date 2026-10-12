// The route's serve rules (lib/data/serve.ts) against the fixture shared with the Python mirror
// (scripts/marketbrief/warehouse/contract.py; tests/test_api_contract.py reads the same file).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { serve, type StoredRow, syncTimeFor } from "../serve.ts";
import type { ServeMode } from "../constants.ts";

const fixture = JSON.parse(readFileSync(new URL("./serve.fixture.json", import.meta.url), "utf8")) as {
  now: string;
  cases: { name: string; mode: ServeMode; row: StoredRow; synced_at?: string; expected: unknown }[];
};

for (const item of fixture.cases) {
  test(`serve: ${item.name}`, () => {
    assert.deepEqual(serve(item.row, item.mode, new Date(fixture.now), item.synced_at ?? null), item.expected);
  });
}

test("serve: a payload stored as JSON text is parsed", () => {
  const row = { ...fixture.cases[0].row, payload: JSON.stringify(fixture.cases[0].row.payload) };
  assert.deepEqual(serve(row, "page", new Date(fixture.now)), fixture.cases[0].expected);
});

test("syncTimeFor: the status row's built_at, except for a page that failed validation in that sync", () => {
  const status = {
    market: "us", page_key: "_", as_of: null, cutoff: null, built_at: "2026-10-07T11:00:00.000Z",
    schema_version: "2.0.0", source_commit: "abc", payload_sha256: "x",
    payload: { market: "us", invalid_pages: [{ table: "stock", page_key: "NVDA" }] },
  };
  assert.equal(syncTimeFor(status, "stock", "AAPL"), "2026-10-07T11:00:00Z");
  assert.equal(syncTimeFor(status, "stock", "NVDA"), null);
  assert.equal(syncTimeFor(status, "home", "NVDA"), "2026-10-07T11:00:00Z");
  assert.equal(syncTimeFor({ ...status, payload: { market: "us" } }, "stock", "NVDA"), "2026-10-07T11:00:00Z");
  assert.equal(syncTimeFor(null, "stock", "NVDA"), null);
});
