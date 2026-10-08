// UI cases of the shell and shared components (B7). A case: {name, path, market?, widths?, mockup?, expectText?,
// expectSelector?, waitFor?, status?, apiStatus?, api?, keyboard?, allowConsole? (regexes of expected console
// messages, e.g. the browser's own line for a 503 the case asked for), check?(page, {width, market}) -> string[]}.
// Page sessions add their own file here (cases/<page>.mjs) with their page's cases at the mockup's widths.

const PAPER = "No proven strong signals today";
const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of (404|503)/;

/** The shell's own checks on any page: one current nav item, the market switch pressed on the market, Paper visible. */
async function shellChecks(page, { market }) {
  const problems = [];
  const pressed = await page.$$eval('[aria-label="Market"] button[aria-pressed="true"]', (b) => b.map((x) => x.textContent));
  if (pressed.length !== 1 || pressed[0] !== (market === "us" ? "US" : "India")) problems.push(`market switch pressed: ${pressed.join(",")}`);
  const current = await page.$$eval('.mb-sidebar [aria-current="page"]', (a) => a.length);
  if (current !== 1) problems.push(`sidebar has ${current} current items`);
  const paper = await page.$$eval(".mb-tag.paper", (t) => t.length);
  if (!paper) problems.push("no Paper tag on the page");
  return problems;
}

export const cases = [
  { name: "shell-home-india", path: "/india", mockup: "01-home", widths: [1280, 1024, 768, 390], waitFor: ".phead", expectText: [PAPER, "Regime", "Home"], check: shellChecks },
  { name: "shell-home-us", path: "/us", market: "us", mockup: "01-home", widths: [1280], waitFor: ".phead", expectText: [PAPER], check: shellChecks },
  { name: "shell-watchlist", path: "/india/watchlist", mockup: "02-watchlist", waitFor: ".phead", expectText: [PAPER, "Watchlist"], check: shellChecks },
  { name: "shell-company", path: "/india/stocks/RELIANCE", mockup: "03-company", waitFor: ".phead", expectText: ["Company"], check: shellChecks },
  { name: "shell-assistant", path: "/india/assistant", mockup: "11-assistant", waitFor: ".mb-pending-h1", expectText: ["Assistant"], check: async (page, ctx) => (await shellChecks(page, ctx)).filter((p) => !p.startsWith("no Paper")) },
  { name: "state-error-503", path: "/india/watchlist", apiStatus: 503, allowConsole: [HTTP_ERROR_LINE], widths: [1280, 390], waitFor: '[role="alert"]', expectText: ["Data service unavailable", "Try again", "dashboard.html"] },
  { name: "state-loading", path: "/india/news", apiStatus: "slow", widths: [1280], waitFor: '[aria-busy="true"]', expectText: ["Loading the page data"] },
  { name: "state-bad-ticker", path: "/india/stocks/not-a-ticker", widths: [1280], waitFor: '[role="alert"]', expectText: ["Not found"] },
  { name: "unknown-market-404", path: "/mars", status: 404, allowConsole: [HTTP_ERROR_LINE], widths: [1280], keyboard: false, expectText: ["Page not found"] },
  {
    name: "market-switch",
    path: "/india/watchlist",
    widths: [1280],
    waitFor: ".phead",
    check: async (page) => {
      await page.click('[aria-label="Market"] button:has-text("US")');
      await page.waitForURL("**/us/watchlist");
      const switched = [];
      await page.goto(page.url().replace("/us/watchlist", "/india/stocks/RELIANCE"));
      await page.click('[aria-label="Market"] button:has-text("US")');
      await page.waitForURL("**/us/watchlist").catch(() => switched.push(`stock page switched to ${page.url()}, not the US watchlist`));
      return switched;
    },
  },
  {
    name: "phone-drawer",
    path: "/india",
    widths: [390],
    waitFor: ".phead",
    check: async (page) => {
      const problems = [];
      await page.click('.mb-navbar button:has-text("More")');
      if (!(await page.$(".mb-sidebar.open"))) problems.push("More did not open the drawer");
      await page.keyboard.press("Escape");
      if (await page.$(".mb-sidebar.open")) problems.push("Escape did not close the drawer");
      return problems;
    },
  },
  {
    name: "tooltip-keyboard",
    path: "/india",
    widths: [1280],
    waitFor: ".phead",
    check: async (page) => {
      await page.focus(".phead .md-chip");
      const shown = await page.$eval("#tip", (t) => t.classList.contains("on") && t.textContent.length > 0);
      return shown ? [] : ["focusing a chip with data-tip did not show the tooltip"];
    },
  },
];
