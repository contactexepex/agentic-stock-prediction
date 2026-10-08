# Cockpit design workspace

The design track of docs/SPEC.md (section 10 "Design track", decisions 32 and 48): the owner designs the 12 pages of
SPEC section 6 with Fable, one page at a time, as HTML mockups built from W1's data catalogue
(docs/DATA_CATALOGUE.md, example records in `design/catalogue/`). The approved mockups decide the API contract:
each page's `data.json` becomes the payload of its endpoint (Wave 3, session B4), and the frontend (Wave 4, B7)
implements the mockups as React components on the design system.

## Rules for every mockup (the agreement)
- **Catalogue data only.** `design/mockups/<NN-page>/data.json` holds the page's full payload, composed only of
  catalogue fields with the example files' values, marked as examples, with `as_of`, `cutoff` and `built_at`. A
  field the catalogue lacks is a new data request: the owner approves it, then W1 adds it (judged); this track never
  edits `design/catalogue/`.
- **Builder -> JSON -> template.** `build.py` composes `data.json` and inlines it into `template.html` to give the
  self-contained `page.html`; no hard-coded number in the template; the build is deterministic (no wall clock).
- **Design system** in `design/system/` (tokens, components, icons, `system.py`); no page-local colours, no CDN, no
  external font or request. Light theme, phone (390 px) and desktop (1280 px), never colour alone, keyboard usable,
  plain language, Paper labels on every signal, "No proven strong signals today" until proven, research only,
  horizon selector N+1..N+5 opening on N+1 (decision 39).
- **Checks.** `node design/system/check_page.js <page.html> <dir> <prefix>` (console errors, horizontal overflow,
  external requests, screenshots at 1280 and 390 px) and `node design/system/check_text.js <page.html>` (clipped,
  overflowing and overlapping text at twelve widths, both markets).
- **Deliverables per page:** `build.py`, `template.html`, `data.json`, `page.html`, `rationale.md` (layout choices,
  what the owner approved), `notes.md` (every catalogue entity and field used), screenshots at 1280 and 390 px.
- **Approval and landing.** The owner approves each page; the `judge` subagent reviews the folder (catalogue fields
  only, reproducible build, checks pass, claims true); the verdict goes to `judgments/log.jsonl`; the page is merged
  to main by this track (no pull request) and the orchestrator is told.

## Pages (SPEC section 6)
| # | Page | Folder | Status |
|---|---|---|---|
| 1 | Home | `mockups/01-home/` | approved by the owner (2026-10-08, with "fix the clipped and overlapping text"); judge PASS round 3 at a0467b2; on main |
| 2 | Watchlist | `mockups/02-watchlist/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at b1c9127; on main; cosmetic issues #152-#155 |
| 3 | Company | `mockups/03-company/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at 8912657; on main |
| 4 | Stock strategies | `mockups/04-stock-strategies/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at ca019cd; on main |
| 5 | Strategy lab | `mockups/05-strategy-lab/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at a7c4ff3 and, reading W1's back-test rows on the Back-test basis, PASS round 4 at 4d03deb, and reading W1's heatmap cells and cumulative lines PASS round 2 at 5c5c60b; on main; cosmetic issues #197-#207, #219-#221, #223-#224 |
| 6 | Rule vs AI | `mockups/06-rule-vs-ai/` | built on the owner's delegated authority (2026-10-08); judge PASS round 4 at e0d2b7d and, rebuilt on W1's W40 research reviews, round 7 at 821298d; on main; cosmetic issues #179-#189 |
| 7 | Paper portfolios | `mockups/07-paper-portfolios/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at 5d22863; on main; cosmetic issues #190-#193 |
| 8 | Track record | `mockups/08-track-record/` | built on W1's `track_record` entity (2026-10-08); judge PASS round 2 at 17c5c6f; on main; cosmetic issues #213-#216 |
| 9 | News | `mockups/09-news/` | built on the owner's rules of 2026-10-08 (the last 3 days, the market movers first, every story linking to its article, the calendar and the companies in a rail) and W1's data request 8; judge PASS round 2 at 163963a; on main; cosmetic issues #225-#226 |
| 10 | Companies | `mockups/10-companies/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at 23c56a4; on main; cosmetic issues #194-#196 |
| 11 | Assistant | `mockups/11-assistant/` | built on W1's `assistant_answer` entity (2026-10-08); judge PASS round 2 at 656b699 and, rebuilt on W1's data request 7 (answers asked before the cut-off), round 3 at 437a891; on main; cosmetic issues #217-#218 |
| 12 | Help | `mockups/12-help/` | built on the owner's delegated authority (2026-10-08); judge PASS round 3 at 962b8dc; on main; cosmetic issues #208-#212 |

Order: the spec's, proposed to the owner with Home first.

## Decisions taken on the owner's behalf (2026-10-08, for the morning review)

The owner delegated the remaining pages ("go with your recommendation, notify the orchestrator"). Each page's
`rationale.md` has the full list under "Decisions taken for the owner"; this is the one-place summary.

