import { test } from "node:test";
import assert from "node:assert/strict";
import { MSFT, SECRET_VALUES, observable, rig } from "./fakes.ts";
import { dashboardContext, githubContext, slackContext } from "../identity.ts";
import { commandId } from "../ids.ts";
import type { CallContext } from "../types.ts";

const app = githubContext("owner-login");
const slack = slackContext("U07ABCD123");

test("command ids follow core/schema_lifecycle.py (W1 example cmd-20261005T135500Z-052b8228)", async () => {
  assert.equal(await commandId(new Date("2026-10-05T13:55:00Z"), "add-msft-7Hq2", {}), "cmd-20261005T135500Z-052b8228");
  assert.match(await commandId(new Date("2026-10-06T15:00:00Z"), null, { view: "accuracy", market: "india" }), /^cmd-20261006T150000Z-[0-9a-f]{8}$/);
});

test("a read returns the read model with its as-of and is logged", async () => {
  const r = rig();
  r.reads.put("home", "us", "_", { picks: [{ ticker: "AAPL" }] });
  const outcome = await r.layer.execute(app, "get_overview", { market: "us" });
  assert.equal(outcome.result, "accepted");
  const data = outcome.data as { sources: { read_model: string; found: boolean; as_of: string }[]; requested: Record<string, unknown> };
  assert.equal(data.sources[0].read_model, "rm.home");
  assert.equal(data.sources[0].found, true);
  assert.equal(data.sources[0].as_of, "2026-10-07T01:00:00Z");
  assert.equal(data.requested.horizon_days, 1, "the tools.yaml default is applied");
  assert.deepEqual(r.reads.calls, ["home|us|_"]);
  assert.equal(r.inbox.commands.length, 1);
  const row = r.inbox.commands[0];
  assert.equal(row.channel, "claude_app");
  assert.equal(row.actor, "github:owner-login");
  assert.equal(row.agent, "claude-app");
  assert.equal(row.kind, "read");
  assert.equal(row.idempotency_key, null);
  assert.equal(row.budget_left, null);
  assert.equal(r.inbox.requests.length, 0);
  assert.equal(r.dispatcher.calls, 0);
});

test("a missing read model answers 'not in the data'", async () => {
  const r = rig();
  const outcome = await r.layer.execute(app, "get_company", { market: "india", ticker: "HDFCBANK" });
  assert.equal(outcome.result, "accepted");
  assert.equal(outcome.message, "not in the data");
  assert.deepEqual(r.reads.calls, ["stock|india|HDFCBANK", "stock_strategies|india|HDFCBANK"]);
});

test("a write is appended to the inbox, dispatches onboard.yml and answers pending", async () => {
  const r = rig();
  const args = { market: "us", ticker: "AAPL", reason: "pause", idempotency_key: "deact-aapl-0001" };
  const outcome = await r.layer.execute(app, "deactivate_company", args, { confirmedSummary: true });
  assert.equal(outcome.result, "pending");
  assert.equal(outcome.inbox_id, "deact-aapl-0001");
  assert.match(outcome.message ?? "", /^Pending: Deactivate AAPL \(US\)/);
  assert.equal(outcome.budget_left, 19);
  assert.equal(r.dispatcher.calls, 1);
  assert.equal(r.inbox.requests.length, 1);
  const request = r.inbox.requests[0];
  assert.equal(request.kind, "watchlist_events");
  assert.equal(request.submitted_by, "github:owner-login");
  assert.equal(request.channel, "claude_app");
  assert.equal(request.command_id, outcome.command_id);
  assert.match(request.args_sha256, /^[0-9a-f]{64}$/);
  const row = r.inbox.commands.at(-1)!;
  assert.equal(row.result, "pending");
  assert.equal(row.idempotency_key, "deact-aapl-0001");
  assert.equal(row.kind, "write");
  assert.equal(row.budget_left, 19);
  assert.equal(r.notifier.reports.length, 0);
});

