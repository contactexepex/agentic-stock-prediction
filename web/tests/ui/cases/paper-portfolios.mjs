// UI cases of page 07, the Paper portfolio (B16's page, v3 by UX3: docs/ux/paper_portfolio_redesign.md). The real
// stored data of India built at Mon 12 Oct 2026, 18:31 IST (tests/ui/ux3/, rm.portfolio `_` and `open:1`..`open:5`, LT's
// company and lifecycle pages): the hero, the sides compared, the hold blocks with their reason lines (no tabs), the
// Rule vs AI picks, what the system learns and the "Full story" view; a finished day made from the 1-day hold's trades
// (an illustration of the layout: nothing had finished that day); the US with no trades (empty states); a read model
// from before UX3; the add-trade form against POST /paper-trades (pending, a refusal, a retry with the same key); and
// the error state. The POST is answered in the test; nothing reaches any inbox.
import { readFileSync } from "node:fs";
import { storedApi } from "../b16/stored.mjs";
import { envelope } from "../fixtures.mjs";

const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of (422|503)/;
const PAPER = "Not proven yet: these are tests, not tips.";
const fixture = (name) => JSON.parse(readFileSync(new URL(`../ux3/${name}.json`, import.meta.url), "utf8"));
const CUTOFF = "2026-10-12T13:01:00Z";
const served = (p) => {
  const out = { ...structuredClone(p), cutoff: CUTOFF, built_at: CUTOFF };
  if (out.status) out.status = { ...out.status, freshness: { state: "fresh", built_at: CUTOFF, age_minutes: 0 } };
  return out;
};

/** India's real pages; `edit` may change the market page and the hold pages before they are served. */
function realApi({ edit = (p) => p, finished = null } = {}) {
  return (rest, market) => {
    if (rest === "portfolios") return { status: 200, body: envelope(market, "_", edit(served(fixture(`${market}-portfolio`)))) };
    const hold = /^portfolios\/open\/([1-5])$/.exec(rest);
    if (hold) {
      try {
        return { status: 200, body: envelope(market, `open:${hold[1]}`, served(fixture(`${market}-open-${hold[1]}`))) };
      } catch {
        return { status: 404, body: { title: "Not found", status: 404, detail: "No open trade of this hold." } };
      }
    }
    const day = /^portfolios\/finished\/(\d{4}-\d{2}-\d{2})$/.exec(rest);
    if (day) return finished && finished[day[1]] ? { status: 200, body: envelope(market, `finished:${day[1]}`, finished[day[1]]) } : { status: 404, body: { title: "Not found", status: 404, detail: "No such session." } };
    if (rest === "stocks/LT") return { status: 200, body: envelope(market, "LT", served(fixture("india-stock-LT"))) };
    if (rest === "stocks/LT/lifecycle/2026-10-12") return { status: 200, body: envelope(market, "LT:2026-10-12", fixture("india-lifecycle-LT-2026-10-12")) };
    return undefined;
  };
}

/** A finished day made from India's real 1-day hold (an illustration of the layout: those trades had not sold yet): as
 * if each sold at its latest price, after a sample fee of 0.24%, with B2's automatic reason from its latest check;
 * the biggest loss carries an end-of-day AI reason. */
function finishedDay() {
  const rows = fixture("india-open-1").trades.map((t) => {
    const fee = Math.round(t.entry_price * t.quantity * 0.0024);
    const net = Math.round((t.unrealised_pnl - fee) * 100) / 100;
    const w = t.why ?? {};
    return {
      ...t, state: "closed", outcome: net > 0 ? "win" : net < 0 ? "loss" : "flat", pnl_market: net, pnl_your: net - 400,
      return_pct_market: t.unrealised_pct, exit_date: "2026-10-13", settled_at: "2026-10-13T12:20:00Z", check: null, sessions: null,
      why: { source: "settlement", check_at: null, session_date: "2026-10-13", move_pct: w.move_pct ?? null, market_pct: w.market_pct ?? null,
        sector_pct: w.sector_pct ?? null, own_pct: null, news_pct: 0, company_pct: w.own_pct ?? null, beta: null, sector_source: null,
        reason_code: w.own_pct !== undefined && Math.abs(w.own_pct) > Math.abs(w.market_pct ?? 0) ? "company" : "market", note: null,
        ai_reason: null },
    };
  });
  const worst = rows.reduce((a, b) => (b.pnl_market < a.pnl_market ? b : a));
  for (const r of rows) if (r.ticker === worst.ticker) r.why.ai_reason = `${r.ticker} fell more than the market on the day: most of the drop was the company’s own.`;
  const count = (rs) => {
    const closed = rs.filter((r) => r.state === "closed"), sum = (xs) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) * 100) / 100 : null);
    return { closed: closed.length, wins: closed.filter((r) => r.outcome === "win").length, losses: closed.filter((r) => r.outcome === "loss").length,
      flat: closed.filter((r) => r.outcome === "flat").length, net_pnl_market: sum(closed.map((r) => r.pnl_market)), net_pnl_your: sum(closed.map((r) => r.pnl_your)) };
  };
  const summary = { session_date: "2026-10-13", not_entered: 0, ...count(rows), by_family: ["rule", "ai", "baseline"].map((family) => ({ family, ...count(rows.filter((r) => r.family === family)) })) };
  return { summary, page: { market: "india", as_of: "2026-10-13", session_date: "2026-10-13", summary, trades: rows, paper: true } };
}

