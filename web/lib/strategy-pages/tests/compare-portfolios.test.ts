// B16's page logic for 06 Rule vs AI and 07 Paper portfolios, offline, on the mockups' data.json payloads and small
// hand-made records.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  familyLines, familyRow, matchTally, matchWinner, matches, perCompany, pickFor, tradeNet, viableLine, whoLeads,
  type RuleVsAiPayload, type SettledTrade,
} from "../rule-vs-ai.ts";
import {
  groupOpenTrades, latestChecks, newIdempotencyKey, openSummary, positionsSummary, receiptState, tradeRequest,
  type PaperPortfoliosPayload, type TradeForm,
} from "../paper-portfolios.ts";

const REPO = fileURLToPath(new URL("../../../../", import.meta.url));
const mockup = <T>(page: string, market = "india"): T =>
  JSON.parse(readFileSync(`${REPO}design/mockups/${page}/data.json`, "utf8")).markets[market] as T;

test("rule vs AI: who leads, matches and their tally on the mockup", () => {
  const p = mockup<RuleVsAiPayload>("06-rule-vs-ai");
  const lead = whoLeads(familyRow(p.rows, "rule"), familyRow(p.rows, "ai"), "market");
  assert.deepEqual(lead, { leader: "level", by: 0 });
  const list = matches(p.trades);
  assert.equal(list.length, 1);
  assert.equal(list[0].ticker, "RELIANCE");
  assert.equal(matchWinner(list[0], p.your_costs, "market"), "draw");
  assert.deepEqual(matchTally(list, p.your_costs, "market"), { both: 1, rule: 0, ai: 0, draw: 1 });
});

const trade = (family: "rule" | "ai", ticker: string, entry: string, exit: string, net: number, id = `${family}-${ticker}-${entry}`): SettledTrade =>
  ({ trade_id: id, prediction_id: id, strategy_id: `${family}.x`, family, view: "head_to_head", pick_rule: "highest_probability",
    ticker, horizon_days: 1, entry_date: entry, exit_date: exit, exit_date_actual: null, net_pnl: net, return_pct: net / 100,
    target_error_pct: 1, target_reached: true });

test("matches: newest entry first; a one-sided match has no winner; a missing your-cost figure is unknown", () => {
  const trades = [trade("rule", "A", "2026-10-01", "2026-10-02", 5), trade("ai", "A", "2026-10-01", "2026-10-02", 3),
    trade("rule", "B", "2026-10-02", "2026-10-03", -1)];
  const list = matches(trades);
  assert.deepEqual(list.map((m) => m.ticker), ["B", "A"]);
  assert.equal(matchWinner(list[0], [], "market"), null);
  assert.equal(matchWinner(list[1], [], "market"), "rule");
  assert.equal(matchWinner(list[1], [], "your"), "unknown");
  assert.equal(tradeNet(trades[0], [{ trade_id: trades[0].trade_id, net_pnl_your: 4, return_pct_your: 0.04 }], "your"), 4);
  assert.equal(tradeNet(trades[0], [], "your"), null);
  const picks = [{ id: "p", ticker: "B", session_date: "2026-10-02", family: "ai" as const, pick_rule: "highest_probability",
    status: "picked", strategy_id: "ai.x", horizon_days: 3, prob_up: 0.6, move_pct: 1, loss_pct: 1, costs_pct: 0.2,
    expected_gain_pct: 0.1, candidates: [], amount: 1 }];
  assert.equal(pickFor(picks, list[0], "ai")?.id, "p");
  assert.equal(pickFor(picks, list[0], "rule"), null);
});

test("per company sums and the cumulative family lines start at zero on the first entry", () => {
  const trades = [trade("rule", "A", "2026-10-01", "2026-10-02", 5), trade("ai", "A", "2026-10-01", "2026-10-03", -2),
    trade("rule", "A", "2026-10-02", "2026-10-03", -1)];
  const sums = perCompany(trades, [], "market");
  assert.deepEqual(sums, [{ ticker: "A", rule: { n: 2, net: 4, won: 1 }, ai: { n: 1, net: -2, won: 0 } }]);
  assert.deepEqual(perCompany(trades, [], "your")[0].rule, { n: 2, net: null, won: null });
  assert.deepEqual(familyLines(trades), { dates: ["2026-10-01", "2026-10-02", "2026-10-03"], rule: [0, 5, 4], ai: [0, 0, -2] });
  assert.deepEqual(familyLines([]), { dates: [], rule: [], ai: [] });
});