test("the same key and arguments again return the first result without a second write", async () => {
  const r = rig();
  const args = { market: "us", ticker: "AAPL", idempotency_key: "react-aapl-0001" };
  const first = await r.layer.execute(app, "reactivate_company", args, { confirmedSummary: true });
  r.now.value = new Date("2026-10-07T10:00:05Z");
  const second = await r.layer.execute(app, "reactivate_company", args, { confirmedSummary: true });
  assert.equal(second.result, "duplicate");
  assert.equal(second.message, first.message);
  assert.equal(r.inbox.requests.length, 1);
  assert.equal(r.dispatcher.calls, 1);
});

test("a reused key with other arguments or from another actor is refused as duplicate_key", async () => {
  const r = rig();
  await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "shared-key-001" }, { confirmedSummary: true });
  const other = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "MSFT", idempotency_key: "shared-key-001" }, { confirmedSummary: true });
  assert.equal(other.refusal_code, "duplicate_key");
  const stranger = await r.layer.execute(slack, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "shared-key-001" }, { confirmedSummary: true });
  assert.equal(stranger.refusal_code, "duplicate_key");
  assert.doesNotMatch(stranger.message ?? "", /owner-login/);
  assert.equal(r.inbox.requests.length, 1);
});

test("the per-agent day budget stops writes and resets the next UTC day", async () => {
  const r = rig();
  for (let i = 0; i < 20; i += 1) {
    const outcome = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: `budget-key-${String(i).padStart(3, "0")}` }, { confirmedSummary: true });
    assert.equal(outcome.result, "pending");
  }
  const over = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "budget-key-over" }, { confirmedSummary: true });
  assert.equal(over.refusal_code, "budget_exceeded");
  assert.equal(over.budget_left, 0);
  assert.equal(r.notifier.reports.at(-1)?.refusal_code, "budget_exceeded");
  r.now.value = new Date("2026-10-08T00:00:01Z");
  const tomorrow = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "budget-key-next" }, { confirmedSummary: true });
  assert.equal(tomorrow.result, "pending");
});

test("a key already stored answers duplicate even after the day budget is used (issue #79)", async () => {
  const r = rig();
  const first = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "budget-key-first" }, { confirmedSummary: true });
  for (let i = 1; i < 20; i += 1) {
    await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: `budget-key-${String(i).padStart(3, "0")}` }, { confirmedSummary: true });
  }
  assert.equal(r.inbox.requests.length, 20);
  const retry = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "budget-key-first" }, { confirmedSummary: true });
  assert.equal(retry.result, "duplicate");
  assert.equal(retry.message, first.message);
  const fresh = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "budget-key-fresh" }, { confirmedSummary: true });
  assert.equal(fresh.refusal_code, "budget_exceeded");
  const preview = await r.layer.preview(app, "deactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "budget-key-prev" });
  assert.equal(preview.outcome?.refusal_code, "budget_exceeded", "the summary step is refused over budget too");
  assert.equal(r.inbox.requests.length, 20);
});

test("the newest controls row counts: switching an agent back on works", async () => {
  const r = rig();
  r.inbox.controls.push({ agent: "claude-app", enabled: false }, { agent: "claude-app", enabled: true });
  assert.equal((await r.layer.execute(app, "get_overview", { market: "us" })).result, "accepted");
  r.inbox.controls.push({ agent: "*", enabled: false });
  assert.equal((await r.layer.execute(app, "get_overview", { market: "us" })).refusal_code, "kill_switch");
});