| Page | Decisions |
|---|---|
| 1 Home | Approved by the owner directly (Materialize-style admin layout; the decision-51 cost labels added later with the Stock strategies page). |
| 2 Watchlist | The table is the page, no second chart; the visual parts are the stacked agreement bar, the odds meter, the buyers-by-horizon bars and the range bar. Inactive companies are not rows (decision 13): named once under the table with a link. |
| 3 Company | Opens with a decision card (today's numbers a retail investor can act on, with one plain-words line), not the chart. The chart projects the reference strategy's ranges as a fan to N+5 and shows every strategy's target at the selected horizon as a spread, not fifteen lines. The open-trade and settlement tables sit full width above the two-column part. The "why it moved" split is a diverging bar per trade. Change amount / deactivate are confirm dialogs recording a pending request; delete is left to the Companies page. |
| 4 Stock strategies | Agreement is a chart (grouped stacked bars per horizon), not a table. The ranked table shows each strategy's prediction at the selected horizon only; the horizon tabs switch it. |
| 5 Strategy lab | One scoreboard for all 15 strategies with the baselines in the list, ranked on market cost with your cost beside it and a cost switch. The luck test is a bar with a three-valued word: "edge" (corrected interval above zero), "luck?" (includes zero), "loss" (wholly below zero). The strategy detail is the comparison with the reasoning (the one setting that differs, both values, the go-live checklist). Four heatmaps with the numbers in the cells, a Profit / Win rate switch and a week picker on W1's cells; the regime map is the scoreboard's (all weeks). Back-test is a switch, never on the same table as forward: the run's facts above the table, "not run" for strategies the engine cannot run, "not stored" for your-cost figures it lacks, compact lakh/crore figures in the cells. |
| 6 Rule vs AI | Opens with a two-sided scorecard and a one-word verdict with the luck test drawn. Matches per company-day and pick rule, a draw when both families made the same trade. The weekly review card reads only reviews written by the cut-off (the W40 ones). The per-company comparison is summed from the trades (no per-company head-to-head scoreboard row exists; W1 answered with heatmap cells at market cost). |
| 7 Paper portfolios | Two family boxes with the pick-rule portfolios inside, not a four-row table. Open trades grouped by strategy with family and view filters, reusing Home's row design. The euro view as four tiles with the formula in tooltips and the "fee provisional, verify" note. Adding an own paper trade is a dialog recording a pending request with the WS4 price rule. |
| 8 Track record | The signal model's skill verdict leads as a band with the review it comes from. Every hit rate carries its Wilson interval as a bar with the always-up tick. Calibration is a chart with the diagonal plus the bands' table. Scoring bases one at a time, never pooled; legacy windows tagged. Empty states say what is missing (no range scored, no replay, the weekly series not in the read model: a request to B4). |
| 9 News | Built on the owner's rules of 2026-10-08. The movers are a ranked band above the feed (the engine's market-moving flag first, then market-wide, results, materiality, newest; a headline stored twice shows once); the feed is one list grouped by day with filter chips and a pager; the rail holds the week's calendar and the companies in the news; market-wide stories carry "not verified per company" because verification is per company. Home's news card became the window's top 5 movers with a link to the News page. |
| 10 Companies | Active and inactive companies as two tables. Every write is a dialog ending in a recorded pending request; delete behind a typed confirmation, dashboard-only (F8.5); the add flow shows the F8.7 summary step. A company deleted later is masked everywhere, command keys and record ids included (decision 12). On phones the row actions collapse into one Manage button; deactivate / reactivate take an optional reason. |
| 11 Assistant | A chat with the sources under each answer and a records panel beside it. Every answer carries a visible state (answered / not in the data / declined). The conversation is filtered on the asking time, as every page filters on a record's write time (W1 re-dated the examples before the cut-off at the track's request). The budget is the spec's caps with an honest "spend not in the example data" note. Long record ids wrap in full. |
| 12 Help | One scrolling page with an anchor chip row, not tabs. The strategy list, the go-live checklist and the agreement example come from the catalogue. Sample visual parts are drawn with the pages' own helpers and labelled "sample". The judge made the track correct several system statements (D = the entry session; only freely accessible vetted pages are read; which pages carry the signals band; what is hand-entered). |

Shared: new named spec constants in `mockups/_shared/shell.js` (the 60-word reason limit; the assistant's 500
characters, $0.65 a day, $20 a month, 90 days), each with its source.

## Design system
`system/`: scheme v2 "modern admin light" (2026-10-08; `system/README.md`): the look of modern admin templates the
owner pointed at (Pixinvent Materialize with its semi-dark vertical menu, Aurora) on a broker-style cockpit, with
the owner's rules kept (NO red; YES green, darker when strong; never colour alone; Paper everywhere). Style guide
`system/styleguide.html`.

## Earlier design round (reference only)
`decision/`, `home/`, `watchlist/`, `portfolio/`, `track/`, `help/` are the pages of the first design round
(2026-10-07), built from the repo's stored data on the previous scheme ("terminal light"); their built HTML files keep
an inlined copy of that scheme, and rebuilding them would inline scheme v2. They are visual reference for the
mockups, not part of the deliverable. `reference/` holds earlier rejected iterations (v2) for context only.
