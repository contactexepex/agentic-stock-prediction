// UI cases of the company pages (B15): 03-company at the mockup's widths for every example company of both markets,
// its empty and error states, and the keyboard path through the horizon tabs and the price chart. The 03 mockup's
// data.json holds one payload per company under `pages`; `companyApi` answers GET .../stocks/{ticker} with the
// market's shared keys plus that company's page, which is what B12's endpoint serves (tests/test_api_contract.py).
import { mockupPayload } from "../fixtures.mjs";

const PAPER = "No proven strong signals today";

export function companyPayload(market, ticker) {
  const m = mockupPayload("03-company", market);
  if (!m || !m.pages?.[ticker]) return null;
  const { pages, default_ticker, ...shared } = m;
  return { ...shared, ...pages[ticker] };
}

/** Answer the company endpoint from the mockup; `edit` may change the payload (empty states). */
export const companyApi = (edit = (p) => p) => (rest, market) => {
  const hit = /^stocks\/([A-Z0-9.&-]{1,20})$/.exec(rest);
  if (!hit) return undefined;
  const p = companyPayload(market, hit[1]);
  return p ? { status: 200, body: envelopeOf(market, hit[1], edit(structuredClone(p))) } : { status: 404, body: { title: "Not found", status: 404, detail: "No stored page for this company." } };
};

function envelopeOf(market, key, payload) {
  return { market, page_key: key, as_of: payload.as_of ?? null, cutoff: payload.cutoff, built_at: payload.built_at, schema_version: "2.0.0", source_commit: "fixture", payload_sha256: "fixture", payload };
}

/** Tables wider than their scrolling wrapper (the mockups fit every table at every width; the closed "why these
 *  horizons" table opens as a scrolling table, as in the 04 mockup), named by their label. */
async function wideTables(page) {
  const wide = await page.$$eval(".md-table-wrap", (ws) => ws.filter((w) => w.offsetParent && !w.closest("details:not([open])") && w.scrollWidth > w.clientWidth + 1).map((w) => `${w.querySelector("table")?.getAttribute("aria-label") ?? w.querySelector("table")?.className} ${w.scrollWidth}>${w.clientWidth}`));
  return wide.map((w) => `table wider than its wrapper: ${w}`);
}

const SECTIONS = ["at a glance", "Price with today’s targets and ranges", "Today’s path: open paper trades", "Settled results and why each moved", "In words: the end-of-day analyst", "News with its status", "Latest results", "Coming up", "On the watchlist"];

/** Every section present, the chart drawn with its candles, every chart and table text inside its box. */
async function companyChecks(page) {
  const problems = [];
  const text = await page.textContent("main");
  for (const s of SECTIONS) if (!text.includes(s)) problems.push(`section missing: ${s}`);
  if (text.includes("null") || text.includes("undefined") || text.includes("NaN")) problems.push("a null, undefined or NaN shows on the page");
  const candles = await page.$$eval(".chart .c", (c) => c.length);
  if (!candles) problems.push("no candles drawn");
  problems.push(...(await wideTables(page)));
  const clipped = await page.$$eval(".chart svg text", (ts) => {
    const svg = ts[0]?.ownerSVGElement?.getBoundingClientRect();
    return svg ? ts.filter((t) => { const r = t.getBoundingClientRect(); return r.width && (r.left < svg.left - 1 || r.right > svg.right + 1); }).length : 0;
  });
  if (clipped) problems.push(`${clipped} chart text(s) outside the chart`);
  return problems;
}

const company = (name, market, ticker, widths, extra = {}) => ({
  name, path: `/${market}/stocks/${ticker}`, market, mockup: "03-company", widths, waitFor: ".chart svg", api: companyApi(),
  expectText: [PAPER, ticker], check: companyChecks, ...extra,
});

