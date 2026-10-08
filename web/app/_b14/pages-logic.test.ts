// Watchlist, Home and Companies computations, on small cases and on the approved mockups' example payloads.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { filterRows, mostAgreed, sectorsOf, sortRows, watchlistRows, horizonWords, distinctFlags } from "./watchlist-logic.ts";
import { cumulativeProfit, eodLeaders, expectedGainMoney, groupBy, niceStep, pickSummary, runsOk, viableLine, type HeadToHeadPick } from "./home-logic.ts";
import { cleanReason, commandArguments, companiesCounts, deactivation, deleteConfirmed, onboardingWords, parseAmount } from "./companies-logic.ts";

const mockup = (page: string) => JSON.parse(readFileSync(new URL(`../../../design/mockups/${page}/data.json`, import.meta.url), "utf8").replace(/\bNaN\b/g, "null"));

const fam = (buy: number, of: number) => ({ buy, of });
const agree = (ticker: string, buy: number, prob: number | null) => ({ ticker, rank: 1, horizon_days: 1, buy, of: 15, by_family: { rule: fam(buy, 8), baseline: fam(0, 3), ai: fam(0, 4) }, avg_prob_up: prob });
const co = (ticker: string, name: string, sector: string, state = "active", change_pct: number | null = 0) => ({ ticker, name, sector, state, last_close: 10, change_pct });

test("watchlist rows: active only, agreement and range at the horizon, open trades and flags summed", () => {
  const p = {
    companies: [co("A", "Alpha", "IT"), co("B", "Beta", "Banks"), co("Z", "Zed", "IT", "inactive")],
    agreement: { "1": [agree("A", 3, 0.6), agree("B", 3, 0.7)], "2": [agree("A", 5, null)] },
    ranges: [{ ticker: "A", horizon_days: 1 }, { ticker: "A", horizon_days: 2 }],
    open_trades: [{ trade_id: "t1", ticker: "A", unrealised_pnl: 5 }, { trade_id: "t2", ticker: "A", unrealised_pnl: null }],
    trade_checks: [{ trade_id: "t1", ticker: "A", check_at: "x", flagged: true, flags: ["outside_range", "far_from_target"] }, { trade_id: "t2", ticker: "A", check_at: "x", flagged: true, flags: ["outside_range"] }],
  };
  const rows = watchlistRows(p, 1);
  assert.deepEqual(rows.map((r) => [r.company.ticker, r.agreement?.buy, r.range?.horizon_days, r.trades.length, r.unrealised, r.flagged.length]), [["A", 3, 1, 2, 5, 2], ["B", 3, undefined, 0, 0, 0]]);
  assert.equal(mostAgreed(rows)?.company.ticker, "B");
  assert.deepEqual(sortRows(rows, "name", 1).map((r) => r.company.ticker), ["A", "B"]);
  assert.deepEqual(sortRows(rows, "open", -1).map((r) => r.company.ticker), ["A", "B"]);
  assert.deepEqual(filterRows(rows, "Banks", "").map((r) => r.company.ticker), ["B"]);
  assert.deepEqual(filterRows(rows, null, "alp").map((r) => r.company.ticker), ["A"]);
  assert.deepEqual(sectorsOf(rows), [{ sector: "Banks", count: 1 }, { sector: "IT", count: 1 }]);
  assert.deepEqual(distinctFlags(rows[0].flagged), ["outside_range", "far_from_target"]);
  assert.equal(mostAgreed(watchlistRows({ ...p, agreement: {} }, 1)), null);
  assert.equal(horizonWords(1), "the next session’s close");
  assert.equal(horizonWords(3), "the close of the 3rd session after the open");
});

