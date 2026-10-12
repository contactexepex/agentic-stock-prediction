// UI cases of page 07, Paper portfolios (B16), at the mockup's widths (design/mockups/07-paper-portfolios/shot-*-full.png):
// the mockup's data (India with open trades and checks; US with the euro view), the stored data of today, the
// filters, the add-trade form against POST /paper-trades (pending, a refusal, a retry with the same key), and the
// error state. The POST is answered in the test; nothing reaches any inbox.
import { storedApi } from "../b16/stored.mjs";
import { readFileSync } from "node:fs";
import { envelope, mockupPayload } from "../fixtures.mjs";

/** B13's sample all_trades block (judged build/b13-all-trades 83887948, from tests/test_b13_all_trades.py's fixture): the
 * part B13 sent (its summary trimmed to family all and mine, its trades trimmed to 5 rows, so the head-to-head summary
 * has no trade behind it in the list), the not-entered row's prices nulled by B13 as in real data; on the US mockup page. */
const SAMPLE = JSON.parse(readFileSync(new URL("../b16/all-trades-sample-us.json", import.meta.url), "utf8"));
function withSample(rest, market) {
  if (rest !== "portfolios") return undefined;
  return { status: 200, body: envelope(market, "_", { ...mockupPayload("07-paper-portfolios", market), all_trades: SAMPLE }) };
}

const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of (422|503)/;
const PAPER = "Not proven yet: these are tests, not tips.";

