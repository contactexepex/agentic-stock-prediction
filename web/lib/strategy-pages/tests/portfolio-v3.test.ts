// The Paper portfolio page v3 (UX3): going with or against the prediction, merged rows, list order and the plain "why"
// lines, on hand-made rows in B13's fields.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  byHold, goingOf, mergeRows, openCause, ordered, ruleNoneWords, ruleStayedOut, settledCause, splitOf, type StoryRow, type TradeWhy,
} from "../portfolio-v3.ts";

const row = (id: string, over: Partial<StoryRow> = {}): StoryRow =>
  ({ id, scope: "all", view: "accuracy", strategy_id: "base.always_up.v1", family: "baseline", pick_rule: null, ticker: "ITC", horizon_days: 1,
    entry_date: "2026-10-12", exit_date: "2026-10-13", state: "open", outcome: null, entry_price: 267.15, exit_or_last_price: 257.5,
    price_pending: false, quantity: 374, amount: 100000, currency: "INR", pnl_market: null, pnl_your: null, return_pct_market: null,
    return_pct_your: null, settled_at: null, unrealised_pnl: -3609, unrealised_pct: -3.61, paper: true, ...over });

const check = (over: Partial<TradeWhy> = {}): TradeWhy => ({
  source: "intraday_check", check_at: "2026-10-12T08:44:00Z", session_date: "2026-10-12", move_pct: -3.6, market_pct: -1.0, sector_pct: -2.0,
  own_pct: -2.9, news_pct: null, company_pct: null, beta: 0.73, sector_source: "sector_etf", reason_code: null, note: null, ai_reason: null, ...over });

test("going with or against the prediction on the price since the buy; a down call flips it; no price is pending", () => {
  assert.equal(goingOf(row("a")), "against");
  assert.equal(goingOf(row("b", { exit_or_last_price: 270 })), "with");
  assert.equal(goingOf(row("c", { direction: "down" })), "with");
  assert.equal(goingOf(row("d", { exit_or_last_price: 267.15 })), "against");
  assert.equal(goingOf(row("e", { price_pending: true, entry_price: null, exit_or_last_price: null })), "pending");
});

test("the split counts each way, flagged trades, and profit and loss apart", () => {
  const s = splitOf([row("a", { check: { check_at: "x", band: null, flags: ["against_prediction"], flagged: true, ret_since_entry_pct: -3.6 } }),
    row("b", { exit_or_last_price: 270, unrealised_pnl: 1000 }), row("c", { price_pending: true, entry_price: null, exit_or_last_price: null, unrealised_pnl: null })]);
  assert.deepEqual(s, { open: 3, going_with: 1, going_against: 1, pending: 1, flagged: 1, profit: 1000, loss: -3609, unrealised_pnl: -2609 });
});

test("identical trades of two strategies on the same side are one row with their results added; other trades stay apart", () => {
  const merged = mergeRows([row("a"), row("b", { strategy_id: "base.momentum.v1" }), row("c", { family: "ai", strategy_id: "ai.x" }), row("d", { ticker: "LT" })]);
  assert.equal(merged.length, 3);
  assert.deepEqual(merged[0].rows.map((r) => r.id), ["a", "b"]);
  assert.equal(merged[0].total, -7218);
});

test("losing lists put flagged trades first, then the biggest loss; winning lists the biggest gain first", () => {
  const flagged = { check_at: "x", band: null, flags: ["against_prediction"], flagged: true, ret_since_entry_pct: -1 };
  const rows = mergeRows([row("small", { ticker: "A", unrealised_pnl: -10 }), row("big", { ticker: "B", unrealised_pnl: -900 }), row("flag", { ticker: "C", unrealised_pnl: -5, check: flagged })]);
  assert.deepEqual(ordered(rows, "against").map((m) => m.first.id), ["flag", "big", "small"]);
  assert.deepEqual(ordered(mergeRows([row("x", { ticker: "X", unrealised_pnl: 5 }), row("y", { ticker: "Y", unrealised_pnl: 50 })]), "with").map((m) => m.first.id), ["y", "x"]);
});