export const cases = [
  company("company-reliance", "india", "RELIANCE", [1280, 1024, 390]),
  company("company-nvda", "us", "NVDA", [1280]),
  company("company-hdfcbank", "india", "HDFCBANK", [1280, 390], { expectText: [PAPER, "Latest results"] }),
  company("company-maruti", "india", "MARUTI", [1280], { expectText: [PAPER, "could not become trades"] }),
  company("company-aapl", "us", "AAPL", [1280, 390]),
  company("company-jpm", "us", "JPM", [1280]),
  {
    name: "company-empty",
    path: "/india/stocks/RELIANCE",
    widths: [1280, 390],
    waitFor: ".phead",
    api: companyApi((p) => ({ ...p, predictions: [], head_to_head: [], open_trades: [], trade_checks: [], settled: [], reasons: [], news: [], results: [], events: [], lifecycle: [], agreement: {}, bars: p.bars })),
    expectText: [PAPER, "No open paper trade on this company.", "No settled paper trade yet.", "No analyst note", "No results digest", "Nothing scheduled.", "No prediction stored for this company today."],
  },
  {
    name: "company-no-bars",
    path: "/india/stocks/RELIANCE",
    widths: [1280],
    waitFor: ".phead",
    api: companyApi((p) => ({ ...p, bars: [] })),
    expectText: ["No stored price for this company yet."],
  },
  { name: "company-unknown-ticker", path: "/india/stocks/ZZZZ", widths: [1280], waitFor: '[role="alert"]', api: companyApi(), allowConsole: [/status of 404/], expectText: ["Not found"] },
  { name: "company-503", path: "/india/stocks/RELIANCE", apiStatus: 503, widths: [1280], waitFor: '[role="alert"]', allowConsole: [/status of 503/], expectText: ["Data service unavailable", "Try again"] },
  {
    name: "company-keyboard",
    path: "/india/stocks/RELIANCE",
    widths: [1280],
    waitFor: ".chart svg",
    api: companyApi(),
    check: async (page) => {
      const problems = [];
      const exitLine = () => page.$eval(".chart .vl.on", (l) => l.getAttribute("x1")).catch(() => null);
      const before = await exitLine();
      await page.click('[aria-label="Horizon"] button:has-text("N+3")');
      const after = await exitLine();
      if (!before || before === after) problems.push("the N+3 tab did not move the chart's exit line");
      if (!(await page.textContent(".dec")).includes("Published range at N+3")) problems.push("the range cell did not follow the tab");
      await page.focus(".chart svg");
      await page.keyboard.press("ArrowLeft");
      if (!(await page.$(".ctip.on"))) problems.push("ArrowLeft on the chart did not show a day");
      await page.keyboard.press("Escape");
      if (await page.$(".ctip.on")) problems.push("Escape did not clear the chart reading");
      return problems;
    },
  },
];

// ---------- 04 stock strategies (the mockup's data.json is flat per market: the default fixture serves it) ----------

async function strategiesChecks(page) {
  const problems = [];
  const text = await page.textContent("main");
  for (const s of ["Who agrees, by horizon", "Today’s head-to-head picks", "Every strategy on", "Best on this company", "Best overall"]) if (!text.includes(s)) problems.push(`section missing: ${s}`);
  if (/\bnull\b|undefined|NaN/.test(text)) problems.push("a null, undefined or NaN shows on the page");
  const rows = await page.$$eval(".rk tbody tr", (r) => r.length);
  if (rows !== 15) problems.push(`ranked table has ${rows} rows, not the 15 strategies`);
  problems.push(...(await wideTables(page)));
  return problems;
}