/** Answer POST /paper-trades with the given statuses in turn; returns the requests seen. */
async function answerPosts(page, statuses) {
  const seen = [];
  await page.route("**/api/v1/markets/*/paper-trades", async (route) => {
    const req = route.request();
    seen.push({ method: req.method(), key: req.headers()["idempotency-key"], type: req.headers()["content-type"], body: req.postDataJSON() });
    const status = statuses[Math.min(seen.length - 1, statuses.length - 1)];
    const result = status === 202 ? "pending" : status === 503 ? "failed" : "refused";
    const body = { command_id: `cmd-${seen.length}`, result, refusal_code: status === 422 ? "validation_failed" : null, message: status === 422 ? "No stored bar for RELIANCE on that date" : status === 503 ? "The inbox is unavailable" : "Pending until the next import", inbox_id: status === 202 ? "inb-1" : null, record_ids: [], budget_left: 9, paper: true };
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  return seen;
}

/** The mockup with an all_trades block in B13's fields (owner request 2026-10-12): two strategy trades in the accuracy
 * view (one open, one closed lost), one head-to-head win, one that never entered, and one of your own sells. */
function withAllTrades(rest, market) {
  if (rest !== "portfolios") return undefined;
  const p = structuredClone(mockupPayload("07-paper-portfolios", market));
  const base = { view: "accuracy", pick_rule: null, horizon_days: 3, side: null, not_entered_reason: null, price_pending: false, quantity: 84, amount: 100000, currency: "INR", return_pct_market: null, return_pct_your: null, settled_at: null, paper: true, last_price_source: null, last_price_time: null, last_price_date: null, unrealised_pnl: null, unrealised_pct: null };
  const row = (over) => ({ ...base, ...over });
  const sum = (scope, family, period, over = {}) => ({ scope, family, period, open: 1, closed: 1, wins: 0, losses: 1, flat: 0, win_rate: 0, net_pnl_market: -1200, net_pnl_your: -1650, pnl_your_missing: 0, currency: "INR", ...over });
  p.all_trades = {
    window: { sessions: 10, from: "2026-09-23", to: "2026-10-06" },
    summary: [sum("all", "all", "to_date"), sum("all", "all", "window"), sum("all", "rule", "to_date"),
      sum("head_to_head", "all", "to_date", { open: 0, wins: 1, losses: 0, win_rate: 100, net_pnl_market: 1016, net_pnl_your: 575 }),
      sum("head_to_head", "all", "window", { open: 0, wins: 1, losses: 0, win_rate: 100, net_pnl_market: 1016, net_pnl_your: 575 }),
      sum("head_to_head", "ai", "to_date", { open: 0, wins: 1, losses: 0, win_rate: 100, net_pnl_market: 1016, net_pnl_your: 575 }),
      sum("mine", "mine", "to_date", { open: 0, wins: 1, losses: 0, win_rate: 100, net_pnl_market: null, net_pnl_your: 1800 }),
      sum("mine", "mine", "window", { open: 0, wins: 1, losses: 0, win_rate: 100, net_pnl_market: null, net_pnl_your: 1800 })],
    trades: [
      row({ id: "acc:rule.model_news.v1:2026-10-05-RELIANCE-3d", scope: "all", strategy_id: "rule.model_news.v1", family: "rule", ticker: "RELIANCE", entry_date: "2026-10-06", exit_date: "2026-10-09", state: "open", outcome: null, entry_price: 1182, exit_or_last_price: 1218, last_price_source: "intraday_check", last_price_time: "2026-10-07T05:43:00Z", last_price_date: "2026-10-07", pnl_market: null, pnl_your: null, unrealised_pnl: 3024, unrealised_pct: 3.05 }),
      row({ id: "acc:rule.model_news.v1:2026-09-29-HDFCBANK-3d", scope: "all", strategy_id: "rule.model_news.v1", family: "rule", ticker: "HDFCBANK", entry_date: "2026-09-30", exit_date: "2026-10-05", state: "closed", outcome: "loss", entry_price: 711.5, exit_or_last_price: 702, pnl_market: -1200, pnl_your: -1650, settled_at: "2026-10-05T12:15:00Z" }),
      row({ id: "acc:base.always_up.v1:2026-10-01-TCS-1d", scope: "all", strategy_id: "base.always_up.v1", family: "baseline", horizon_days: 1, ticker: "TCS", entry_date: "2026-10-02", exit_date: "2026-10-02", state: "not_entered", outcome: null, not_entered_reason: "no_entry", entry_price: null, exit_or_last_price: null, quantity: null, pnl_market: null, pnl_your: null }),
      row({ id: "h2h:highest_probability:ai.combined.opus.v1:2026-09-29-RELIANCE-3d", scope: "head_to_head", view: "head_to_head", strategy_id: "ai.combined.opus.v1", family: "ai", pick_rule: "highest_probability", ticker: "RELIANCE", entry_date: "2026-09-30", exit_date: "2026-10-06", state: "closed", outcome: "win", entry_price: 1182, exit_or_last_price: 1218, pnl_market: 1016, pnl_your: 575, settled_at: "2026-10-06T12:15:00Z" }),
      row({ id: "pt-india-20261006-RELIANCE-2", scope: "mine", view: null, strategy_id: null, family: "mine", horizon_days: null, side: "sell", ticker: "RELIANCE", entry_date: null, exit_date: "2026-10-06", state: "closed", outcome: "win", entry_price: 1182, exit_or_last_price: 1218, quantity: 50, amount: null, pnl_market: null, pnl_your: 1800 }),
    ],
  };
  return { status: 200, body: envelope(market, "_", p) };
}

/** Every visible list column lies inside the table's visible box (no column scrolled out of sight); fails when the
 * list has no header at all. */
const clippedHeaders = (page) => page.$$eval(".p-portfolios .at-list", (tables) => {
  if (!tables.length) return ["no trade list"];
  const wrap = tables[0].closest(".md-table-wrap").getBoundingClientRect();
  const ths = [...tables[0].querySelectorAll("th")].filter((th) => th.getBoundingClientRect().width > 0);
  if (!ths.length) return ["no visible column header"];
  return ths.filter((th) => th.getBoundingClientRect().right > wrap.right + 0.5).map((th) => `${th.textContent} ends at ${Math.round(th.getBoundingClientRect().right)}, box at ${Math.round(wrap.right)}`);
});
const press = (page, group, text) => page.click(`[aria-label="${group}"] button:has-text("${text}")`);
const listText = (page) => page.textContent('[aria-label="All paper trades"] .at-list').catch(() => "");

/** The mockup with one open trade and one all-trades row priced pending (B4: entered at D's open, no price stored or
 * checked yet; prices, quantity and unrealised figures null). The open trade carries no price_pending flag, as
 * rm.portfolio's open_trades served it at dbd85a32; the page must still say "price pending". */
function withPricePending(rest, market) {
  if (rest !== "portfolios") return undefined;
  const p = structuredClone(mockupPayload("07-paper-portfolios", market));
  Object.assign(p.open_trades[0], { entry_price: null, quantity: null, last_price: null, last_price_date: null, unrealised_pnl: null, unrealised_pct: null, to_target_pct: null });
  p.all_trades = { window: { sessions: 10, from: "2026-09-23", to: "2026-10-06" },
    summary: [{ scope: "all", family: "all", period: "to_date", open: 1, closed: 0, wins: 0, losses: 0, flat: 0, win_rate: null, net_pnl_market: null, net_pnl_your: null, pnl_your_missing: 0, currency: "INR" }],
    trades: [{ id: "acc:rule.model_news.v1:2026-10-06-RELIANCE-1d", scope: "all", view: "accuracy", strategy_id: "rule.model_news.v1", family: "rule", pick_rule: null, side: null, ticker: "RELIANCE", horizon_days: 1, entry_date: "2026-10-07", exit_date: "2026-10-07", state: "open", not_entered_reason: null, outcome: null, entry_price: null, entry_price_source: null, exit_or_last_price: null, last_price_source: null, last_price_date: null, last_price_time: null, price_pending: true, quantity: null, amount: 100000, currency: "INR", unrealised_pnl: null, unrealised_pct: null, pnl_market: null, pnl_your: null, return_pct_market: null, return_pct_your: null, settled_at: null, paper: true }] };
  return { status: 200, body: envelope(market, "_", p) };
}

/** B13's portfolio-size split (build/b13-portfolio-size d4e1cf8e): all_trades carries `sessions` and only head-to-head
 * and your own trades; the accuracy view is read per entry session from GET /portfolios/sessions/{date}. Hand-made in
 * those fields on the India mockup page: two sessions with pages (6 Oct: an open trade flagged outside its range with its
 * own range, one checked inside its 50% band, a closed loss; 5 Oct: one open trade, no check yet) and a third whose page
 * answers 503, to show the list's own error state. open_trades and trade_checks are emptied: the page must not need them. */
const SESSION_ROW = { scope: "all", view: "accuracy", family: "rule", pick_rule: null, side: null, horizon_days: 3, not_entered_reason: null, entry_price_source: "daily_bar", price_pending: false, quantity: 84, amount: 100000, currency: "INR", return_pct_market: null, return_pct_your: null, settled_at: null, paper: true, last_price_source: "daily_close", last_price_time: null, last_price_date: "2026-10-06", pnl_market: null, pnl_your: null, unrealised_pnl: null, unrealised_pct: null, lo80: null, lo50: null, hi50: null, hi80: null, target_price: null, to_target_pct: null, check: null };
const sessionSum = (session_date, over) => ({ session_date, entered: 3, not_entered: 0, open: 2, closed: 1, wins: 0, losses: 1, flat: 0, win_rate: 0, net_pnl_market: -1200, net_pnl_your: -1650, unrealised_pnl: 1400, flagged_open: 1, ...over });
const SESSIONS = {
  "2026-10-06": { summary: sessionSum("2026-10-06"), trades: [
    { ...SESSION_ROW, id: "acc:rule.model_news.v1:2026-10-05-RELIANCE-3d", strategy_id: "rule.model_news.v1", ticker: "RELIANCE", entry_date: "2026-10-06", exit_date: "2026-10-09", state: "open", outcome: null, entry_price: 1182, exit_or_last_price: 1158, unrealised_pnl: -2016, unrealised_pct: -2.03, lo80: 1165, lo50: 1175, hi50: 1200, hi80: 1212, target_price: 1190, to_target_pct: 2.76, check: { check_at: "2026-10-06T08:43:00Z", band: "below80", flags: ["outside_range"], flagged: true, ret_since_entry_pct: -2.03 } },
    { ...SESSION_ROW, id: "acc:rule.model_news.v1:2026-10-05-TCS-3d", strategy_id: "rule.model_news.v1", ticker: "TCS", entry_date: "2026-10-06", exit_date: "2026-10-09", state: "open", outcome: null, entry_price: 3010, exit_or_last_price: 3062, quantity: 33, unrealised_pnl: 1716, unrealised_pct: 1.73, lo80: 2950, lo50: 2990, hi50: 3080, hi80: 3120, target_price: 3040, to_target_pct: -0.72, check: { check_at: "2026-10-06T08:43:00Z", band: "inside50", flags: [], flagged: false, ret_since_entry_pct: 1.73 } },
    { ...SESSION_ROW, id: "acc:rule.model_news.v1:2026-10-05-HDFCBANK-1d", strategy_id: "rule.model_news.v1", horizon_days: 1, ticker: "HDFCBANK", entry_date: "2026-10-06", exit_date: "2026-10-06", state: "closed", outcome: "loss", entry_price: 711.5, exit_or_last_price: 702, last_price_date: null, pnl_market: -1200, pnl_your: -1650, settled_at: "2026-10-06T12:15:00Z" },
  ] },
  "2026-10-05": { summary: sessionSum("2026-10-05", { entered: 1, open: 1, closed: 0, losses: 0, win_rate: null, net_pnl_market: null, net_pnl_your: null, unrealised_pnl: 300, flagged_open: 0 }), trades: [
    { ...SESSION_ROW, id: "acc:rule.model_news.v1:2026-10-02-INFY-5d", strategy_id: "rule.model_news.v1", horizon_days: 5, ticker: "INFY", entry_date: "2026-10-05", exit_date: "2026-10-12", state: "open", outcome: null, entry_price: 1500, exit_or_last_price: 1504.5, quantity: 66, unrealised_pnl: 297, unrealised_pct: 0.3, lo80: 1440, lo50: 1475, hi50: 1540, hi80: 1570, target_price: 1515, to_target_pct: 0.7 },
  ] },
};
function withSessions(rest, market) {
  const m = /^portfolios\/sessions\/(\d{4}-\d{2}-\d{2})$/.exec(rest);
  if (m) {
    const s = SESSIONS[m[1]];
    if (!s) return { status: 503, body: { title: "Data service unavailable", status: 503, detail: "The read models cannot be read right now; try again shortly." } };
    return { status: 200, body: envelope(market, `trades:${m[1]}`, { market, as_of: "2026-10-06", session_date: m[1], summary: s.summary, trades: s.trades, paper: true }) };
  }
  if (rest !== "portfolios") return undefined;
  const p = structuredClone(mockupPayload("07-paper-portfolios", market));
  p.open_trades = [];
  p.trade_checks = [];
  const sum = (scope, family, period, over = {}) => ({ scope, family, period, open: 3, closed: 1, wins: 0, losses: 1, flat: 0, win_rate: 0, net_pnl_market: -1200, net_pnl_your: -1650, pnl_your_missing: 0, unrealised_pnl: -3, flagged_open: 1, currency: "INR", ...over });
  p.all_trades = {
    window: { sessions: 10, from: "2026-09-23", to: "2026-10-06" },
    summary: [sum("all", "all", "to_date"), sum("all", "all", "window"), sum("all", "rule", "to_date"),
      sum("head_to_head", "all", "to_date", { open: 1, closed: 0, losses: 0, win_rate: null, net_pnl_market: null, net_pnl_your: null, unrealised_pnl: 410, flagged_open: 0 })],
    trades: [{ ...SESSION_ROW, id: "h2h:highest_probability:ai.combined.opus.v1:2026-10-05-RELIANCE-3d", scope: "head_to_head", view: "head_to_head", strategy_id: "ai.combined.opus.v1", family: "ai", pick_rule: "highest_probability", ticker: "RELIANCE", entry_date: "2026-10-06", exit_date: "2026-10-09", state: "open", outcome: null, entry_price: 1182, exit_or_last_price: 1187, unrealised_pnl: 410, unrealised_pct: 0.42 }],
    sessions: [sessionSum("2026-10-06"), sessionSum("2026-10-05", { entered: 1, open: 1, closed: 0, losses: 0, win_rate: null, flagged_open: 0 }), sessionSum("2026-10-02", { entered: 2, open: 0, closed: 2, flagged_open: 0 })],
  };
  return { status: 200, body: envelope(market, "_", p) };
}

export const cases = [
  {
    name: "paper-portfolios-sessions-phone",
    path: "/india/paper-portfolios",
    api: withSessions,
    widths: [390],
    waitFor: ".p-portfolios .at-list",
    expectText: ["Entry session", "RELIANCE", "TCS", "head-to-head 1 open", "open · outside range"],
    check: async (page) => (await clippedHeaders(page)).map((p) => `6 Oct list: ${p}`),
  },
  {
    name: "paper-portfolios-sessions",
    path: "/india/paper-portfolios",
    api: withSessions,
    widths: [1280],
    allowConsole: [HTTP_ERROR_LINE],
    waitFor: ".p-portfolios .at-list",
    expectText: ["Entry session", "2 open · 1 closed · 0 won, 1 lost", "outside range", "inside 50%", "head-to-head 1 open", "one session at a time"],
    check: async (page) => {
      const problems = [];
      for (const p of await clippedHeaders(page)) problems.push(`6 Oct list: ${p}`);
      if ((await page.$$(".p-portfolios .at-list td.cw .rng svg")).length !== 2) problems.push("not one range per open row with bands");
      const kpis = await page.textContent(".kpis");
      if (!/Open paper trades\s*3/.test(kpis) || !kpis.includes("1 flagged")) problems.push(`open KPI not from the summary: ${kpis}`);
      if ((await page.$$('[aria-label="Open paper trades by strategy"]')).length) problems.push("the open-trades card (open_trades) still shown");
      let text = await listText(page);
      if (!text.includes("RELIANCE") || !text.includes("TCS") || text.includes("INFY") || text.includes("Highest chance")) problems.push(`6 Oct list: ${text}`);
      await page.selectOption('select[aria-label="Entry session"]', "2026-10-05");
      await page.waitForFunction(() => document.querySelector('[aria-label="All paper trades"] .at-list')?.textContent.includes("INFY"));
      text = await listText(page);
      if (text.includes("RELIANCE")) problems.push(`5 Oct list still shows 6 Oct: ${text}`);
      await press(page, "Whose trades", "Head-to-head");
      text = await listText(page);
      if (!text.includes("Highest chance") || text.includes("INFY") || (await page.$$('select[aria-label="Entry session"]')).length) problems.push(`head-to-head scope: ${text}`);
      await press(page, "Whose trades", "All strategies");
      await page.selectOption('select[aria-label="Entry session"]', "2026-10-02");
      await page.waitForSelector('[aria-label="All paper trades"] [role="alert"]');
      const card = await page.textContent('[aria-label="All paper trades"]');
      if (!card.includes("Data service unavailable") || !card.includes("Since paper trading began")) problems.push("the session page's error did not stay inside the list");
      return problems;
    },
  },
  {
    name: "paper-portfolios-price-pending",
    path: "/india/paper-portfolios",
    api: withPricePending,
    widths: [1280],
    waitFor: ".p-portfolios .ot",
    expectText: ["price pending", "open, no price yet", "+₹30,219"],
    check: async (page) => {
      const text = await page.textContent(".p-portfolios");
      const problems = [];
      if (/NaN|undefined|null/.test(text)) problems.push("NaN, undefined or null printed");
      if (text.includes("₹0 ") || /[^0-9,.]₹0(?![0-9,.])/.test(text.replace(/drawdown ₹0/g, ""))) problems.push("a ₹0 shown for a pending price");
      return problems;
    },
  },
  {
    name: "paper-portfolios-all-trades-sample",
    path: "/us/paper-portfolios",
    market: "us",
    api: withSample,
    widths: [1280, 390],
    waitFor: ".p-portfolios .at-list",
    expectText: ["1 open · 4 closed · 2 won, 1 lost, 1 even", "1 open · 3 closed · 1 won, 1 lost, 1 even", "did not enter: no stored open price that day"],
    check: async (page) => {
      const problems = [];
      // every visible list column lies inside the table's visible box (no column scrolled out of sight), in each view
      // that has rows: All strategies first, then Mine; fails when the list has no header at all
      const clipped = () => clippedHeaders(page);
      for (const p of await clipped()) problems.push(`All strategies: ${p}`);
      await page.click('[aria-label="Whose trades"] button:has-text("Mine")');
      for (const p of await clipped()) problems.push(`Mine: ${p}`);
      const text = await page.textContent('[aria-label="All paper trades"]');
      if (!text.includes("sold 9 Oct") || !text.includes("bought 9 Oct")) problems.push("your own trades' dates not in words");
      if (text.includes("planned exit")) problems.push("a planned exit shown on your own open lot");
      await page.click('[aria-label="Whose trades"] button:has-text("Head-to-head")');
      if (!(await page.textContent('[aria-label="All paper trades"]')).includes("1 without your-cost figure yet")) problems.push("missing your-cost count not shown");
      return problems;
    },
  },
  {
    name: "paper-portfolios-all-trades",
    path: "/india/paper-portfolios",
    api: withAllTrades,
    widths: [1280, 390],
    waitFor: ".p-portfolios .at-list",
    expectText: ["All paper trades in one place", "Since paper trading began", "Last 10 sessions", "1 open · 1 closed · 0 won, 1 lost", "closed, lost money", "did not enter: no stored open price that day", "so far, before costs", "checked 11:13 IST", "Closed trades older than the last 10 sessions are counted above but not listed."],
    check: async (page) => {
      const problems = [];
      let text = await listText(page);
      if (text.includes("Highest chance")) problems.push("a head-to-head trade is listed under All strategies (views pooled)");
      await press(page, "Won or lost", "Lost");
      text = await listText(page);
      if (!text.includes("HDFCBANK") || text.includes("TCS")) problems.push(`Lost filter: ${text}`);
      await press(page, "Won or lost", "Any");
      await press(page, "Open or closed", "Open");
      text = await listText(page);
      if (!text.includes("RELIANCE") || text.includes("HDFCBANK")) problems.push(`Open filter: ${text}`);
      await press(page, "Open or closed", "All");
      await press(page, "Whose trades", "Head-to-head");
      text = await listText(page);
      if (!text.includes("Highest chance") || text.includes("HDFCBANK")) problems.push(`Head-to-head scope: ${text}`);
      await press(page, "Whose trades", "Mine");
      const card = await page.textContent('[aria-label="All paper trades"]');
      if (!card.includes("You") || !card.includes("after your cost") || card.includes("Net after market cost")) problems.push("Mine scope: wrong words or a market-cost column");
      return problems;
    },
  },
  {
    name: "paper-portfolios-india",
    path: "/india/paper-portfolios",
    mockup: "07-paper-portfolios",
    widths: [1280, 390],
    waitFor: ".p-portfolios .ot",
    expectText: [PAPER, "The list of all paper trades is not in this page’s data yet.", "Head-to-head portfolios", "Open paper trades by strategy", "14 of 14 open", "Your own paper portfolio", "1 recorded trade", "Add own paper trade"],
    expectSelector: [".p-portfolios .ot tr.grp", ".p-portfolios .rng svg", ".p-portfolios .fbox .tot"],
  },
  { name: "paper-portfolios-us", path: "/us/paper-portfolios", market: "us", mockup: "07-paper-portfolios", widths: [1280], waitFor: ".p-portfolios .eur", expectText: [PAPER, "Euro view of AAPL", "Euros paid"] },
  {
    name: "paper-portfolios-filters",
    path: "/india/paper-portfolios",
    widths: [1280],
    waitFor: ".p-portfolios .ot",
    check: async (page) => {
      const problems = [];
      await page.click('.p-portfolios button.md-chip:has-text("AI traders")');
      await page.click('.p-portfolios button.md-chip:has-text("Head-to-head")');
      const end = await page.textContent('[aria-label="Open paper trades by strategy"] .head .end');
      if (!end.startsWith("1 of 14 open")) problems.push(`filtered count: ${end}`);
      const groups = await page.$$eval(".p-portfolios .ot tr.grp", (r) => r.map((x) => x.textContent));
      if (groups.length !== 1 || !groups[0].includes("AI")) problems.push(`groups: ${groups.join(" | ")}`);
      return problems;
    },
  },
  {
    name: "paper-portfolios-add-trade",
    path: "/india/paper-portfolios",
    widths: [1280, 390],
    allowConsole: [HTTP_ERROR_LINE],
    waitFor: ".p-portfolios .own",
    check: async (page) => {
      const problems = [];
      const seen = await answerPosts(page, [422, 503, 202]);
      await page.click('button:has-text("Add own paper trade")');
      await page.waitForSelector("dialog[open]");
      await page.fill("dialog input[type=number] >> nth=0", "1.5");
      await page.click('dialog button[type=submit]');
      if (!(await page.textContent("dialog")).includes("Whole shares only in India.")) problems.push("fractional India shares not caught in the form");
      if (seen.length) problems.push("a request was sent for an invalid form");
      await page.fill("dialog input[type=number] >> nth=0", "5");
      await page.click('dialog button[type=submit]');
      await page.waitForSelector('dialog [role="alert"]');
      if (!(await page.textContent("dialog")).includes("No stored bar for RELIANCE")) problems.push("the refusal's message is not shown");
      await page.click('dialog button[type=submit]');
      await page.waitForFunction(() => document.querySelector("dialog")?.textContent.includes("Try again later"));
      await page.click('dialog button[type=submit]');
      await page.waitForSelector("dialog[open]", { state: "detached" });
      const text = await page.textContent(".p-portfolios");
      if (!/Pending: buy 5 [A-Z]+ at the open/.test(text)) problems.push("no pending line after a 202");
      if (!/Pending requests\s*1/.test(await page.textContent(".kpis"))) problems.push("pending KPI not 1");
      if (seen.length !== 3) problems.push(`requests sent: ${seen.length}`);
      else {
        if (seen.some((s) => s.method !== "POST" || !s.type.startsWith("application/json"))) problems.push("not a JSON POST");
        if (!/^[A-Za-z0-9_-]{8,64}$/.test(seen[0].key)) problems.push(`bad key ${seen[0].key}`);
        if (new Set(seen.map((s) => s.key)).size !== 1) problems.push("the same request did not keep its key");
        const fields = Object.keys(seen[0].body).sort().join(",");
        if (fields !== "price_basis,quantity,side,ticker,trade_date") problems.push(`body fields: ${fields}`);
        if (seen[0].body.quantity !== 5) problems.push("quantity not a number");
      }
      return problems;
    },
  },
  {
    name: "paper-portfolios-stored-india",
    path: "/india/paper-portfolios",
    api: storedApi,
    widths: [1280, 390],
    waitFor: ".p-portfolios .own, .p-portfolios [aria-label='Your own paper portfolio']",
    expectText: [PAPER, "No rule-vs-AI trade of this side has finished yet.", "No open paper trade: nothing has entered", "No own paper trade in India (NSE) yet."],
  },
  { name: "paper-portfolios-error", path: "/india/paper-portfolios", apiStatus: 503, allowConsole: [HTTP_ERROR_LINE], widths: [1280], waitFor: '[role="alert"]', expectText: ["Data service unavailable", "Try again"] },
];
