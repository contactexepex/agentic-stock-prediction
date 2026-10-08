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
| 5 | Strategy lab | `mockups/05-strategy-lab/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at a7c4ff3 and, reading W1's back-test rows on the Back-test basis, PASS round 4 at 4d03deb; on main; cosmetic issues #197-#207, #219-#221 |
| 6 | Rule vs AI | `mockups/06-rule-vs-ai/` | built on the owner's delegated authority (2026-10-08); judge PASS round 4 at e0d2b7d and, rebuilt on W1's W40 research reviews, round 7 at 821298d; on main; cosmetic issues #179-#189 |
| 7 | Paper portfolios | `mockups/07-paper-portfolios/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at 5d22863; on main; cosmetic issues #190-#193 |
| 8 | Track record | `mockups/08-track-record/` | built on W1's `track_record` entity (2026-10-08); judge PASS round 2 at 17c5c6f; on main; cosmetic issues #213-#216 |
| 9 | News | | the owner decided in the earlier round to fold the news into Home (the news card) and the Company page; to be confirmed |
| 10 | Companies | `mockups/10-companies/` | built on the owner's delegated authority (2026-10-08); judge PASS round 2 at 23c56a4; on main; cosmetic issues #194-#196 |
| 11 | Assistant | `mockups/11-assistant/` | built on W1's `assistant_answer` entity (2026-10-08); judge PASS round 2 at 656b699 and, rebuilt on W1's data request 7 (answers asked before the cut-off), round 3 at 437a891; on main; cosmetic issues #217-#218 |
| 12 | Help | `mockups/12-help/` | built on the owner's delegated authority (2026-10-08); judge PASS round 3 at 962b8dc; on main; cosmetic issues #208-#212 |

Order: the spec's, proposed to the owner with Home first.

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
