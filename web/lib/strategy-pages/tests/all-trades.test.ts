// "All paper trades in one place" (B16): the summary row a filter reads, the filters (one scope only, results on
// closed trades only) and the plain words of each row, on a small hand-made all_trades block in B13's fields.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  countsWords, familiesOf, filterTrades, openHeadline, perSession, pickSession, resultFigure, rowBands, sessionWords, stateWords, summaryRow,
  totalFamily, type AllTrades, type AllTradesRow, type AllTradesSession, type AllTradesSummaryRow,
} from "../all-trades.ts";

const sum = (scope: AllTradesSummaryRow["scope"], family: AllTradesSummaryRow["family"], period: AllTradesSummaryRow["period"], over: Partial<AllTradesSummaryRow> = {}): AllTradesSummaryRow =>
  ({ scope, family, period, open: 1, closed: 2, wins: 1, losses: 1, flat: 0, win_rate: 50, net_pnl_market: 10, net_pnl_your: 5, pnl_your_missing: 0, currency: "INR", ...over });

const row = (id: string, scope: AllTradesRow["scope"], state: AllTradesRow["state"], outcome: AllTradesRow["outcome"], over: Partial<AllTradesRow> = {}): AllTradesRow =>
  ({ id, scope, view: scope === "mine" ? null : scope === "all" ? "accuracy" : "head_to_head", strategy_id: scope === "mine" ? null : "rule.model_news.v1",
    family: scope === "mine" ? "mine" : "rule", pick_rule: null, ticker: "RELIANCE", horizon_days: scope === "mine" ? null : 3, entry_date: "2026-10-05",
    exit_date: "2026-10-08", state, outcome, entry_price: 100, exit_or_last_price: 101, price_pending: false, quantity: 10, amount: 1000,
    currency: "INR", pnl_market: state === "closed" && scope !== "mine" ? 5 : null, pnl_your: state === "closed" ? 3 : null,
    return_pct_market: null, return_pct_your: null, settled_at: null, paper: true, ...over });

const block: AllTrades = {
  window: { sessions: 10, from: "2026-09-28", to: "2026-10-09" },
  summary: [sum("all", "all", "to_date"), sum("all", "all", "window", { closed: 1 }), sum("all", "rule", "to_date"), sum("all", "ai", "to_date"),
    sum("head_to_head", "all", "to_date", { open: 0, closed: 0, wins: 0, losses: 0, win_rate: null }), sum("mine", "mine", "to_date", { net_pnl_market: null })],
  trades: [row("a1", "all", "open", null, { unrealised_pnl: 4 }), row("a2", "all", "closed", "win"), row("a3", "all", "closed", "loss", { pnl_market: -2 }),
    row("a4", "all", "not_entered", null, { not_entered_reason: "no_entry", pnl_your: null }), row("h1", "head_to_head", "closed", "win"),
    row("m1", "mine", "closed", "win", { side: "sell", entry_date: null })],
};

test("the summary row of a scope, family and period", () => {
  assert.equal(summaryRow(block, "all", "all", "window")!.closed, 1);
  assert.equal(summaryRow(block, "all", "baseline", "to_date"), null);
  assert.deepEqual(familiesOf(block, "all"), ["all", "rule", "ai"]);
  assert.deepEqual(familiesOf(block, "mine"), ["mine"]);
  assert.equal(totalFamily("mine"), "mine");
  assert.equal(totalFamily("head_to_head"), "all");
});

test("filters keep one scope only and results on closed trades only", () => {
  const ids = (f: Parameters<typeof filterTrades>[1]) => filterTrades(block, f).map((r) => r.id);
  assert.deepEqual(ids({ scope: "all", state: "any", result: "any" }), ["a1", "a2", "a3", "a4"]);
  assert.deepEqual(ids({ scope: "all", state: "open", result: "any" }), ["a1"]);
  assert.deepEqual(ids({ scope: "all", state: "closed", result: "any" }), ["a2", "a3"]);
  assert.deepEqual(ids({ scope: "all", state: "any", result: "win" }), ["a2"]);
  assert.deepEqual(ids({ scope: "all", state: "open", result: "loss" }), []);
  assert.deepEqual(ids({ scope: "head_to_head", state: "any", result: "any" }), ["h1"]);
  assert.deepEqual(ids({ scope: "mine", state: "any", result: "win" }), ["m1"]);
});