cases.push(
  { name: "strategies-reliance", path: "/india/stocks/RELIANCE/strategies", mockup: "04-stock-strategies", widths: [1680, 1280, 1024, 390], waitFor: ".agc svg", expectText: [PAPER, "RELIANCE"], check: strategiesChecks },
  { name: "strategies-nvda", path: "/us/stocks/NVDA/strategies", market: "us", mockup: "04-stock-strategies", widths: [1280], waitFor: ".agc svg", expectText: [PAPER, "NVDA"], check: strategiesChecks },
  {
    name: "strategies-keyboard",
    path: "/india/stocks/RELIANCE/strategies",
    widths: [1280],
    waitFor: ".agc svg",
    check: async (page) => {
      const problems = [];
      await page.focus(".agc rect.hit >> nth=2");
      await page.keyboard.press("Enter");
      const head = await page.textContent(".rk thead");
      if (!head.includes("Today at N+3")) problems.push("Enter on the N+3 bar did not select N+3 in the ranking");
      const pressed = await page.$$eval('[aria-label="Horizon"] button[aria-pressed="true"]', (b) => b.map((x) => x.textContent));
      if (!pressed.every((t) => t === "N+3")) problems.push(`horizon tabs not in step: ${pressed.join(",")}`);
      return problems;
    },
  },
  {
    name: "strategies-empty",
    path: "/india/stocks/RELIANCE/strategies",
    widths: [1280, 390],
    waitFor: ".phead",
    api: (rest, market) => {
      if (rest !== "stocks/RELIANCE/strategies") return undefined;
      const p = mockupPayload("04-stock-strategies", market);
      return { status: 200, body: envelopeOf(market, "RELIANCE", { ...p, head_to_head: [], predictions: [], on_company: [], overall: [], agreement: {} }) };
    },
    expectText: ["No head-to-head picks stored", "None yet", "no trades yet", "No agreement row for this horizon."],
  },
);

// ---------- the call history of one session (no mockup: built from 03's parts) ----------
// The 03 mockup holds settled and open trades of the predictions made for 30 Sep (RELIANCE); this fixture is that
// session's page as rm.lifecycle serves it: those predictions (their ids, horizons, chances and ranges), their checks,
// settlements and notes.
const LIFECYCLE_DAY = "2026-09-30";
function lifecyclePayload(market, ticker) {
  const c = companyPayload(market, ticker);
  const seen = new Map();
  for (const t of [...c.open_trades, ...c.settled]) {
    if (seen.has(t.prediction_id) || t.entry_date !== LIFECYCLE_DAY) continue;
    seen.set(t.prediction_id, { id: t.prediction_id, strategy_id: t.strategy_id, family: t.family, ticker, made_at: "2026-09-30T02:10:00Z", as_of_date: "2026-09-29", session_date: LIFECYCLE_DAY, exit_date: t.exit_date, horizon_days: t.horizon_days, direction: "up", prob_up: t.prob_up ?? null, qualifies: true, target_price: t.target_price, lo50: t.lo50 ?? null, hi50: t.hi50 ?? null, lo80: t.lo80, hi80: t.hi80 });
  }
  const ids = new Set(seen.keys());
  const trades = new Set([...c.settled, ...c.open_trades].filter((t) => ids.has(t.prediction_id)).map((t) => t.trade_id));
  return { market, ticker, session_date: LIFECYCLE_DAY, predictions: [...seen.values()], head_to_head: [], trade_checks: c.trade_checks.filter((x) => ids.has(x.prediction_id)), settled: c.settled.filter((t) => ids.has(t.prediction_id)), reasons: c.reasons.filter((r) => trades.has(r.trade_id)) };
}
const lifecycleApi = (edit = (p) => p) => (rest, market) => {
  const hit = /^stocks\/([A-Z0-9.&-]{1,20})\/lifecycle\/(.+)$/.exec(rest);
  if (!hit) return companyApi()(rest, market);
  if (hit[2] !== LIFECYCLE_DAY) return { status: 404, body: { title: "Not found", status: 404, detail: "No page for that session." } };
  return { status: 200, body: envelopeOf(market, `${hit[1]}:${hit[2]}`, edit(lifecyclePayload(market, hit[1]))) };
};

