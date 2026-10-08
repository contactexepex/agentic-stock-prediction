# Home mockup: rationale

Page 1 of docs/SPEC.md section 6 (decisions 30 and 39), designed in the design track from W1's data catalogue
(docs/DATA_CATALOGUE.md, design/catalogue/*.json). Status: **awaiting the owner's approval** (third version,
2026-10-08). History: v1 was flat cards on the "terminal light" tokens; v2 the dense terminal look of the earlier
design round; v3 moves the design system itself to scheme v2 "modern admin light" after the owner pointed at
modern admin templates (Pixinvent Materialize with its semi-dark vertical menu, Aurora) and asked for an open,
modern, easy-to-read cockpit in the manner of popular broker and stock-monitoring platforms.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html`), `data.json` (the example payload of
`GET /api/v1/markets/{market}/home`, read model `rm.home`, one payload per market), `page.html` (self-contained, the
design system inlined, no request leaves the page), `notes.md` (every catalogue entity and field used), screenshots
`shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png` (India, N+1), `shot-us-1280-full.png` (US),
`shot-us-1280-n5.png` (horizon N+5 selected), `shot-1280-top.png` (the top of the desktop page at 2x),
`shot-1280-trades.png` (the trades table at 2x), `shot-1024-full.png` and `shot-768-full.png` (laptop and tablet
widths), `shot-390-h2h.png`, `shot-390-agree.png`, `shot-390-trades.png` (phone cards).

## What the page is for
The first screen of the morning, one market at a time (the India/US switch in the top bar; the real app navigates
between `/markets/india/home` and `/markets/us/home`, the mockup embeds both payloads). It answers, in order: is
anything proven yet (no: the banner), who agrees today and at which horizon, which paper trades compete today and
whether any clears costs, what is flagged right now, who is ahead (rule vs AI), what is open, and whether the runs
worked.

## The look
Scheme v2 of design/system/ ("modern admin light", README there): a soft light-grey page, white cards lifted by
a faint shadow instead of hairlines, one periwinkle-indigo accent, a dark navy sidebar with labels (collapsed to
icons between 600 and 1199 px, a drawer plus a bottom bar on phones), icon tiles on the KPI cards, label badges
(tint plus ink), pill tabs, a gradient area chart, generous spacing. Kept from the owner's rules: NO red, YES green
in two shades, every up/down with its sign, every status with a glyph and a word, Paper everywhere, the odds meter
and the range bar. Text tones stay AA on white (figures in tokens.css).

## Layout (desktop 1280 px: two columns, then a full-width table; phone 390 px: one column in the same order)
1. **Shell**: the semi-dark sidebar with the 10 market-level pages of the spec (Company and Stock strategies are
   reached from company rows, not from the menu) and a foot with the Paper label; top bar with a menu button
   (phone), the page title, a search field, the market pill switch and a filled **Ask** button (the assistant side
   panel of page 11). Phone: a bottom bar with Home, Watchlist, Strategy lab, Rule vs AI and **More**, which opens
   the sidebar as a drawer (scrim, Escape closes).
2. **Page head**: the session being predicted (D) as the title, a one-line subtitle, and chips: open/closed (with the
   session times in the tooltip), regime, freshness (state and build time, tooltip with the cut-off), PAPER.
3. **Alert band** "No proven strong signals today": the catalogue's `paper_label`, the number of strategies and the
   go-live bar's position (`go_live` of the scoreboard). It stays until a strategy is proven (F7); only then may a
   Strong signal appear (owner's direction, SPEC section 6).
4. **KPI cards** (four, icon tiles): most agreed company at the selected horizon with its "n of N buy" label and the
   buyers' average chance; head-to-head trades today with "clears costs / none clears costs"; open paper trades
   with their unrealised total; alerts (flagged of checked, or "no check yet"). Counts and sums of the payload.
5. **Horizon selector** N+1..N+5, pill tabs in the agreement card's head, opening on N+1 (decision 39); a
   plain-language reading of the selected horizon sits under the title. It drives the ranking and the first KPI.
6. **Who agrees (top 5 by agreement)** (decision 30; the example files hold 3 active companies per market, so the mockup ranks 3):
   rank, symbol box, ticker (a link to the stock strategies page, page 4), name, last close and day move, "12 of 15
   strategies buy at N+1" over a **stacked bar by family** (rule / baselines / AI in the three chart colours of the
   system, with the counts), a **buyers-by-horizon mini bar chart** (N+1..N+5 counts, the selected horizon dark),
   which shows the strongest other horizon of decision 39 at a glance, and the average chance of a rise as an
   **odds meter** (30-70 track, the dot right of the midpoint = above a coin flip; "no probability" when only
   always-buy and follow-yesterday buy). Empty state: "No strategy buys any company at N+k today".
7. **Today's head-to-head trades** (decisions 41-42): per company, the amount per trade (override marked), then
   Rule | AI boxes naming the family's strongest strategy and its ranking basis (tooltip), one row per pick rule
   (best expected gain, highest probability): horizon chip, the chance of a rise as an odds meter, the expected gain
   after costs in money and in percent with a tick/cross **clears costs / below costs** (F9's viability rule:
   expected gain after costs above zero), and the three inputs (to target, downside to the 80% range's low, costs).
   "Why these horizons" opens the candidate table (every buyable horizon with the same numbers). The summary line
   counts the trades and says "No pick clears costs today" when none does. A company with no candidate says so
   (HDFC Bank in the example).
8. **Alerts** (side column, first): the flagged rows of the latest intraday check, grouped by company: what is
   flagged, price and move since entry at the check time, the trades concerned. Empty states: no check stored yet
   today (US in the example: the cut-off is before the first US check), or nothing flagged.
9. **Rule vs AI** (side column, first): a **cumulative profit chart** (gradient area lines per family: rule, AI,
   baselines; the settled paper trades of the accuracy view added up by settlement day; hover or focus a day for
   every family's figure), *last close* from the end-of-day analysis (family tiles with trades won and net profit,
   the leader in the accent tint and marked "led"; the analyst's summary with a link to the reasons), and *to date*
   as the head-to-head grid family x pick rule (net profit, trades, win rate, "too few to rank" under 20 trades).
10. **News that can carry a call** (the owner's decision of the earlier round: the news card lives on Home, no
    separate News screen): the market's stored items whose status is confirmed or corroborated, each with the
    sentiment square, the company, the headline (link), the status badge, source, materiality, event type,
    independent origins and filings, local time; the rest behind "Set aside: n rumour, ..." with the same rows.
11. **Runs today**: a timeline of pre-open, intraday checks, post-close (or its next time) and news (new items),
    each with a tick / cross / clock mark and the local time; "n of N ok" label; the cut-off line.
12. **Open paper trades** (full width): grouped by company (count, last close, unrealised total), one row per open
    trade: strategy (H2H tag for a head-to-head trade), horizon chip with entry -> exit dates, entry, last,
    unrealised in money and percent, a **range bar** (the trade's own 50% and 80% bands, the entry dotted, the
    target as a triangle, the last price as the dark line; the numbers in the tooltip), distance to target ("past
    target" once reached), and **today's check** from the latest intraday trade check stored by the cut-off (band
    position, flags; tooltip with the check's numbers). Below 1200 px the entry, last and to-target columns and the
    dates go (the tooltips keep them); below 761 px the range bar goes too: strategy, horizon, unrealised, check.
13. **Legend** (signs, tags, badges) and the **footer**: research-only line, `as_of`, `cutoff`, `built_at` and the
    endpoint.

## Data and contract
- `data.json` is composed from eleven catalogue files only (`notes.md` lists each field). Nothing is invented in
  the builder; the only logic is selection (market, today's session, the latest check by the cut-off, news and
  settled trades stored by the cut-off, active companies, the top 5 per horizon) and ordering. The page computes
  only presentation: counts and sums (the KPI cards, the unrealised total per company, the cumulative profit per
  family and day), the expected gain in money, local times, and the geometry of the bars and the chart. Two spec
  constants are named once in the template with their source (the go-live bar's 2 months, SPEC F7.2; two intraday
  checks per session, SPEC section 7); the legend shows sample values and says so.
- Per market the payload carries `as_of`, `cutoff` (the catalogue's clock, 2026-10-07T12:00Z) and `built_at` (the
  market status example's `freshness.built_at`), so the build is deterministic (two builds give the same bytes).
- No look-ahead: intraday checks after the cut-off are left out (the US example's 16:27Z checks), which is why the
  US page shows the "no check yet" state and India the flagged state.
- Family totals to date are not shown: the catalogue has no family-level scoreboard row and the page does not
  invent one (the family x pick-rule rows are catalogue rows). If the owner wants "rule vs AI to date" as one
  number per family, that is a new data request for W1 (a `family` scope on the scoreboard row).
- No new data request was needed for this page. Two things the earlier Home showed are not in the catalogue and
  are therefore not on this page: the benchmark and vol-index tiles (regime is), and the market calendar (next 7
  days of results and market events). Both would be new data requests for W1 (market status: benchmark and vol
  index close and move; a calendar entity) if the owner wants them back.

## Design rules kept
Design system only (tokens, components, icons; no page-local colour, no CDN, font or request); light theme; phone
and desktop; never colour alone (signed numbers, tick/cross glyphs, words beside every colour); keyboard usable
(buttons and links, tooltips on focus, Escape closes); plain language; Paper labels on every signal and trade;
"No proven strong signals today" until proven; research only (no buy or sell instruction: the trades are records,
the viability line is an expected-gain reading); horizon selector N+1..N+5 opening on N+1.

## Checked
`node design/system/check_page.js design/mockups/01-home/page.html design/mockups/01-home shot`: no console
errors, no horizontal overflow, no external requests, at 1280 and 390 px. Rebuild is byte-identical.

- Keyboard: every element with a tooltip is focusable (links and buttons natively, the rest with `tabindex=0`), so
  the range bars' and checks' figures can be reached without a mouse; Escape closes a tooltip and the drawer.
- Text fit: `design/system/check_text.js` scans for clipped, overflowing and overlapping text at 390-1680 px for both
  markets; the only reports left are bounding-box artefacts of an inline ticker before a wrapped headline.
- Catalogue data note for W1 (cosmetic): India's market status lists two intraday runs (05:43Z and 08:43Z ok) but
  trade_check.json holds rows for 05:43Z only, so the runs timeline shows check 2 done while the alerts card's
  latest check is 11:13 IST.

## Design system change (this version)
`design/system/tokens.css` and `components.css` moved to scheme v2 (same token and class names, new values and a
few new classes: `.mb-sidebar`, `.mb-avatar`, `.mb-label`, `.mb-alert`, the KPI card); the style guide was rebuilt
and checked. The earlier round's built pages keep their inlined copy of the previous scheme.

## Open questions for the owner
- Keep both markets behind one switch (as here), or one page with both markets stacked (the earlier design round's
  Home showed both)?
- Bring back the benchmark / vol-index tiles and the 7-day calendar (new data requests to W1)?
