// The wire to B1's importer, TypeScript side: the exact inbox rows the tool layer writes for each kind of write are
// kept in inbox_wire.fixture.json. tests/test_b5_tools.py inserts those rows with the real statements of sql.ts into a
// DuckDB file built from mcp/inbox.sql and runs B1's `company.py import-inbox` on it. Regenerate the fixture after an
// intended change with: UPDATE_INBOX_FIXTURE=1 npm test
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { MSFT, rig } from "./fakes.ts";
import { githubContext, slackContext } from "../identity.ts";

const FIXTURE = new URL("./inbox_wire.fixture.json", import.meta.url);

test("the inbox rows of each write kind match the fixture B1's importer is tested on", async () => {
  const r = rig();
  const slack = slackContext("U07ABCD123");
  const app = githubContext("owner-login");
  const outcomes = [
    await r.layer.execute(slack, "deactivate_company", { market: "us", ticker: "DAL", reason: "pause airlines",
      idempotency_key: "wire-deact-dal-01" }, { confirmedSummary: true, slackThread: { channel: "C0C6REB7QS2", ts: "1791400000.000101" } }),
    await r.layer.execute(app, "set_paper_amount", { market: "us", ticker: "AAPL", amount: 1500,
      idempotency_key: "wire-amount-aapl-01" }, { confirmedSummary: true, slackThread: { channel: "C0C6REB7QS2", ts: "1791400000.000103" } }),
    await r.layer.execute(slack, "add_company", { market: "us", symbol: "MSFT", idempotency_key: "wire-add-msft-01" },
      { confirmedSummary: true, preview: MSFT, slackThread: { channel: "C0C6REB7QS2", ts: "1791400000.000102" } }),
    await r.layer.execute(app, "add_paper_trade", { market: "us", ticker: "AAPL", side: "buy", quantity: 2,
      trade_date: "2026-10-06", price_basis: "close", idempotency_key: "wire-trade-aapl-01" }),
  ];
  assert.deepEqual(outcomes.map((outcome) => outcome.result), ["pending", "pending", "pending", "pending"]);
  assert.equal(r.dispatcher.calls, 3, "only company commands start onboard.yml");
  assert.match(outcomes[3].message ?? "", /paper-trade import is not built yet/);
  assert.deepEqual(r.inbox.requests.map((row) => [row.slack_channel, row.slack_ts]), [
    ["C0C6REB7QS2", "1791400000.000101"], [null, null], ["C0C6REB7QS2", "1791400000.000102"], [null, null],
  ], "Slack ids are kept for the slack channel only (the Claude app's thread is ignored)");
  const rows = JSON.stringify(r.inbox.requests, null, 2) + "\n";
  if (process.env.UPDATE_INBOX_FIXTURE === "1") writeFileSync(FIXTURE, rows);
  assert.equal(rows, readFileSync(FIXTURE, "utf8"), "the inbox rows changed: rerun with UPDATE_INBOX_FIXTURE=1 and check B1's import");
});
