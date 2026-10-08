// UI cases of page 06, Rule vs AI (B16), at the mockup's widths (design/mockups/06-rule-vs-ai/shot-*-full.png): the
// mockup's data (its research review served by /review, with a news-impact row), the stored data of today, the cost
// switch, a review read that fails on its own, and the error state.
import { storedApi } from "../b16/stored.mjs";
import { envelope, mockupPayload } from "../fixtures.mjs";

const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of 503/;
const PAPER = "No proven strong signals today";

/** /review from the mockup: its reviews and review_due (the handover's rm.review), plus one news-impact row. */
function mockupReview(rest, market) {
  if (rest !== "review") return undefined;
  const p = mockupPayload("06-rule-vs-ai", market);
  const impact = [{ id: `ni-${market}-2026-W40-results`, market, iso_week: "2026-W40", event_type: "results", status: "confirmed_primary", materiality: "high", horizon_days: 1, n_events: 3, mean_abnormal_pct: 1.24, ci_low_pct: -0.4, ci_high_pct: 2.9, enough: false, computed_at: "2026-10-03T04:00:00Z" }];
  return { status: 200, body: envelope(market, "_", { market, name: p.name, currency: p.currency, as_of: p.as_of, reviews: p.reviews, review_due: p.review_due, news_impact: impact }) };
}

/** The mockup with an AI trade of 2 Oct that never entered (no stored open), as B2 stores it: status no_entry, no profit. */
function withNoEntry(rest, market) {
  if (rest === "review") return mockupReview(rest, market);
  if (rest !== "compare") return undefined;
  const p = structuredClone(mockupPayload("06-rule-vs-ai", market));
  const base = p.trades.find((t) => t.family === "rule");
  p.trades.push({ ...base, trade_id: "h2h:x:no-entry", strategy_id: "ai.combined.opus.v1", family: "ai", entry_date: "2026-10-02", status: "no_entry", net_pnl: null, return_pct: null, exit_price: null, target_reached: null, target_error_pct: null });
  p.trades.push({ ...base, trade_id: "h2h:x:rule-0210", entry_date: "2026-10-02", exit_date_actual: base.exit_date_actual });
  return { status: 200, body: envelope(market, "_", p) };
}

export const cases = [
  {
    name: "rule-vs-ai-india",
    path: "/india/rule-vs-ai",
    mockup: "06-rule-vs-ai",
    api: mockupReview,
    widths: [1280, 390],
    waitFor: ".p-compare .rev .lead-row",
    expectText: [PAPER, "Head-to-head: the strongest rule strategy vs the strongest AI trader", "Level", "Today’s picks for", "not viable at your cost", "Match by match", "draw", "Gain-pick vs probability-pick", "Per company", "Why: the end-of-day analyst", "The week’s research review", "No proposals this week.", "confirmed primary · high · 2026-W40", "too few"],
    expectSelector: [".p-compare .luck svg, .p-compare .vs", ".p-compare .mb-chart svg", ".p-compare .pk .mb-odds"],
  },
  { name: "rule-vs-ai-us", path: "/us/rule-vs-ai", market: "us", mockup: "06-rule-vs-ai", api: mockupReview, widths: [1280], waitFor: ".p-compare .rev h3", expectText: [PAPER, "$"] },
  {
    name: "rule-vs-ai-your-cost",
    path: "/india/rule-vs-ai",
    api: mockupReview,
    widths: [1280],
    waitFor: ".p-compare .mt",
    check: async (page) => {
      await page.click('[aria-label="Costs"] button:has-text("Your cost")');
      const text = await page.textContent(".p-compare");
      const problems = [];
      if (!text.includes("after your cost")) problems.push("cost switch did not change the words");
      if (!text.includes("+₹575")) problems.push("your-cost figure of the match (+₹575) missing");
      return problems;
    },
  },
  {
    name: "rule-vs-ai-no-entry",
    path: "/india/rule-vs-ai",
    api: withNoEntry,
    widths: [1280],
    waitFor: ".p-compare .mt",
    expectText: ["did not enter (no stored open on the entry day)", "no match", "1 match: rule 0, AI 0, draw 1"],
    check: async (page) => {
      const perCompany = await page.textContent('[aria-label="Per company"]');
      return perCompany.includes("1 trade · 1 won") && perCompany.includes("2 trades · 2 won") ? [] : [`per-company sums count the unentered trade: ${perCompany}`];
    },
  },
  {
    name: "rule-vs-ai-stored-india",
    path: "/india/rule-vs-ai",
    api: storedApi,
    widths: [1280, 390],
    waitFor: ".p-compare .rev",
    expectText: [PAPER, "Nothing settled yet in the head-to-head view.", "No head-to-head picks stored for the session.", "No settled head-to-head trade yet.", "No end-of-day analysis stored by the cut-off.", "No weekly review written by the cut-off. The next one (2026-W41)", "No news-impact study computed by the cut-off."],
  },
  {
    name: "rule-vs-ai-review-down",
    path: "/india/rule-vs-ai",
    api: (rest) => (rest === "review" ? { status: 503, body: { title: "Data service unavailable", status: 503, detail: "The read models cannot be read right now." } } : undefined),
    allowConsole: [HTTP_ERROR_LINE],
    widths: [1280],
    waitFor: '.p-compare .rev [role="alert"]',
    expectText: ["Match by match", "Data service unavailable", "Try again"],
  },
  { name: "rule-vs-ai-error", path: "/india/rule-vs-ai", apiStatus: 503, allowConsole: [HTTP_ERROR_LINE], widths: [1280], waitFor: '[role="alert"]', expectText: ["Data service unavailable", "Try again"] },
];