test("each row in plain words, and the figure its result is judged on", () => {
  const [open, win, loss, never, , mine] = block.trades;
  assert.equal(stateWords(open), "open");
  assert.equal(stateWords({ ...open, price_pending: true }), "open, no price yet");
  assert.equal(stateWords(win), "closed, made money");
  assert.equal(stateWords(loss), "closed, lost money");
  assert.equal(stateWords(never), "did not enter: no stored open price that day");
  assert.deepEqual(resultFigure(open), { value: 4, cost: "before" });
  assert.deepEqual(resultFigure(loss), { value: -2, cost: "market" });
  assert.deepEqual(resultFigure(mine), { value: 3, cost: "your" });
});

test("the headline counts in words", () => {
  assert.equal(countsWords(summaryRow(block, "all", "all", "to_date")), "1 open · 2 closed · 1 won, 1 lost");
  assert.equal(countsWords(summaryRow(block, "head_to_head", "all", "to_date")), "0 open · 0 closed");
  assert.equal(countsWords(null), "nothing recorded yet");
});

// B13's portfolio-size split: the accuracy view's trades live on per-session pages, `sessions` lists them newest first.
const sess = (session_date: string, over: Partial<AllTradesSession> = {}): AllTradesSession =>
  ({ session_date, entered: 5, not_entered: 1, open: 4, closed: 1, wins: 1, losses: 0, flat: 0, win_rate: 100, net_pnl_market: 2,
    net_pnl_your: 1, unrealised_pnl: 3, flagged_open: 0, ...over });
const split: AllTrades = {
  ...block,
  summary: [sum("all", "all", "to_date", { open: 7, unrealised_pnl: -12.5, flagged_open: 2 }), sum("head_to_head", "all", "to_date", { open: 3 })],
  trades: [row("h1", "head_to_head", "open", null)],
  sessions: [sess("2026-10-09", { flagged_open: 2 }), sess("2026-10-08", { closed: 0 })],
};

test("per-session pages: whether the split is there, and the session a picker opens on", () => {
  assert.equal(perSession(block), false);
  assert.equal(perSession(split), true);
  assert.equal(perSession({ ...split, sessions: [] }), true);
  assert.equal(pickSession(split, null), "2026-10-09");
  assert.equal(pickSession(split, "2026-10-08"), "2026-10-08");
  assert.equal(pickSession(split, "2026-09-01"), "2026-10-09", "a session without a page falls back to the newest");
  assert.equal(pickSession({ ...split, sessions: [] }, "2026-10-08"), null);
  assert.equal(pickSession(block, null), null);
});

test("the open-trades headline per view from the summary rows, never added together", () => {
  assert.equal(openHeadline(block), null, "before the split the page keeps reading open_trades");
  assert.deepEqual(openHeadline(split), { open: 7, unrealised: -12.5, flagged: 2, h2hOpen: 3 });
  assert.deepEqual(openHeadline({ ...split, summary: [] }), { open: 0, unrealised: null, flagged: 0, h2hOpen: null });
});

test("an open row's range only when every band and the target are there; a session in words", () => {
  const full = row("o1", "all", "open", null, { lo80: 90, lo50: 95, hi50: 105, hi80: 110, target_price: 101 });
  assert.deepEqual(rowBands(full), { lo80: 90, lo50: 95, hi50: 105, hi80: 110, target_price: 101 });
  assert.equal(rowBands({ ...full, hi80: null }), null);
  assert.equal(rowBands(row("o2", "all", "open", null)), null);
  const fmt = (iso: string) => `d${iso.slice(8)}`;
  assert.equal(sessionWords(split.sessions![0], fmt), "d09 · 5 entered · 4 open · 1 closed · 2 flagged");
  assert.equal(sessionWords(split.sessions![1], fmt), "d08 · 5 entered · 4 open");
});
