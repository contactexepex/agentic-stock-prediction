# Home mockup: rationale

Page 1 of docs/SPEC.md section 6 (decisions 30 and 39), designed in the design track from W1's data catalogue
(docs/DATA_CATALOGUE.md, design/catalogue/*.json). Status: **awaiting the owner's approval** (first version,
2026-10-07).

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html`), `data.json` (the example payload of
`GET /api/v1/markets/{market}/home`, read model `rm.home`, one payload per market), `page.html` (self-contained, the
design system inlined, no request leaves the page), `notes.md` (every catalogue entity and field used), screenshots
`shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png` (India, N+1), `shot-us-1280-full.png` (US),
`shot-us-1280-n5.png` (horizon N+5 selected), `shot-390-h2h.png`, `shot-390-trades.png` (phone cards).

## What the page is for
The first screen of the morning, one market at a time (the India/US switch in the top bar; the real app navigates
between `/markets/india/home` and `/markets/us/home`, the mockup embeds both payloads). It answers, in order: is
anything proven yet (no: the banner), who agrees today and at which horizon, which paper trades compete today and
whether any clears costs, what is flagged right now, who is ahead (rule vs AI), what is open, and whether the runs
worked.

## Layout (desktop 1280 px: two columns, then a full-width table; phone 390 px: one column in the same order)
1. **Shell**: navigation rail with the 10 market-level pages of the spec (Company and Stock strategies are reached
   from company rows, not from the rail), top bar with the market segmented button and an **Ask** button (the
   assistant side panel of page 11). Phone: a navigation bar with Home, Watchlist, Strategy lab, Rule vs AI and
   **More** (a sheet with the other pages).
2. **Header**: the session being predicted (D), open/closed with the session times in the market's local clock,
   data as-of date, regime, freshness (state and build time, tooltip with the cut-off) and the Paper tag.
3. **Banner** "No proven strong signals today": the catalogue's `paper_label`, the number of strategies and the
   go-live bar's position (`go_live` of the scoreboard). It stays until a strategy is proven (F7); only then may a
   Strong signal appear (owner's direction, SPEC section 6).
4. **Horizon selector** N+1..N+5, a segmented button, opening on N+1 (decision 39), with a plain-language reading of
   the selected horizon. It drives the agreement ranking.
5. **Top 5 by agreement** (decision 30; the example files hold 3 active companies per market, so the mockup ranks 3):
   rank, ticker (a link to the stock strategies page, page 4), name, last close and day move, "12 of 15 strategies
   buy at N+1" with a bar, the split by family (rule / baselines / AI), the average probability of the buyers (or
   "no probability" when only always-buy and follow-yesterday buy), and a **buyers-by-horizon strip** (N+1..N+5
   counts, the selected horizon highlighted), which shows the strongest other horizon of decision 39 at a glance.
   Empty state: "No strategy buys any company at N+k today".
6. **Today's head-to-head trades** (decisions 41-42): per company, the amount per trade (override marked), then
   Rule | AI boxes naming the family's strongest strategy and its ranking basis (tooltip), one row per pick rule
   (best expected gain, highest probability): horizon chip, chance of a rise, the expected gain after costs in money
   and in percent with a tick/cross **clears costs / below costs** (F9's viability rule: expected gain after costs
   above zero), and the three inputs (to target, downside to the 80% range's low, costs). "Why these horizons" opens
   the candidate table (every buyable horizon with the same numbers). The summary line counts the trades and says
   "No pick clears costs today" when none does. A company with no candidate says so (HDFC Bank in the example).
7. **Open paper trades** (full width): grouped by company (count, last close, unrealised total), one row per open
   trade: strategy (H2H tag for a head-to-head trade), horizon chip with entry -> exit dates, entry, last,
   unrealised in money and percent, distance to target ("past target" once reached), and **today's check** from the
   latest intraday trade check stored by the cut-off (band position, flags; tooltip with the check's numbers).
   Phone: strategy, horizon, last, unrealised and the check; the table scrolls inside its card.
8. **Alerts** (side column, first): the flagged rows of the latest intraday check, grouped by company: what is
   flagged, price and move since entry at the check time, the trades concerned. Empty states: no check stored yet
   today (US in the example: the cut-off is before the first US check), or nothing flagged.
9. **Rule vs AI**: *last close* from the end-of-day analysis (family tiles rule / AI / baselines with trades won and
   net profit, the leader outlined; the two pick rules; the analyst's summary with a link to the reasons), and
   *to date* as the head-to-head scoreboard grid family x pick rule (net profit, trades, win rate, mean return,
   "too few to rank" badge under 20 trades). Link to the Rule vs AI page.
10. **Last runs**: pre-open, intraday checks, post-close (or its next time), news (new items), each with a
    tick / cross / clock mark and the local time; the cut-off line.
11. **Footer**: research-only line, `as_of`, `cutoff`, `built_at` and the endpoint.

## Data and contract
- `data.json` is composed from nine catalogue files only (`notes.md` lists each field). Nothing is invented in the
  builder; the only logic is selection (market, today's session, the latest check by the cut-off, active companies,
  the top 5 per horizon) and ordering. The page sums the unrealised profit per company and nothing else.
- Per market the payload carries `as_of`, `cutoff` (the catalogue's clock, 2026-10-07T12:00Z) and `built_at` (the
  market status example's `freshness.built_at`), so the build is deterministic (two builds give the same bytes).
- No look-ahead: intraday checks after the cut-off are left out (the US example's 16:27Z checks), which is why the
  US page shows the "no check yet" state and India the flagged state.
- Family totals to date are not shown: the catalogue has no family-level scoreboard row and the page does not
  invent one (the family x pick-rule rows are catalogue rows). If the owner wants "rule vs AI to date" as one
  number per family, that is a new data request for W1 (a `family` scope on the scoreboard row).
- No new data request was needed for this page.

## Design rules kept
Design system only (tokens, components, icons; no page-local colour, no CDN, font or request); light theme; phone
and desktop; never colour alone (signed numbers, tick/cross glyphs, words beside every colour); keyboard usable
(buttons and links, tooltips on focus, Escape closes); plain language; Paper labels on every signal and trade;
"No proven strong signals today" until proven; research only (no buy or sell instruction: the trades are records,
the viability line is an expected-gain reading); horizon selector N+1..N+5 opening on N+1.

## Checked
`node design/system/check_page.js design/mockups/01-home/page.html design/mockups/01-home shot`: no console
errors, no horizontal overflow, no external requests, at 1280 and 390 px. Rebuild is byte-identical.

## Open questions for the owner
- Keep both markets behind one switch (as here), or one page with both markets stacked (the earlier design round's
  Home showed both)?
- The buyers-by-horizon strip on each agreement row: keep, or show only the selected horizon?
