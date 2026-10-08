// UI cases of page 07, Paper portfolios (B16), at the mockup's widths (design/mockups/07-paper-portfolios/shot-*-full.png):
// the mockup's data (India with open trades and checks; US with the euro view), the stored data of today, the
// filters, the add-trade form against POST /paper-trades (pending, a refusal, a retry with the same key), and the
// error state. The POST is answered in the test; nothing reaches any inbox.
import { storedApi } from "../b16/stored.mjs";

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

export const cases = [
  {
    name: "paper-portfolios-india",
    path: "/india/paper-portfolios",
    mockup: "07-paper-portfolios",
    widths: [1280, 390],
    waitFor: ".p-portfolios .ot",
    expectText: [PAPER, "Head-to-head portfolios", "Open paper trades by strategy", "14 of 14 open", "Your own paper portfolio", "1 recorded trade", "Add own paper trade"],
    expectSelector: [".p-portfolios .ot tr.grp", ".p-portfolios .rng svg", ".p-portfolios .luck svg"],
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
      if (!text.includes("Pending: buy 5 RELIANCE at the open")) problems.push("no pending line after a 202");
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
