// UI cases of page 05, Strategy lab (B16), at the mockup's widths (design/mockups/05-strategy-lab/shot-*-full.png):
// the mockup's data, the stored data of today (back-test rows only), the switches (basis never pooled, head-to-head,
// your cost), the strategy chosen by the URL hash (as Help and the portfolios link it), and the error state.
import { storedApi } from "../b16/stored.mjs";

const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of 503/;
const PAPER = "No proven strong signals today";

const press = (page, group, text) => page.click(`[aria-label="${group}"] button:has-text("${text}")`);
const rowsText = (page) => page.$$eval(".p-lab .lb tbody tr", (rows) => rows.map((r) => r.textContent));

export const cases = [
  {
    name: "strategy-lab-india",
    path: "/india/strategy-lab",
    mockup: "05-strategy-lab",
    widths: [1280, 390],
    waitFor: ".p-lab .cum svg",
    expectText: [PAPER, "Every strategy, ranked by profit after costs", "Model without news", "too few to rank", "In plain words", "more settled trades needed", "Where each strategy wins and loses", "By reason the price moved"],
    expectSelector: [".p-lab .luck svg", ".p-lab .hm td[tabindex]", ".p-lab .chk li.no"],
    check: async (page) => {
      const problems = [];
      const first = (await rowsText(page))[0];
      if (!first.includes("Model without news")) problems.push(`first ranked row: ${first}`);
      const selected = await page.$eval(".p-lab .det .big", (b) => b.textContent);
      if (!selected.startsWith("Model without news")) problems.push(`default selection: ${selected}`);
      return problems;
    },
  },
  { name: "strategy-lab-us", path: "/us/strategy-lab", market: "us", mockup: "05-strategy-lab", widths: [1280], waitFor: ".p-lab .lb", expectText: [PAPER, "$"] },
  {
    name: "strategy-lab-switches",
    path: "/india/strategy-lab",
    widths: [1280],
    waitFor: ".p-lab .lb",
    check: async (page) => {
      const problems = [];
      await press(page, "Basis", "Back-test");
      const kept = await page.$eval(".p-lab .det .big", (b) => b.textContent);
      if (!kept.startsWith("Model without news")) problems.push(`the selection followed the slice: ${kept}`);
      const back = await page.textContent(".p-lab .lb");
      if (!back.includes("not run")) problems.push("back-test basis shows no 'not run' strategy");
      if (!(await page.textContent(".p-lab")).includes("Back-test run.")) problems.push("back-test run facts missing");
      if ((await page.$$(".p-lab .cum polyline")).length) problems.push("cumulative lines drawn on the back-test basis (pooled)");
      await press(page, "Basis", "Forward");
      await press(page, "View", "Head-to-head");
      if (!(await page.textContent(".p-lab")).includes("By family and pick rule")) problems.push("head-to-head view has no pick-rule table");
      await press(page, "View", "Accuracy");
      await press(page, "Costs", "Your cost");
      if (!(await page.textContent(".p-lab .lb thead")).includes("Profit after your cost")) problems.push("your-cost column title missing");
      await press(page, "Horizon", "N+3");
      if (!(await page.textContent(".p-lab .lb .end, .p-lab .card .end")).includes("N+3 only")) problems.push("horizon N+3 not shown in the card head");
      await page.click('.p-lab .lb button.sel:has-text("Always buy")');
      if (!page.url().endsWith("#base.always_up.v1")) problems.push(`hash not updated: ${page.url()}`);
      return problems;
    },
  },
  {
    name: "strategy-lab-hash",
    path: "/india/strategy-lab#rule.model_news.v1",
    widths: [1280],
    waitFor: ".p-lab .det .big",
    check: async (page) => {
      const big = await page.$eval(".p-lab .det .big", (b) => b.textContent);
      return big.startsWith("Model + news") ? [] : [`hash did not select the strategy: ${big}`];
    },
  },
  {
    name: "strategy-lab-stored-india",
    path: "/india/strategy-lab",
    api: storedApi,
    widths: [1280, 390],
    waitFor: ".p-lab .lb",
    expectText: [PAPER, "no trades yet", "No settled trade in this view yet.", "No forward accuracy row yet"],
    check: async (page) => {
      await press(page, "Basis", "Back-test");
      const text = await page.textContent(".p-lab");
      return text.includes("Always buy") && text.includes("Back-test run.") && !text.includes("null") ? [] : ["stored back-test basis did not render its run"];
    },
  },
  { name: "strategy-lab-stored-us", path: "/us/strategy-lab", market: "us", api: storedApi, widths: [1280], waitFor: ".p-lab .lb", expectText: [PAPER, "no trades yet"] },
  { name: "strategy-lab-error", path: "/india/strategy-lab", apiStatus: 503, allowConsole: [HTTP_ERROR_LINE], widths: [1280], waitFor: '[role="alert"]', expectText: ["Data service unavailable", "Try again"] },
];