test("the kill switch stops every call before its arguments are checked: the agent's controls row, and '*' for all", async () => {
  const off = rig();
  off.inbox.controls.push({ agent: "claude-app", enabled: false });
  assert.equal((await off.layer.execute(app, "get_overview", { market: "us" })).refusal_code, "kill_switch");
  assert.equal((await off.layer.execute(app, "get_overview", { market: "nowhere" })).refusal_code, "kill_switch",
    "invalid arguments are refused as kill_switch while the switch is off");
  const all = rig();
  all.inbox.controls.push({ agent: "*", enabled: false });
  assert.equal((await all.layer.execute(slack, "explain", { market: "us", question: "why?" })).refusal_code, "kill_switch");
  const controlled = rig();
  controlled.inbox.controls.push({ agent: "claude-app", enabled: false });
  const outcome = await controlled.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "kill-key-0001" }, { confirmedSummary: true });
  assert.equal(outcome.refusal_code, "kill_switch");
  assert.equal(controlled.inbox.requests.length, 0);
  assert.equal(controlled.dispatcher.calls, 0);
});

test("channel permissions follow mcp/tools.yaml: delete only from the dashboard, never in gateway mode", async () => {
  const r = rig();
  const args = { market: "us", ticker: "AAPL", confirm: "AAPL", idempotency_key: "delete-aapl-01" };
  assert.equal((await r.layer.execute(app, "delete_company", args)).refusal_code, "not_allowed_in_channel");
  assert.equal((await r.layer.execute(slack, "delete_company", args)).refusal_code, "not_allowed_in_channel");
  assert.equal((await r.layer.execute(dashboardContext(), "delete_company", args)).refusal_code, "unknown_actor", "gateway mode");
  const dash = rig({ gatewayMode: false });
  const wrongConfirm = await dash.layer.execute(dashboardContext(), "delete_company", { ...args, confirm: "aapl" });
  assert.equal(wrongConfirm.refusal_code, "validation_failed");
  const deleted = await dash.layer.execute(dashboardContext(), "delete_company", args);
  assert.equal(deleted.result, "pending");
  assert.equal(dash.inbox.requests[0].channel, "dashboard");
});

