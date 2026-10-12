// UI cases of page 01, Home (B14), at the mockup's widths (design/mockups/01-home/shot-{1280,1024,768,390}-full.png):
// the agreement list and its horizon tabs, the head-to-head picks with their cost labels, Rule vs AI (chart, last
// close, to date), alerts, the top 5 market movers, the runs, the open trades, and the empty states.
import { envelope, mockupPayload } from "../fixtures.mjs";

/** The agreement list follows the horizon tabs; the movers card shows at most 5 stories. */
async function homeChecks(page) {
  const problems = [];
  const first = () => page.locator(".agl li .tk").first().textContent();
  if ((await first()) !== "RELIANCE") problems.push(`N+1 leader ${await first()}`);
  await page.locator('[aria-label="Horizon"] button', { hasText: "5 days" }).click();
  if (!(await page.getByText("Which companies most strategies would buy · 5-day hold").count())) problems.push("the horizon tab did not change the agreement card");
  if (!(await page.getByText("Most strategies like (5-day hold)").count())) problems.push("the horizon tab did not change the KPI");
  const movers = await page.locator('section[aria-label="News"] .nl li').count();
  if (movers < 1 || movers > 5) problems.push(`Home shows ${movers} movers (expected 1..5)`);
  if ((await page.locator('section[aria-label="News"] a[target="_blank"]:not([rel~="noopener"])').count())) problems.push("article links without rel=noopener");
  const chartHits = await page.locator('section[aria-label="Rule vs AI"] svg').count();
  if (!chartHits) problems.push("no profit chart");
  await page.locator("details.cand summary").first().click();
  if (!(await page.locator("details.cand[open] table tbody tr").count())) problems.push("the candidates table does not open");
  return problems;
}

const emptyHome = (rest, market) => {
  if (rest !== "home") return undefined;
  const p = mockupPayload("01-home", market);
  return {
    status: 200,
    body: envelope(market, "_", { ...p, agreement: Object.fromEntries(Object.keys(p.agreement).map((k) => [k, []])), head_to_head: [], open_trades: [], trade_checks: [], eod: null, to_date: [], news: [], settled_trades: [] }),
  };
};

const flaggedHome = (rest, market) => {
  if (rest !== "home") return undefined;
  const p = mockupPayload("01-home", market);
  return { status: 200, body: envelope(market, "_", { ...p, trade_checks: p.trade_checks.map((c, i) => (i < 2 ? { ...c, flagged: true, flags: ["outside_range"] } : c)) }) };
};

/** Home with the "Can I rely on this yet?" fields (review D1-D4): the checklist, the nearest strategy, the review's
 *  verdict and the next intraday check time. */
const relyHome = (rest, market) => {
  if (rest !== "home") return undefined;
  const p = mockupPayload("01-home", market);
  return {
    status: 200,
    body: envelope(market, "_", {
      ...p, trade_checks: [], status: { ...p.status, runs: { ...p.status.runs, intraday: [] } },
      go_live_checks: { drawdown_within_limit: true, holds_in_calm_and_volatile: null, earliest_date: "2026-12-12" },
      go_live_nearest: { strategy_id: "ai.combined.opus.v1", name: "AI combined (Opus)", family: "ai", trades: 9, proven: false, months_forward: 0.2, trades_needed: 291, beats_best_baseline: null, drawdown_within_limit: true, holds_in_calm_and_volatile: null },
      skill: { state: "paper", why: "The backtest did not beat the baselines after costs." },
      intraday_next_at: "2026-10-08T05:43:00Z",
    }),
  };
};

export const cases = [
  {
    name: "home-india",
    path: "/india",
    mockup: "01-home",
    widths: [1280],
    waitFor: ".agl",
    expectText: ["Wednesday 7 Oct 2026", "Can I rely on this yet?", "NOT YET", "Today in 3 lines", "Which companies most strategies would buy · 1-day hold", "12 of 15", "Today’s test trades: rule vs AI", "Rule vs AI", "Last close", "Rule vs AI so far", "Market movers · last 3 days", "Runs today", "Open paper trades", "expected to beat market fees"],
    expectSelector: [".agl li.top", ".h2h .cmp", ".fam-box .pk", ".lastclose .t", ".grid22 .cell", ".nl li", ".runs li", "table.mb-ot"],
  },
  { name: "home-india-narrow", path: "/india", mockup: "01-home", widths: [1024, 768, 390], waitFor: ".agl", expectText: ["Which companies most strategies would buy · 1-day hold", "Runs today"] },
  { name: "home-india-interactions", path: "/india", mockup: "01-home", widths: [1280], waitFor: ".agl", check: homeChecks },
  { name: "home-us", path: "/us", market: "us", mockup: "01-home", widths: [1280], waitFor: ".agl", expectText: ["NVDA", "14 of 15", "No intraday check stored yet today"] },
  {
    name: "home-rely",
    path: "/india",
    mockup: "01-home",
    widths: [1280, 390],
    waitFor: ".rely-checks",
    api: relyHome,
    expectText: ["Can I rely on this yet?", "NOT YET", "earliest: 12 Dec 2026", "Closest to passing: AI combined (Opus) (AI trader), 9 of about 300 finished trades",
      "No. The backtest did not beat the baselines after costs.", "next check around 8 Oct 11:13 IST", "Today in 3 lines", "See all paper trades"],
    expectSelector: ['.rely-checks li .mb-mark.ok', '.rely-checks li .mb-mark.na', '.today ol li', 'a[href$="/help#why-no-buy-sell"]'],
  },
  { name: "home-flagged", path: "/india", mockup: "01-home", widths: [1280], waitFor: ".agl", api: flaggedHome, expectText: ["2 flagged", "outside its range"], expectSelector: [".al li"] },
  {
    name: "home-empty",
    path: "/india",
    mockup: "01-home",
    widths: [1280, 390],
    waitFor: ".phead",
    api: emptyHome,
    expectText: ["No strategy would buy any company for a 1-day hold today.", "No rule-vs-AI picks for today’s session yet.", "No paper trade has finished yet.", "The after-close write-up appears after the first trades finish", "No intraday check stored yet today.", "No market-moving story in the last 3 days", "No open paper trade."],
  },
];
