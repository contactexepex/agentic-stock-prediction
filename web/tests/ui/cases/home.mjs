// UI cases of page 01, Home (B14), at the mockup's widths (design/mockups/01-home/shot-{1280,1024,768,390}-full.png):
// the agreement list and its horizon tabs, the head-to-head picks with their cost labels, Rule vs AI (chart, last
// close, to date), alerts, the top 5 market movers, the runs, the open trades, and the empty states.
import { envelope, mockupPayload } from "../fixtures.mjs";

/** The agreement list follows the horizon tabs; the movers card shows at most 5 stories. */
async function homeChecks(page) {
  const problems = [];
  const first = () => page.locator(".agl li .tk").first().textContent();
  if ((await first()) !== "RELIANCE") problems.push(`N+1 leader ${await first()}`);
  await page.locator('[aria-label="Horizon"] button', { hasText: "N+5" }).click();
  if (!(await page.getByText("Who agrees at N+5").count())) problems.push("the horizon tab did not change the agreement card");
  if (!(await page.getByText("Most agreed at N+5").count())) problems.push("the horizon tab did not change the KPI");
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

export const cases = [
  {
    name: "home-india",
    path: "/india",
    mockup: "01-home",
    widths: [1280],
    waitFor: ".agl",
    expectText: ["Wednesday 7 Oct 2026", "No proven strong signals today", "Who agrees at N+1", "12 of 15", "Today’s head-to-head trades", "Rule vs AI", "Last close", "Head-to-head to date", "Market movers · last 3 days", "Runs today", "Open paper trades", "clears market costs"],
    expectSelector: [".agl li.top", ".h2h .cmp", ".fam-box .pk", ".lastclose .t", ".grid22 .cell", ".nl li", ".runs li", "table.mb-ot"],
  },
  { name: "home-india-narrow", path: "/india", mockup: "01-home", widths: [1024, 768, 390], waitFor: ".agl", expectText: ["Who agrees at N+1", "Runs today"] },
  { name: "home-india-interactions", path: "/india", mockup: "01-home", widths: [1280], waitFor: ".agl", check: homeChecks },
  { name: "home-us", path: "/us", market: "us", mockup: "01-home", widths: [1280], waitFor: ".agl", expectText: ["NVDA", "14 of 15", "No intraday check stored yet today"] },
  { name: "home-flagged", path: "/india", mockup: "01-home", widths: [1280], waitFor: ".agl", api: flaggedHome, expectText: ["2 flagged", "outside its range"], expectSelector: [".al li"] },
  {
    name: "home-empty",
    path: "/india",
    mockup: "01-home",
    widths: [1280, 390],
    waitFor: ".phead",
    api: emptyHome,
    expectText: ["No strategy buys any company at N+1 today.", "No head-to-head picks stored for today’s session yet.", "No settled paper trade yet", "No end-of-day analysis stored yet.", "No intraday check stored yet today.", "No market-moving story in the last 3 days", "No open paper trade."],
  },
];
