// UI cases of page 10, Companies (B14), at the mockup's widths (design/mockups/10-companies/shot-{1280,390}-full.png):
// the tables, the requests and history lists, and the request dialogs on B11's preview and commands routes (answered
// here in the browser, so the case sees exactly what the page sends).
const PREVIEW = "**/api/v1/markets/*/companies/preview";
const COMMANDS = "**/api/v1/markets/*/companies/commands";
const REFUSED_LINE = /^Failed to load resource: the server responded with a status of 422/;
const receipt = (result, message = null, extra = {}) => ({ command_id: "cmd-1", result, refusal_code: null, message, inbox_id: null, record_ids: [], budget_left: 49, paper: true, ...extra });

/** Captures the page's POSTs and answers them with the given replies, in order per route. */
async function answer(page, url, replies) {
  const seen = [];
  await page.route(url, async (route) => {
    const req = route.request();
    seen.push({ body: JSON.parse(req.postData() || "null"), key: req.headers()["idempotency-key"] });
    const [status, body] = replies.shift() ?? [500, null];
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  return seen;
}

/** Deactivate RELIANCE: form, preview, confirm; one key on both calls; the summary sent back as shown; pending listed. */
async function deactivateFlow(page) {
  const problems = [];
  const summary = "Deactivate RELIANCE (Reliance Industries) in India from the next pre-open run";
  const previews = await answer(page, PREVIEW, [[200, { tool: "deactivate_company", summary, preview: null, arguments: { ticker: "RELIANCE", reason: "too volatile" }, paper: true }]]);
  const commands = await answer(page, COMMANDS, [[202, receipt("pending", "Recorded; pending until the next import.")]]);
  await page.getByRole("button", { name: "Deactivate Reliance Industries" }).click();
  await page.getByLabel("Reason").fill("  too volatile  ");
  await page.getByRole("button", { name: "Check the request" }).click();
  await page.getByText(summary).waitFor();
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.getByText(`Pending: ${summary}`).waitFor();
  if (previews.length !== 1 || commands.length !== 1) problems.push(`calls: ${previews.length} previews, ${commands.length} commands (expected 1 and 1)`);
  else {
    if (JSON.stringify(previews[0].body) !== JSON.stringify({ tool: "deactivate_company", arguments: { ticker: "RELIANCE", reason: "too volatile" } })) problems.push(`preview body ${JSON.stringify(previews[0].body)}`);
    if (commands[0].body.confirmed_summary !== summary) problems.push("confirmed_summary differs from the preview's summary");
    if (!previews[0].key || previews[0].key !== commands[0].key) problems.push("the preview and the confirm must send the same Idempotency-Key");
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(previews[0].key ?? "")) problems.push(`key ${previews[0].key} does not fit the route's pattern`);
  }
  if ((await page.locator("dialog[open]").count()) !== 0) problems.push("the dialog stayed open after the request was recorded");
  const pending = await page.locator('.mb-kpi:has-text("Pending requests") .v').textContent();
  if (pending?.trim() !== "1") problems.push(`pending KPI shows ${pending}, expected 1`);
  return problems;
}

/** Delete needs the typed ticker; a stale summary shows the new one; a refusal shows the tool layer's words. */
async function deleteAndRefusals(page) {
  const problems = [];
  const first = "Delete MARUTI for good (old)", second = "Delete MARUTI for good";
  const previews = await answer(page, PREVIEW, [
    [200, { tool: "delete_company", summary: first, preview: null, arguments: { ticker: "MARUTI", confirm: "MARUTI" }, paper: true }],
    [200, { tool: "delete_company", summary: second, preview: null, arguments: { ticker: "MARUTI", confirm: "MARUTI" }, paper: true }],
  ]);
  const commands = await answer(page, COMMANDS, [
    [422, receipt("refused", "The summary changed since the preview, so nothing was written; preview again")],
    [422, receipt("refused", "MARUTI has open paper trades; try again after they settle", { refusal_code: "invalid_arguments" })],
  ]);
  await page.getByRole("button", { name: "Delete Maruti Suzuki" }).click();
  const go = page.getByRole("button", { name: "Check the request" });
  if (!(await go.isDisabled())) problems.push("delete is enabled before the ticker is typed");
  await page.getByLabel("Type MARUTI to confirm").fill("maruti");
  if (await go.isDisabled()) problems.push("delete stays disabled after the ticker is typed");
  await go.click();
  await page.getByText(first).waitFor();
  await page.getByRole("button", { name: "Delete for good" }).click();
  await page.getByText("The summary changed since you checked it").waitFor();
  if (!(await page.getByText(second).count())) problems.push("the new summary is not shown after a stale confirm");
  await page.getByRole("button", { name: "Delete for good" }).click();
  await page.getByText("MARUTI has open paper trades").waitFor();
  if (commands.length !== 2 || commands[1].body.confirmed_summary !== second) problems.push("the second confirm must send the new summary");
  if (previews[0]?.body?.arguments?.confirm !== "MARUTI") problems.push(`delete confirm sent ${previews[0]?.body?.arguments?.confirm}`);
  await page.keyboard.press("Escape");
  if ((await page.locator("dialog[open]").count()) !== 0) problems.push("Escape did not close the dialog");
  return problems;
}

/** Add: the resolved identifiers of the preview are shown before Confirm; a refused preview stays on the form. */
async function addFlow(page) {
  const problems = [];
  await answer(page, PREVIEW, [
    [422, receipt("refused", "SPY is an ETF; only common stocks can be added", { refusal_code: "etf" })],
    [200, { tool: "add_company", summary: "Add AMZN (Amazon.com, Inc.) to the US watchlist at $1,000 per paper trade", arguments: { symbol: "AMZN" }, paper: true,
      preview: { market: "us", symbol: "AMZN", name: "Amazon.com, Inc.", exchange: "Nasdaq", sector: "Consumer Discretionary", yahoo: "AMZN", nse_symbol: null, cik: "0001018724", amount: 1000, amount_is_default: true, currency: "USD" } }],
  ]);
  await page.getByRole("button", { name: "Add company" }).click();
  await page.getByLabel("Exchange symbol").fill("spy");
  await page.getByRole("button", { name: "Check the symbol" }).click();
  await page.locator("dialog .dmsg", { hasText: "SPY is an ETF" }).waitFor();
  await page.getByLabel("Exchange symbol").fill("amzn");
  await page.getByRole("button", { name: "Check the symbol" }).click();
  await page.locator("dialog .summ", { hasText: "Amazon.com, Inc." }).waitFor();
  for (const t of ["Nasdaq · Consumer Discretionary", "AMZN · 0001018724", "(default)", "Confirm: add AMZN?"]) if (!(await page.locator("dialog", { hasText: t }).count())) problems.push(`summary misses ${t}`);
  return problems;
}

const emptyLists = async (rest, market) => {
  if (rest !== "companies") return undefined;
  const { envelope, mockupPayload } = await import("../fixtures.mjs");
  const p = mockupPayload("10-companies", market);
  return { status: 200, body: envelope(market, "_", { ...p, companies: p.companies.filter((c) => c.state === "active"), lifecycle: [], commands: [] }) };
};

export const cases = [
  {
    name: "companies-india",
    path: "/india/companies",
    mockup: "10-companies",
    widths: [1280, 390],
    waitFor: ".co",
    expectText: ["Active companies (3)", "Inactive companies (1)", "INDIGO", "Default per paper trade", "₹1,00,000", "custom", "Lifecycle history", "No company command recorded for this market yet"],
    expectSelector: ["table.co", ".ev li", "button.md-btn.filled"],
  },
  { name: "companies-us", path: "/us/companies", market: "us", mockup: "10-companies", widths: [1280], waitFor: ".co", expectText: ["Active companies (3)", "DAL", "$1,000", "Requests"], expectSelector: [".ev.cmd li"] },
  { name: "companies-deactivate", path: "/india/companies", mockup: "10-companies", widths: [1280], waitFor: ".co", check: deactivateFlow },
  { name: "companies-delete", path: "/india/companies", mockup: "10-companies", widths: [1280], waitFor: ".co", check: deleteAndRefusals, allowConsole: [REFUSED_LINE] },
  { name: "companies-add", path: "/us/companies", market: "us", mockup: "10-companies", widths: [1280], waitFor: ".co", check: addFlow, allowConsole: [REFUSED_LINE] },
  { name: "companies-empty-lists", path: "/india/companies", mockup: "10-companies", widths: [1280], waitFor: ".co", api: emptyLists, expectText: ["No inactive company.", "No event stored.", "No company command recorded"] },
];
