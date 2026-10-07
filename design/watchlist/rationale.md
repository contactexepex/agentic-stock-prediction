# Watchlist screen: rationale

Files: `template.html` + `build.py` (`--market india|us --out DIR`), `watchlist-india.html`, `watchlist-us.html`
(self-contained, no network), `data-india.json` (everything the India page shows), screenshots `shot-*.png`,
`notes.md` (queries). Same shell and "terminal light" design system as the decision page (`design/system/`).

## What it is for
The list the owner opens to pick a company: the market's 20 watchlist companies, aggregated, one row each, in
plain language and icons; the detail lives on the company decision page (a click on a row). It answers, in order:
is there anything to do today (banner), what is the market doing (header tiles), and which company deserves a
look (the table, sortable and filterable).

## Layout
1. **Shell**: rail (Watchlist current), top bar with the market and the India/US segmented control, ticker tape
   of the 20 companies (last close and day move; each item links to the company page).
2. **Market header**: title, session status, LIVE DATA / PAPER tags, as-of date, last model run time; six tiles:
   regime and today's major events, benchmark close and move (live quote at the run where stored), vol index,
   FII/DII flows (India) or live calls scored (US), calls today (YES count, abstentions, blocked), model skill
   (the weekly review's verdict).
3. **Signals banner**: "No proven strong signals today" with the Paper candidates at or above the 60% call line
   (none on 6 Oct), or the YES calls in green when live calls exist.
4. **Toolbar**: filter box, sector chips (with the sector index's day move where stored), sort select; column
   headers sort too.
5. **Table**, grouped by sector by default (sector index row with its day and 5-day move): company (symbol box,
   name, sector), last close, day and 5-day move in green/red with the sign, 20-session sparkline, chance up 1d
   and 5d (odds meter on a 30–70 track), verdict pill (NO red; YES green by strength, with a Paper tag), the
   latest published 5-day range drawn around the last close, "80% held" (rule replay coverage over the back-test
   window, amber below 75%), next results (days, red when within 1 day), news in 72 hours (count, high-materiality
   count, best verification badge), the overnight cue (ADR / pre-market). Narrow widths hide the 5-day chance and
   the cue (below 1440 px), then the sparkline and coverage (below 1000 px), then 5-day move, range and news on
   phones; the phone keeps company, last, day, chance 1d, verdict and next results.
6. **Legend** and the collapsed data-sources panel.

## Real, back-test, derived, coming
- Live: every number from the stored rows (prices, model_scores_latest, ranges_latest, features_latest,
  agent_reasoning, predictions/outcomes, quotes_latest, regime, events, news + news_verified, flows, reviews).
- Back-test: "80% held" from the rule replay over the same 35-session window as the decision page.
- Derived: verdict strength (confidence >= 0.75 or anchored probability >= 0.65), Paper candidates (>= 60%),
  blocked (quality BLOCKED or results within 1 day), the sector net move labels.
- Coming (marked): cross-market symbol search, the live market switch, the other rail sections.
- Not invented: a missing value is a dash ("no sector index stored", "none stored").

## Checked
Playwright, pre-installed Chromium, 1280 and 390 px, both markets: no console errors, no horizontal scroll, no
external requests. Row click and Enter open `../decision/decision-<TICKER>.html` (built for HDFCBANK, ICICIBANK,
AAPL so far; the consolidation session generates all 40).