test("the picks' cost line", () => {
  const p = mockup<RuleVsAiPayload>("06-rule-vs-ai");
  const picked = p.picks.filter((pick) => pick.session_date === p.session_date && pick.status === "picked");
  assert.equal(viableLine(picked), "none clears market costs · none viable at your cost");
  assert.equal(viableLine([]), "none clears market costs · your-cost view not stored");
});

test("paper portfolios: KPI sums, grouping by strategy and the latest check", () => {
  const p = mockup<PaperPortfoliosPayload>("07-paper-portfolios");
  const open = openSummary(p);
  assert.equal(open.open, 14);
  assert.equal(Math.round(open.unrealised!), 30212);
  const own = positionsSummary(p.owner.positions);
  assert.deepEqual(own, { count: 1, value: 60900, pnl: 1800 });
  const groups = groupOpenTrades(p.open_trades, p.strategies, { family: null, view: null });
  assert.deepEqual(groups.map((g) => p.strategies[g.id].family), ["rule", "baseline", "baseline", "ai", "ai"]);
  assert.equal(groups.reduce((n, g) => n + g.trades.length, 0), 14);
  const ai = groupOpenTrades(p.open_trades, p.strategies, { family: "ai", view: "head_to_head" });
  assert.ok(ai.every((g) => g.trades.every((t) => t.family === "ai" && t.view === "head_to_head")));
  const checks = latestChecks([{ trade_id: "t", check_at: "2026-10-07T05:00:00Z", id: "a" }, { trade_id: "t", check_at: "2026-10-07T08:00:00Z", id: "b" }] as never);
  assert.equal(checks.get("t")!.id, "b");
});

const form = (over: Partial<TradeForm> = {}): TradeForm => ({ ticker: "RELIANCE", side: "buy", quantity: "5", trade_date: "2026-10-07",
  price_basis: "open", price: "", note: "", ...over });

test("the add-trade form's request: body fields only, whole shares in India, a typed price only when manual", () => {
  const active = new Set(["RELIANCE", "AAPL"]);
  assert.deepEqual(tradeRequest(form(), "INR", active), { body: { ticker: "RELIANCE", side: "buy", quantity: 5, trade_date: "2026-10-07", price_basis: "open" } });
  assert.deepEqual(tradeRequest(form({ quantity: "1.5" }), "INR", active), { errors: ["Whole shares only in India."] });
  assert.deepEqual(tradeRequest(form({ ticker: "AAPL", quantity: "1.5", price_basis: "manual", price: "330.5", note: " mine " }), "USD", active),
    { body: { ticker: "AAPL", side: "buy", quantity: 1.5, trade_date: "2026-10-07", price_basis: "manual", price: 330.5, note: "mine" } });
  assert.ok("errors" in tradeRequest(form({ price_basis: "manual", price: "" }), "INR", active));
  assert.ok("errors" in tradeRequest(form({ ticker: "OLD" }), "INR", active));
  assert.ok("errors" in tradeRequest(form({ quantity: "0" }), "INR", active));
  assert.ok("errors" in tradeRequest(form({ note: "x".repeat(201) }), "INR", active));
});

test("receipt states and the idempotency key's format", () => {
  assert.equal(receiptState(202), "pending");
  assert.equal(receiptState(200), "duplicate");
  assert.equal(receiptState(429), "retry");
  assert.equal(receiptState(503), "retry");
  assert.equal(receiptState(422), "refused");
  assert.equal(receiptState(409), "refused");
  assert.match(newIdempotencyKey(), /^[A-Za-z0-9_-]{8,64}$/);
});