cases.push(
  {
    name: "lifecycle-reliance",
    path: `/india/stocks/RELIANCE/lifecycle/${LIFECYCLE_DAY}`,
    widths: [1280, 390],
    waitFor: ".lcy",
    api: lifecycleApi(),
    expectText: [PAPER, "calls for Wed 30 Sep", "The calls made for", "Checked during the holding window", "Settled results and why each moved", "In words: the end-of-day analyst"],
    check: async (page) => {
      const problems = [];
      const text = await page.textContent("main");
      if (/\bnull\b|undefined|NaN/.test(text)) problems.push("a null, undefined or NaN shows on the page");
      if (!(await page.$$eval(".path .step.on", (s) => s.length))) problems.push("no path step drawn");
      problems.push(...(await wideTables(page)));
      return problems;
    },
  },
  { name: "lifecycle-old-day", path: "/india/stocks/RELIANCE/lifecycle/2026-01-05", widths: [1280], waitFor: '[role="alert"]', api: lifecycleApi(), allowConsole: [/status of 404/], expectText: ["the history keeps the last 30 sessions"] },
  {
    name: "lifecycle-empty",
    path: `/india/stocks/RELIANCE/lifecycle/${LIFECYCLE_DAY}`,
    widths: [1280],
    waitFor: ".phead",
    api: lifecycleApi((p) => ({ ...p, predictions: [], head_to_head: [], trade_checks: [], settled: [], reasons: [] })),
    expectText: ["No prediction was made for this session", "No head-to-head pick stored", "No intraday check of these trades", "No settled paper trade yet.", "No analyst note"],
  },
);

// ---------- the watchlist actions (preview, confirm, pending) through B11's command routes ----------
const commandsApi = (previewStatus = 200) => (rest, market) => {
  if (rest === "companies/preview") {
    return previewStatus === 200
      ? { status: 200, body: { tool: "deactivate_company", summary: "Deactivate RELIANCE (Reliance Industries) in India: no new predictions or paper trades; open trades still settle.", preview: null, arguments: { ticker: "RELIANCE" }, paper: true } }
      : { status: previewStatus, body: { command_id: "c1", result: "refused", refusal_code: "validation_failed", message: "RELIANCE is already inactive", inbox_id: null, record_ids: [], budget_left: 9, paper: true } };
  }
  if (rest === "companies/commands") return { status: 202, body: { command_id: "c2", result: "pending", refusal_code: null, message: null, inbox_id: "6f1c2a7e-0000-4000-8000-000000000001", record_ids: [], budget_left: 8, paper: true } };
  return companyApi()(rest, market);
};

cases.push(
  {
    name: "company-deactivate",
    path: "/india/stocks/RELIANCE",
    widths: [1280, 390],
    waitFor: ".chart svg",
    api: commandsApi(),
    check: async (page) => {
      const problems = [];
      await page.click('.cohead button:has-text("Deactivate")');
      if (!(await page.isVisible("dialog[open]"))) return ["the Deactivate button did not open the dialog"];
      await page.click('dialog[open] button:has-text("Review")');
      await page.waitForSelector('dialog[open] button:has-text("Record deactivation")', { timeout: 3000 }).catch(() => problems.push("no Record button after the preview"));
      if (!(await page.textContent("dialog[open]")).includes("Deactivate RELIANCE (Reliance Industries)")) problems.push("the server's summary is not shown");
      await page.click('dialog[open] button:has-text("Record deactivation")');
      await page.waitForSelector(".pend .mb-alert", { timeout: 3000 }).catch(() => problems.push("no pending line after Confirm"));
      if (await page.isVisible("dialog[open]")) problems.push("the dialog stayed open after the request was recorded");
      const pend = await page.textContent(".pend").catch(() => "");
      if (!pend.includes("Pending: deactivate (pending, request 6f1c2a7e)")) problems.push(`pending line reads: ${pend}`);
      return problems;
    },
  },
  {
    name: "company-amount-refused",
    path: "/india/stocks/RELIANCE",
    widths: [1280],
    waitFor: ".chart svg",
    api: commandsApi(422),
    allowConsole: [/status of 422/],
    check: async (page) => {
      const problems = [];
      await page.click('.cohead button:has-text("Change amount")');
      await page.fill("dialog[open] input", "150000");
      await page.click('dialog[open] button:has-text("Review")');
      await page.waitForSelector('dialog[open] [role="alert"]', { timeout: 3000 }).catch(() => problems.push("no refusal shown"));
      const text = await page.textContent("dialog[open]");
      if (!text.includes("Nothing was recorded") || !text.includes("RELIANCE is already inactive")) problems.push("the refusal does not say why or that nothing was recorded");
      await page.keyboard.press("Escape");
      if (await page.isVisible("dialog[open]")) problems.push("Escape did not close the dialog");
      if (await page.$(".pend .mb-alert")) problems.push("a refused request shows as pending");
      return problems;
    },
  },
);