test("the one-line reason of an open trade names what moved it, with true minus signs", () => {
  assert.equal(openCause(check(), "Nifty 50"), "Fell mostly on its own (−2.9%); the market added −0.7%. Its sector −2.0%.");
  assert.equal(openCause(check({ move_pct: -2.33, market_pct: -1.0, beta: 1.45, own_pct: -0.9, sector_pct: -0.8 }), "Nifty 50"),
    "Fell with the whole market (Nifty 50 −1.0%, so −1.5% for this stock); −0.9% on its own. Its sector −0.8%.");
  assert.equal(openCause(null, "Nifty 50"), null);
  assert.equal(openCause(check({ market_pct: null }), "Nifty 50"), null);
});

test("the one-line reason of a finished trade names the main part and the parts that moved", () => {
  const why = check({ source: "settlement", move_pct: -1.8, market_pct: -1.2, sector_pct: 0.0, news_pct: null, company_pct: -0.6, own_pct: null, reason_code: "market" });
  assert.equal(settledCause(why), "Moved −1.8%, mostly the whole market. Parts: market −1.2%, company −0.6%.");
  assert.equal(settledCause(check()), null);
});

test("the rule strategies' empty state says why, from their best chance against their bar", () => {
  const rule = { session_date: "2026-10-12", predictions: 800, qualifying: 0, best_prob_up: 0.5034, bar: 0.55 };
  assert.equal(ruleStayedOut(rule), true);
  assert.equal(ruleStayedOut({ ...rule, qualifying: 3 }), false);
  const words = ruleNoneWords(rule);
  assert.equal(words.line, "No trades today: the signal model saw no clear rise");
  assert.match(words.tip, /at least a 55% chance\. On the newest session the highest chance was 50%, so none of their 800 predictions cleared it/);
});

test("open rows of one scope by hold, shortest first", () => {
  const holds = byHold([row("a", { horizon_days: 5 }), row("b", { horizon_days: 1 }), row("c", { scope: "head_to_head", horizon_days: 3 }), row("d", { state: "closed" })], "all");
  assert.deepEqual([...holds.keys()], [1, 5]);
});

test("the prediction behind a trade id, and the full story link's hash round trip", async () => {
  const { predictionIdOf, storyHash, parseStoryHash } = await import("../portfolio-v3.ts");
  assert.equal(predictionIdOf(row("acc:ai.news_results.sonnet.v1:2026-10-09-LT-5d")), "ai.news_results.sonnet.v1:2026-10-09-LT-5d");
  assert.equal(predictionIdOf(row("h2h:best_expected_gain:ai.news_results.sonnet.v1:2026-10-09-LT-5d", { scope: "head_to_head" })), "ai.news_results.sonnet.v1:2026-10-09-LT-5d");
  assert.equal(predictionIdOf(row("pt-1", { scope: "mine" })), null);
  const r = row("acc:ai.x:2026-10-09-M&M-1d");
  assert.deepEqual(parseStoryHash(storyHash(r)), { prediction: "ai.x:2026-10-09-M&M-1d", trade: "acc:ai.x:2026-10-09-M&M-1d" });
});

test("one-decimal percents round halves away from zero, with a true minus and no sign on zero", async () => {
  const { pct1 } = await import("../portfolio-v3.ts");
  assert.equal(pct1(-1.0 * 1.45), "−1.5%");
  assert.equal(pct1(1.45), "+1.5%");
  assert.equal(pct1(-0.04), "0.0%");
  assert.equal(pct1(-2.875), "−2.9%");
});

test("the market's pull is the stored one when the read model carries it (computed before rounding)", () => {
  assert.equal(openCause(check({ move_pct: -2.33, market_pct: -1.0, market_pull_pct: -1.45, beta: 1.4489, own_pct: -0.88, sector_pct: -0.84 }), "Nifty 50"),
    "Fell with the whole market (Nifty 50 −1.0%, so −1.5% for this stock); −0.9% on its own. Its sector −0.8%.");
});
