import assert from "node:assert/strict";
import { test } from "node:test";
import { moodLine, nearestLine, relyChecks, storyLine, tradesLine, tradesSoFar } from "../home.ts";

const goLive = { proven: false, months_forward: 0.2, trades_needed: 294, beats_best_baseline: null };

test("the checklist names the reference strategy, the earliest date and what is not measurable yet", () => {
  const checks = relyChecks(goLive, { drawdown_within_limit: null, holds_in_calm_and_volatile: null, earliest_date: "2026-12-12" },
    { state: "paper", why: "The backtest did not beat the baselines." });
  assert.deepEqual(checks.map((c) => [c.key, c.met]), [
    ["trades", false], ["months", false], ["baseline", null], ["drawdown", null], ["regimes", null], ["skill", false],
  ]);
  assert.equal(checks[0].detail, "6 of about 300 (the main rule strategy)");
  assert.equal(checks[1].detail, "0.2 of 2 months (earliest: 12 Dec 2026)");
  assert.equal(checks[5].detail, "No. The backtest did not beat the baselines.");
  // without the new fields (an older payload) every extra check reads "not measured"
  assert.deepEqual(relyChecks(goLive, undefined, undefined).slice(3).map((c) => c.met), [null, null, null]);
});

test("the nearest strategy is named only when it is not the reference", () => {
  const near = { ...goLive, strategy_id: "ai.combined.opus.v1", name: "Opus combined", family: "ai" as const, trades: 9,
    trades_needed: 291, drawdown_within_limit: null, holds_in_calm_and_volatile: null };
  assert.equal(nearestLine(near, "rule.model_news.v1"), "Closest to passing: Opus combined (AI trader), 9 of about 300 finished trades, 0.2 of 2 months.");
  assert.equal(nearestLine({ ...near, strategy_id: "rule.model_news.v1" }, "rule.model_news.v1"), null);
  assert.equal(nearestLine(null, "rule.model_news.v1"), null);
});

test("paper trades so far count only trades with money", () => {
  assert.deepEqual(tradesSoFar([{ net_pnl: 10 }, { net_pnl: -4 }, { net_pnl: 0 }, { net_pnl: null }]), { finished: 3, won: 1, lost: 1, net: 6 });
  assert.deepEqual(tradesSoFar([]), { finished: 0, won: 0, lost: 0, net: null });
});

test("today in 3 lines", () => {
  const companies = [{ state: "active", change_pct: 1 }, { state: "active", change_pct: -1 }, { state: "active", change_pct: 2 }, { state: "inactive", change_pct: 5 }];
  assert.equal(moodLine("CALM", { name: "Nifty 50", change_pct: 0.4, close_date: "2026-10-09" }, companies),
    "Market mood: calm. Nifty 50 moved +0.40% on Fri 9 Oct; 2 of the 3 companies you follow rose, 1 fell.");
  assert.equal(moodLine(null, null, []), "Market mood: not known yet.");
  const open = [{ entry_date: "2026-10-12", exit_date: "2026-10-13" }, { entry_date: "2026-10-09", exit_date: "2026-10-14" }];
  assert.equal(tradesLine(open, "2026-10-12"), "2 paper trades running, 1 of them opened on Mon 12 Oct; the first finishes at the close on Tue 13 Oct.");
  assert.equal(tradesLine([], "2026-10-12"), "No paper trade is running.");
  assert.equal(storyLine({ title: "RBI holds rates", status: null }), "The story that mattered: “RBI holds rates” (market-wide).");
  assert.equal(storyLine({ title: "TCS results", status: "confirmed_primary" }), "The story that mattered: “TCS results” (confirmed).");
  assert.equal(storyLine(undefined), "No market-moving story in the last 3 days.");
});
