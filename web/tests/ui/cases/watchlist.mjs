// UI cases of page 02, Watchlist (B14), at the mockup's widths (design/mockups/02-watchlist/shot-{1280,1024,768,390}-full.png):
// one row per active company, the agreement order, sorting, the sector chips and text filter, the horizon tabs, the
// inactive line under the table, and the flagged-check label.
import { envelope, mockupPayload } from "../fixtures.mjs";

const tickers = (page) => page.locator("table.wl tbody tr.row .tk").allTextContents();

/** On the mockup's India payload: agreement order RELIANCE, MARUTI, HDFCBANK; INDIGO inactive, never a row. */
async function tableChecks(page) {
  const problems = [];
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  let t = await tickers(page);
  if (!same(t, ["RELIANCE", "MARUTI", "HDFCBANK"])) problems.push(`agreement order ${t}`);
  await page.getByRole("button", { name: "Sort by company" }).click();
  t = await tickers(page);
  if (!same(t, ["HDFCBANK", "MARUTI", "RELIANCE"])) problems.push(`name order A-Z ${t}`);
  if ((await page.locator('table.wl th[aria-sort="ascending"]').count()) !== 1) problems.push("the sorted column has no aria-sort");
  await page.getByRole("button", { name: "Sort by company" }).click();
  t = await tickers(page);
  if (!same(t, ["RELIANCE", "MARUTI", "HDFCBANK"])) problems.push(`name order Z-A ${t}`);
  await page.getByRole("button", { name: "Banks" }).click();
  t = await tickers(page);
  if (!same(t, ["HDFCBANK"])) problems.push(`Banks chip shows ${t}`);
  await page.getByRole("button", { name: "All sectors" }).click();
  await page.getByLabel("Filter by symbol or name").fill("maru");
  t = await tickers(page);
  if (!same(t, ["MARUTI"])) problems.push(`text filter shows ${t}`);
  await page.getByLabel("Filter by symbol or name").fill("zzz");
  if (!(await page.getByText("No company matches the filter.").count())) problems.push("no empty row for an unmatched filter");
  await page.getByLabel("Filter by symbol or name").fill("");
  await page.getByRole("button", { name: "N+5" }).click();
  if (!(await page.getByText("Agreement at N+5").count())) problems.push("the horizon tab did not change the columns");
  if (!(await page.locator('[aria-label="Horizon"] [aria-pressed="true"]', { hasText: "N+5" }).count())) problems.push("N+5 not pressed");
  return problems;
}

/** A flagged check shows a warning label with its count on the company's row and in the KPI. */
const flaggedApi = (rest, market) => {
  if (rest !== "watchlist") return undefined;
  const p = mockupPayload("02-watchlist", market);
  const checks = p.trade_checks.map((c, i) => (i === 0 ? { ...c, flagged: true, flags: ["outside_range"] } : c));
  return { status: 200, body: envelope(market, "_", { ...p, trade_checks: checks }) };
};

export const cases = [
  {
    name: "watchlist-india",
    path: "/india/watchlist",
    mockup: "02-watchlist",
    widths: [1280],
    waitFor: "table.wl",
    expectText: ["No proven strong signals today", "Companies followed", "Most agreed at N+1", "12 of 15 buy", "3 of 3 companies", "Not listed: InterGlobe Aviation (IndiGo)", "manage on the Companies page"],
    expectSelector: ["table.wl tbody tr.row", ".rng svg", ".hzb svg", ".mb-agbar"],
  },
  { name: "watchlist-india-narrow", path: "/india/watchlist", mockup: "02-watchlist", widths: [1024, 768, 390], waitFor: "table.wl", expectText: ["Most agreed at N+1", "RELIANCE"] },
  { name: "watchlist-india-table", path: "/india/watchlist", mockup: "02-watchlist", widths: [1440], waitFor: "table.wl", check: tableChecks },
  { name: "watchlist-us", path: "/us/watchlist", market: "us", mockup: "02-watchlist", widths: [1280], waitFor: "table.wl", expectText: ["NVDA", "14 of 15 buy", "No check yet", "first intraday check pending"] },
  { name: "watchlist-flagged", path: "/india/watchlist", mockup: "02-watchlist", widths: [1280], waitFor: "table.wl", api: flaggedApi, expectText: ["Flagged today", "1 of 4"], expectSelector: ["table.wl .mb-label.warn"] },
];