test("home: pick summary, money gain, grouping, profit series, leaders and runs", () => {
  const pick = (id: string, ticker: string, gain: number | null, viable: boolean | null, status = "picked"): HeadToHeadPick => ({ id, ticker, family: "rule", pick_rule: "best_expected_gain", status, strategy_id: "s", horizon_days: 2, expected_gain_pct: gain, amount: 1000, candidates: [{ horizon_days: 2, prob_up: 0.6, move_pct: 1, loss_pct: 1, costs_pct: 0.1, expected_gain_pct: gain, cost_viable: viable }] });
  const picks = [pick("1", "A", 0.5, false), pick("2", "A", -0.1, null), pick("3", "B", 0.2, true), pick("4", "C", null, null, "no_candidate")];
  const s = pickSummary(picks);
  assert.deepEqual(s, { picked: 3, clearMarket: 2, viableYours: 1, yourKnown: 2 });
  assert.equal(viableLine(s), "2 clear market costs · 1 viable at your cost");
  assert.equal(viableLine({ picked: 1, clearMarket: 1, viableYours: 0, yourKnown: 0 }), "1 clears market costs · your-cost view not stored");
  assert.equal(expectedGainMoney(picks[0]), 5);
  assert.deepEqual(groupBy(picks, (k) => k.ticker).map(([t, ks]) => [t, ks.length]), [["A", 2], ["B", 1], ["C", 1]]);
  const series = cumulativeProfit([
    { view: "accuracy", family: "rule", exit_date_actual: "2026-10-02", net_pnl: 10 },
    { view: "accuracy", family: "rule", exit_date_actual: "2026-10-01", net_pnl: -4 },
    { view: "accuracy", family: "ai", exit_date_actual: "2026-10-02", net_pnl: 3 },
    { view: "head_to_head", family: "ai", exit_date_actual: "2026-10-02", net_pnl: 100 },
    { view: "accuracy", family: "ai", exit_date_actual: null, net_pnl: null },
  ]);
  assert.deepEqual(series.days, ["2026-10-01", "2026-10-02"]);
  assert.deepEqual(series.series.map((x) => [x.family, x.points]), [["rule", [-4, 6]], ["ai", [0, 3]], ["baseline", [0, 0]]]);
  assert.equal(series.trades, 3);
  assert.deepEqual([niceStep(400), niceStep(9), niceStep(0)], [100, 5, 1]);
  assert.deepEqual([...eodLeaders({ rule: { trades: 2, wins: 1, net_pnl: 5 }, ai: { trades: 1, wins: 1, net_pnl: 9 }, baseline: { trades: 0, wins: 0, net_pnl: 50 } })], ["ai"]);
  const run = (ok: boolean | null) => ({ at: ok == null ? null : "t", ok });
  assert.deepEqual(runsOk({ pre_open: run(true), intraday: [run(true)], post_close: run(null), news: run(false) }), { ok: 2, total: 5 });
});

test("companies: counts, deactivation, arguments, onboarding words, confirmations", () => {
  const cos = [{ ticker: "A", name: "A", state: "active", amount_overridden: true }, { ticker: "B", name: "B", state: "active" }, { ticker: "C", name: "C", state: "inactive" }];
  const cmd = (result: string, args: Record<string, unknown> | null) => ({ id: "c", tool: "add_company", result, arguments: args, record_ids: [], refusal_code: null });
  assert.deepEqual(companiesCounts(cos, [cmd("pending", null), cmd("accepted", null)], 1), { active: 2, inactive: 1, custom: 1, pending: 2 });
  const ev = (id: string, event: string, ticker: string, channel = "dashboard") => ({ id, event, ticker, recorded_at: "t", effective_from: "t", channel, requested_by: "owner", reason: null, amount: null, onboarding: { identifiers: "ok", not_etf: "ok" } });
  assert.equal(deactivation([ev("2", "deactivate", "C"), ev("1", "deactivate", "C")], "C")?.id, "2");
  assert.equal(deactivation([ev("1", "add", "C")], "C"), null);
  assert.equal(commandArguments(cmd("accepted", { market: "us", symbol: "AMZN" })), "symbol AMZN");
  assert.equal(commandArguments(cmd("accepted", { market: "us" })), "add_company");
  assert.equal(onboardingWords(ev("1", "add", "A")), "identifiers ok, not etf ok");
  assert.equal(onboardingWords(ev("1", "add", "A", "seed")), null);
  assert.ok(deleteConfirmed(" tcs ", "TCS"));
  assert.ok(!deleteConfirmed("TC", "TCS"));
  assert.deepEqual(["1000", "0", "-5", "12.5", "1e3", ""].map(parseAmount), [1000, null, null, 12.5, null, null]);
  assert.equal(cleanReason(` ${"x".repeat(250)} `).length, 200);
});

test("the mockups' payloads: every page's computations run on both markets", () => {
  const wl = mockup("02-watchlist"), home = mockup("01-home"), cos = mockup("10-companies");
  for (const m of ["india", "us"]) {
    const p = wl.markets[m];
    const rows = watchlistRows(p, p.default_horizon);
    assert.equal(rows.length, p.companies.filter((c: { state: string }) => c.state === "active").length);
    const h = home.markets[m];
    assert.ok(pickSummary(h.head_to_head).picked <= h.head_to_head.length);
    assert.ok(runsOk(h.status.runs).ok <= 5);
    assert.ok(cumulativeProfit(h.settled_trades).days.length > 0);
    const c = cos.markets[m];
    assert.equal(companiesCounts(c.companies, c.commands).active + companiesCounts(c.companies, c.commands).inactive, c.companies.length);
  }
});
