// UI cases of page 07, Paper portfolios (B16), at the mockup's widths (design/mockups/07-paper-portfolios/shot-*-full.png):
// the mockup's data (India with open trades and checks; US with the euro view), the stored data of today, the
// filters, the add-trade form against POST /paper-trades (pending, a refusal, a retry with the same key), and the
// error state. The POST is answered in the test; nothing reaches any inbox.
import { storedApi } from "../b16/stored.mjs";
import { envelope, mockupPayload } from "../fixtures.mjs";

const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of (422|503)/;
const PAPER = "No proven strong signals today";

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
      row({ id: "acc:base.always_up.v1:2026-10-01-TCS-1d", scope: "all", strategy_id: "base.always_up.v1", family: "baseline", ticker: "TCS", entry_date: "2026-10-02", exit_date: "2026-10-02", state: "not_entered", outcome: null, not_entered_reason: "no_entry", entry_price: null, exit_or_last_price: null, quantity: null, pnl_market: null, pnl_your: null }),
      row({ id: "h2h:highest_probability:ai.combined.opus.v1:2026-09-29-RELIANCE-3d", scope: "head_to_head", view: "head_to_head", strategy_id: "ai.combined.opus.v1", family: "ai", pick_rule: "highest_probability", ticker: "RELIANCE", entry_date: "2026-09-30", exit_date: "2026-10-06", state: "closed", outcome: "win", entry_price: 1182, exit_or_last_price: 1218, pnl_market: 1016, pnl_your: 575, settled_at: "2026-10-06T12:15:00Z" }),
      row({ id: "pt-india-20261006-RELIANCE-2", scope: "mine", view: null, strategy_id: null, family: "mine", horizon_days: null, side: "sell", ticker: "RELIANCE", entry_date: null, exit_date: "2026-10-06", state: "closed", outcome: "win", entry_price: 1182, exit_or_last_price: 1218, quantity: 50, amount: null, pnl_market: null, pnl_your: 1800 }),
    ],
  };
  return { status: 200, body: envelope(market, "_", p) };
}

const press = (page, group, text) => page.click(`[aria-label="${group}"] button:has-text("${text}")`);
const listText = (page) => page.textContent('[aria-label="All paper trades"] .at-list').catch(() => "");

export const cases = [
  {
    name: "paper-portfolios-all-trades",
    path: "/india/paper-portfolios",
    api: withAllTrades,
    widths: [1280, 390],
    waitFor: ".p-portfolios .at-list",
    expectText: ["All your paper trades in one place", "Since paper trading began", "Last 10 sessions", "1 open · 1 closed · 0 won, 1 lost", "closed, lost money", "did not enter: no stored open price that day", "so far, before costs", "checked 11:13 IST", "Closed trades older than the last 10 sessions are counted above but not listed."],
    check: async (page) => {
      const problems = [];
      let text = await listText(page);
      if (text.includes("Highest probability")) problems.push("a head-to-head trade is listed under All strategies (views pooled)");
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
      if (!text.includes("Highest probability") || text.includes("HDFCBANK")) problems.push(`Head-to-head scope: ${text}`);
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
    expectText: [PAPER, "No settled head-to-head trade for this family yet.", "No open paper trade: nothing has entered", "No own paper trade in India (NSE) yet."],
  },
  { name: "paper-portfolios-error", path: "/india/paper-portfolios", apiStatus: 503, allowConsole: [HTTP_ERROR_LINE], widths: [1280], waitFor: '[role="alert"]', expectText: ["Data service unavailable", "Try again"] },
];