test("summary-confirm tools need the confirmation, and an add needs the confirmed preview", async () => {
  const r = rig();
  const unconfirmed = await r.layer.execute(app, "deactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "deact-unconf-1" });
  assert.equal(unconfirmed.refusal_code, "validation_failed");
  const add = { market: "us", symbol: "MSFT", idempotency_key: "add-msft-7Hq2" };
  assert.equal((await r.layer.execute(app, "add_company", add, { confirmedSummary: true })).refusal_code, "validation_failed");
  const mismatch = await r.layer.execute(app, "add_company", add, { confirmedSummary: true, preview: { ...MSFT, symbol: "AAPL" } });
  assert.equal(mismatch.refusal_code, "validation_failed");
  const otherAmount = await r.layer.execute(app, "add_company", { ...add, amount: 2500 }, { confirmedSummary: true, preview: MSFT });
  assert.equal(otherAmount.refusal_code, "validation_failed", "the confirmed amount must match too (issue #85)");
  const ok = await r.layer.execute(app, "add_company", add, { confirmedSummary: true, preview: MSFT });
  assert.equal(ok.result, "pending");
  assert.match(ok.message ?? "", /Microsoft Corporation \(NASDAQ, Technology, Yahoo MSFT, CIK 0000789019\), \$1,000 per trade \(default\)/);
  assert.deepEqual(r.inbox.requests[0].preview, MSFT);
  assert.equal(r.inbox.requests.length, 1);
});

test("the add preview resolves identifiers and logs a refused symbol (W1 example: SPY is an ETF)", async () => {
  const r = rig();
  const preview = await r.layer.preview(slack, "add_company", { market: "us", symbol: "MSFT", amount: 1500, idempotency_key: "add-msft-0002" });
  assert.equal(preview.ok, true);
  assert.equal(preview.preview?.amount, 1500);
  assert.match(preview.summary ?? "", /\$1,500 per trade$/);
  assert.equal(r.inbox.commands.length, 0, "a summary shown is not a command yet");
  const etf = await r.layer.preview(slack, "add_company", { market: "us", symbol: "SPY", idempotency_key: "add-spy-1abc" });
  assert.equal(etf.ok, false);
  assert.equal(etf.outcome?.refusal_code, "validation_failed");
  assert.equal(etf.outcome?.message, "SPY is an ETF; only common stocks can be added");
  assert.equal(r.inbox.commands.at(-1)?.result, "refused");
  assert.equal(r.notifier.reports.at(-1)?.message, "SPY is an ETF; only common stocks can be added");
  assert.equal(r.inbox.requests.length, 0);
});

test("a failed dispatch still answers pending, says the next run imports it, and tells the owner", async () => {
  const r = rig();
  r.dispatcher.fail = true;
  const outcome = await r.layer.execute(app, "reactivate_company", { market: "us", ticker: "AAPL", idempotency_key: "react-dispatch1" }, { confirmedSummary: true });
  assert.equal(outcome.result, "pending");
  assert.match(outcome.message ?? "", /next scheduled run imports it/);
  assert.match(r.notifier.reports.at(-1)?.message ?? "", /Workflow dispatch failed \(GitHub answered 500\)/);
});

test("an unavailable inbox fails closed without echoing driver text", async () => {
  const r = rig();
  r.inbox.down = true;
  const outcome = await r.layer.execute(app, "get_overview", { market: "us" });
  assert.equal(outcome.result, "failed");
  assert.equal(outcome.message, "The command log is unavailable, so nothing was done");
  assert.doesNotMatch(observable(outcome, r.notifier.reports), /password|SECRET/);
});

test("identity must match its channel; unknown agents and channels are refused", async () => {
  const r = rig();
  const forged: CallContext = { channel: "claude_app", actor: "slack:U07ABCD123", agent: "claude-app" };
  assert.equal((await r.layer.execute(forged, "get_overview", { market: "us" })).refusal_code, "unknown_actor");
  const wrongAgent: CallContext = { channel: "claude_app", actor: "github:owner-login", agent: "dashboard" };
  assert.equal((await r.layer.execute(wrongAgent, "get_overview", { market: "us" })).refusal_code, "unknown_actor");
  const code: CallContext = { channel: "claude_code", actor: "cli:session", agent: "claude-app" };
  assert.equal((await r.layer.execute(code, "get_overview", { market: "us" })).refusal_code, "unknown_actor");
  assert.equal((await r.layer.execute(app, "no_such_tool", {})).refusal_code, "validation_failed");
});

test("explain is a stub until session B8 and writes nothing", async () => {
  const r = rig();
  const outcome = await r.layer.execute(app, "explain", { market: "us", question: "Why did AAPL fall?" });
  assert.equal(outcome.result, "accepted");
  assert.equal((outcome.data as { not_in_data: boolean }).not_in_data, true);
  assert.equal(r.inbox.requests.length, 0);
  assert.equal(r.inbox.commands[0].kind, "read_ai");
});

test("a paper trade goes to portfolio_trades without a summary step", async () => {
  const r = rig();
  const outcome = await r.layer.execute(app, "add_paper_trade", {
    market: "india", ticker: "HDFCBANK", side: "buy", quantity: 10, trade_date: "2026-10-06", price_basis: "close",
    idempotency_key: "trade-hdfc-0001",
  });
  assert.equal(outcome.result, "pending");
  assert.equal(r.inbox.requests[0].kind, "portfolio_trades");
  assert.match(outcome.message ?? "", /Paper buy 10 HDFCBANK \(India\) on 2026-10-06 at the close \(a record, not an order\)/);
});

test("nothing observable carries a secret value", async () => {
  const r = rig();
  r.reads.error = new Error(`timeout user=postgres password=${SECRET_VALUES[0]}`);
  const read = await r.layer.execute(app, "get_overview", { market: "us" });
  assert.equal(read.result, "failed");
  const all = observable(read, r.inbox.commands, r.notifier.reports);
  for (const secret of SECRET_VALUES) assert.equal(all.includes(secret), false, secret);
});