const textOf = (page, sel) => page.textContent(sel).catch(() => "");

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
    name: "paper-portfolio-v3-india",
    path: "/india/paper-portfolios",
    market: "india",
    api: realApi(),
    widths: [1280, 390],
    waitFor: ".pp-hold .pp-trades",
    expectText: [PAPER, "Which bets are working?", "Rule strategies", "Simple benchmarks", "AI traders", "No trades today: the signal model saw no clear rise",
      "Nothing finished yet — first results Tue 13 Oct", "Rule vs AI: the daily picks", "Open trades, by how long they’re held", "1-day hold", "2-day hold", "3-day hold", "4-day hold", "5-day hold",
      "Going against the prediction", "Going as predicted", "Full story", "What the system learns", "Learns automatically", "Needs the owner’s approval", "2026-W41", "Your own paper trades"],
    expectSelector: [".pp-hero .pp-money.big", ".pp-strip .pp-ss", ".pp-why-line", ".pp-trades .rng svg", ".pp-wl .w", ".pp-wl .l"],
    check: async (page) => {
      const problems = [];
      await page.waitForFunction(() => document.querySelectorAll(".pp-hold .pp-trades").length >= 7, null, { timeout: 8000 }).catch(() => problems.push("not every hold block loaded its list"));
      if ((await page.$$('[role="tab"]')).length) problems.push("a tab on the page: the holds must all be visible");
      const blocks = await page.$$eval(".pp-hold h3", (hs) => hs.map((h) => h.textContent.trim()));
      if (blocks.join("|") !== "1-day hold|2-day hold|3-day hold|4-day hold|5-day hold|3-day hold|5-day hold") problems.push(`hold blocks: ${blocks.join(" | ")}`);
      const text = await textOf(page, ".p-portfolios");
      if (/NaN|undefined|\bnull\b/.test(text)) problems.push("NaN, undefined or null printed");
      if (/Baseline/.test(text.replace(/Baselines?\b(?= ·)/g, ""))) problems.push("the internal word Baseline shows");
      // every losing line of the first block says why, with a market or own move in percent and a Full story link
      const lines = await page.$$eval(".pp-hold:first-of-type .pp-why-line", (ls) => ls.map((l) => l.textContent));
      if (!lines.length) problems.push("no reason line in the 1-day block");
      for (const l of lines) if (!/(Fell|Rose) (mostly on its own|with the whole market)/.test(l) || !/−?\d+\.\d%/.test(l) || !l.includes("Full story")) problems.push(`reason line: ${l}`);
      const story = await page.$eval(".pp-hold .pp-why-line a.pp-story", (a) => a.getAttribute("href")).catch(() => "");
      if (!/^\/india\/stocks\/[A-Z&]+\/lifecycle\/2026-10-12#story=.+&trade=acc%3A/.test(story)) problems.push(`full story link: ${story}`);
      // "Show N more" reveals the rest of a list and folds it back
      const first = await page.$(".pp-hold .pp-more button");
      if (!first) problems.push("no Show more button");
      else {
        const before = await page.$$eval(".pp-hold:first-of-type tbody.pp-row", (r) => r.length);
        await first.click();
        const after = await page.$$eval(".pp-hold:first-of-type tbody.pp-row", (r) => r.length);
        if (after <= before) problems.push(`show more: ${before} -> ${after}`);
        await first.click();
      }
      // identical trades of two benchmarks are one line marked ×2, with both strategies named
      if (!(await page.$$eval(".pp-x", (xs) => xs.some((x) => x.textContent === "×2")))) problems.push("no merged ×2 line");
      const tips = await page.$$eval(".pp-hold .pp-info", (bs) => bs.map((b) => b.getAttribute("data-tip") ?? ""));
      if (!tips.some((t) => t.startsWith("Expected: ") && t.includes("Sells at the close of"))) problems.push("row popover words");
      return problems;
    },
  },
  {
    name: "paper-portfolio-v3-finished",
    path: "/india/paper-portfolios",
    market: "india",
    widths: [1280, 390],
    api: (() => {
      const day = finishedDay();
      return realApi({ finished: { "2026-10-13": day.page }, edit: (p) => ({ ...p, all_trades: { ...p.all_trades, finished_sessions: [day.summary] } }) });
    })(),
    waitFor: "[aria-label='Finished trades'] .pp-trades",
    expectText: ["Finished trades", "Tue 13 Oct · 39", "Won", "Lost", "AI reason", "Nothing finished that day"],
    check: async (page) => {
      const problems = [];
      const card = await textOf(page, "[aria-label='Finished trades']");
      if (!/Moved −\d+\.\d%, mostly (the whole market|the company itself)/.test(card)) problems.push("no finished reason line");
      if (!card.includes("won") || !card.includes("lost")) problems.push("no won / lost per side");
      return problems;
    },
  },
  {
    name: "paper-portfolio-v3-us-empty",
    path: "/us/paper-portfolios",
    market: "us",
    api: realApi(),
    widths: [1280, 390],
    waitFor: ".pp-hero",
    expectText: [PAPER, "Nothing has finished yet", "No open paper trade right now", "No open daily pick right now", "What the system learns", "2026-W41"],
  },
  {
    name: "paper-portfolio-v3-story",
    path: "/india/stocks/LT/lifecycle/2026-10-12#story=ai.news_results.sonnet.v1%3A2026-10-09-LT-5d&trade=acc%3Aai.news_results.sonnet.v1%3A2026-10-09-LT-5d",
    market: "india",
    api: realApi(),
    widths: [1280, 390],
    waitFor: "[aria-label='The full story']",
    expectText: ["Why is it going against the prediction?", "Whole market", "LT on its own", "What happened, step by step", "Chance of a rise 55%", "(its bar: 55%)",
      "Exchange-confirmed large order wins", "AI note, checked against the stored data", "Sells at the close and is settled", "What the system learned",
      "This strategy doesn’t get lessons", "Needs the owner’s approval"],
    check: async (page) => {
      const problems = [];
      const story = await textOf(page, "[aria-label='The full story']");
      if (/NaN|undefined|\bnull\b/.test(story)) problems.push("NaN, undefined or null printed");
      if (!/Check: −\d+\.\d% since the buy/.test(story)) problems.push("no check step with the move since the buy");
      const steps = await page.$$eval(".st-tl li", (ls) => ls.length);
      if (steps < 5) problems.push(`steps: ${steps}`);
      return problems;
    },
  },
  {
    name: "paper-portfolio-old-read-model",
    path: "/india/paper-portfolios",
    api: storedApi,
    widths: [1280],
    waitFor: ".p-portfolios [aria-label='Your own paper portfolio']",
    expectText: [PAPER, "This page fills after the next data sync of India (NSE)", "No own paper trade in India (NSE) yet."],
  },
  { name: "paper-portfolio-us-euro", path: "/us/paper-portfolios", market: "us", mockup: "07-paper-portfolios", widths: [1280], waitFor: ".p-portfolios .eur", expectText: [PAPER, "Euro view of AAPL", "Euros paid"] },
  {
    name: "paper-portfolios-add-trade",
    path: "/india/paper-portfolios",
    widths: [1280, 390],
    allowConsole: [HTTP_ERROR_LINE],
    waitFor: ".p-portfolios [aria-label='Your own paper portfolio']",
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
  { name: "paper-portfolios-error", path: "/india/paper-portfolios", apiStatus: 503, allowConsole: [HTTP_ERROR_LINE], widths: [1280], waitFor: '[role="alert"]', expectText: ["Data service unavailable", "Try again"] },
];
