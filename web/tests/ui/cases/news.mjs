import { envelope, mockupPayload } from "../fixtures.mjs";
// UI cases of page 09, News (B14), at the mockup's widths (design/mockups/09-news/shot-{1280,390}-full.png): the
// movers band, the feed with its filters, company select, pager and day groups, the calendar and the company rail,
// and the empty states.
const FEED = 'section[aria-label="All stories of the window"]';

/** The feed's filters, pager and rail work on the mockup's 29 India stories (12 market-wide, 1 can carry a call). */
async function feedChecks(page) {
  const problems = [];
  const rows = () => page.locator(`${FEED} .feed .row`).count();
  const movers = await page.locator('section[aria-label="Market movers"] .mv .it').count();
  if (movers < 1 || movers > 10) problems.push(`movers band shows ${movers} stories (expected 1..10)`);
  if ((await rows()) !== 10) problems.push(`first page shows ${await rows()} rows, expected 10`);
  if (!(await page.getByText("Page 1 of 3 · 29 stories, 10 a page").count())) problems.push("pager summary missing");
  await page.locator(`${FEED} .pager button`, { hasText: "3" }).click();
  if ((await rows()) !== 9) problems.push(`page 3 shows ${await rows()} rows, expected 9`);
  await page.locator(`${FEED} button.md-chip`, { hasText: "Last 24 h" }).click();
  const recent = Number(/(\d+) in the last 24 h/.exec((await page.locator(`${FEED} .head`).textContent()) ?? "")?.[1] ?? -1);
  if ((await rows()) !== recent || recent < 1) problems.push(`last-24 h filter shows ${await rows()} rows, the head says ${recent}`);
  await page.locator(`${FEED} button.md-chip`, { hasText: "Market-wide" }).click();
  const shown = await rows();
  const marketKinds = await page.locator(`${FEED} .feed .row .kind.mkt`).count();
  if (shown !== 10 || marketKinds !== 10) problems.push(`market-wide filter: ${shown} rows, ${marketKinds} market-wide (expected 10 and 10, page 1 of 12)`);
  await page.locator(`${FEED} button.md-chip`, { hasText: "Can carry a call" }).click();
  if ((await rows()) !== 1) problems.push(`can-carry filter shows ${await rows()} rows, expected 1`);
  if ((await page.locator(`${FEED} button.md-chip[aria-pressed="true"]`).count()) !== 1) problems.push("exactly one chip should be pressed");
  await page.locator(`${FEED} select[aria-label="Company"]`).selectOption("RELIANCE");
  const companyRows = await rows();
  const pressed = await page.locator(`${FEED} button.md-chip[aria-pressed="true"]`).count();
  if (companyRows < 1 || pressed !== 0) problems.push(`company filter: ${companyRows} rows, ${pressed} chips pressed (expected rows and none pressed)`);
  await page.locator('section[aria-label="By company"] .co button').first().click();
  if (!(await page.locator(`${FEED} select[aria-label="Company"]`).inputValue())) problems.push("rail count did not select a company");
  const external = await page.locator(`${FEED} a[target="_blank"]:not([rel~="noopener"])`).count();
  if (external) problems.push(`${external} article links without rel=noopener`);
  return problems;
}

export const cases = [
  {
    name: "news-india",
    path: "/india/news",
    mockup: "09-news",
    widths: [1280, 390],
    waitFor: ".mv",
    expectText: ["Market movers · last 3 days", "Last 3 days", "29 stories", "Coming up · 7 days", "RBI policy decision", "By company · 3 days", "Open article", "not verified per company"],
    expectSelector: [".mv .it .rk", ".feed .day", ".cal .ev.major", ".cos .co .mix", ".pager [aria-current='page']"],
  },
  { name: "news-india-filters", path: "/india/news", mockup: "09-news", widths: [1280], waitFor: ".mv", check: feedChecks },
  {
    name: "news-us",
    path: "/us/news",
    market: "us",
    mockup: "09-news",
    widths: [1280],
    waitFor: ".mv",
    expectText: ["JPMorgan results", "Market movers · last 3 days"],
    check: async (page) => {
      await page.locator(`${FEED} button.md-chip`, { hasText: "Can carry a call" }).click();
      return (await page.getByText("No story in the window is confirmed by a filing").count()) ? [] : ["US can-carry empty state missing"];
    },
  },
  {
    name: "news-empty",
    path: "/india/news",
    mockup: "09-news",
    widths: [1280, 390],
    waitFor: ".phead",
    api: async (rest, market) => {
      if (rest !== "news") return undefined;
      const p = mockupPayload("09-news", market);
      return { status: 200, body: envelope(market, "_", { ...p, news: [], calendar: [], window: { ...p.window, stored_in_window: 0 } }) };
    },
    expectText: ["No market-moving story in the last 3 days", "No story first seen in the last 3 days", "Nothing scheduled in the next 7 days", "No watchlist company has a story in the window"],
  },
];
