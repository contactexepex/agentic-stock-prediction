# Home mockup: rationale

Page 1 of docs/SPEC.md section 6 (decisions 30 and 39), designed in the design track from W1's data catalogue
(docs/DATA_CATALOGUE.md, design/catalogue/*.json). Status: **awaiting the owner's approval** (second version,
2026-10-08: rebuilt in the terminal look the owner approved page by page in the earlier design round, after the
owner asked for that look and more modernity; the first version was flat cards in the same tokens).

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html`), `data.json` (the example payload of
`GET /api/v1/markets/{market}/home`, read model `rm.home`, one payload per market), `page.html` (self-contained, the
design system inlined, no request leaves the page), `notes.md` (every catalogue entity and field used), screenshots
`shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png` (India, N+1), `shot-us-1280-full.png` (US),
`shot-us-1280-n5.png` (horizon N+5 selected), `shot-1280-top.png` (the top of the desktop page at 2x),
`shot-390-h2h.png`, `shot-390-trades.png` (phone cards).

## What the page is for
The first screen of the morning, one market at a time (the India/US switch in the top bar; the real app navigates
between `/markets/india/home` and `/markets/us/home`, the mockup embeds both payloads). It answers, in order: is
anything proven yet (no: the banner), who agrees today and at which horizon, which paper trades compete today and
whether any clears costs, what is flagged right now, who is ahead (rule vs AI), what is open, and whether the runs
worked.

## The look
The "terminal light" system of design/system/ as the owner approved it on the decision, watchlist and earlier Home
pages (references the owner gave: TradingView symbol pages, Meridian Terminal, Tickr, SignalAIx): a ticker tape,
uppercase micro-labels over large bold numerals in a stat strip, white hairline cards, one indigo accent, green/red
signed numbers with the sign, odds meters on a 30-70 track, range bars, verification badges, tiny LIVE / PAPER tags.
Nothing is colour alone: every up/down carries its sign, every status a glyph and a word.

## Layout (desktop 1280 px: two columns, then a full-width table; phone 390 px: one column in the same order)
1. **Shell**: navigation rail with the 10 market-level pages of the spec (Company and Stock strategies are reached
   from company rows, not from the rail), top bar with a Search-symbols chip, the market segmented button and an
   **Ask** button (the assistant side panel of page 11). Phone: a navigation bar with Home, Watchlist, Strategy lab,
   Rule vs AI and **More** (a sheet with the other pages). Under the top bar a **ticker tape** of the market's active
   companies: last close, day move and "n/N buy" (the N+1 agreement), each linking to the company page.
2. **Header**: the session being predicted (D), open/closed with the session times in the market's local clock,
   data as-of date, regime, freshness (state and build time, tooltip with the cut-off), LIVE DATA and PAPER tags.
3. **Stat strip**, six tiles, the page in one line: most agreed company at the selected horizon; head-to-head
   trades today and how many clear costs; open paper trades and their unrealised total; alerts (flagged of checked,
   or "no check yet"); rule vs AI on the last settled close; runs today ok. Every tile is computed from the payload
   below it (counts and sums only).
4. **Banner** "No proven strong signals today": the catalogue's `paper_label`, the number of strategies and the
   go-live bar's position (`go_live` of the scoreboard). It stays until a strategy is proven (F7); only then may a
   Strong signal appear (owner's direction, SPEC section 6).
5. **Horizon selector** N+1..N+5, a segmented button, opening on N+1 (decision 39), with a plain-language reading of
   the selected horizon. It drives the agreement ranking and the first stat tile.
6. **Top 5 by agreement** (decision 30; the example files hold 3 active companies per market, so the mockup ranks 3):
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
9. **Rule vs AI**: *last close* from the end-of-day analysis (family tiles rule / AI / baselines with trades won and
   net profit, the leader in the accent tint and marked "led"; the two pick rules; the analyst's summary with a link
   to the reasons), and *to date* as the head-to-head scoreboard grid family x pick rule (net profit, trades, win
   rate, mean return, "too few to rank" badge under 20 trades). Link to the Rule vs AI page.
10. **News that can carry a call** (the owner's decision of the earlier round: the news card lives on Home, no
    separate News screen): the market's stored items whose status is confirmed or corroborated, each with the
    sentiment square, the company, the headline (link), the status badge, source, materiality, event type,
    independent origins and filings, local time; the rest behind "Set aside: n rumour, ..." with the same rows.
11. **Last runs**: pre-open, intraday checks, post-close (or its next time), news (new items), each with a
    tick / cross / clock mark and the local time; the cut-off line.
12. **Open paper trades** (full width): grouped by company (count, last close, unrealised total), one row per open
    trade: strategy (H2H tag for a head-to-head trade), horizon chip with entry -> exit dates, entry, last,
    unrealised in money and percent, a **range bar** (the trade's own 50% and 80% bands, the entry dotted, the
    target as a triangle, the last price as the dark line; the numbers in the tooltip), distance to target ("past
    target" once reached), and **today's check** from the latest intraday trade check stored by the cut-off (band
    position, flags; tooltip with the check's numbers). Phone: strategy, horizon, unrealised and the check.
13. **Legend** (signs, tags, badges) and the **footer**: research-only line, `as_of`, `cutoff`, `built_at` and the
    endpoint.

## Data and contract
- `data.json` is composed from ten catalogue files only (`notes.md` lists each field). Nothing is invented in the
  builder; the only logic is selection (market, today's session, the latest check by the cut-off, news first seen
  by the cut-off, active companies, the top 5 per horizon) and ordering. The page computes only counts and sums
  for the stat strip and the unrealised total per company.
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

## Open questions for the owner
- Keep both markets behind one switch (as here), or one page with both markets stacked (the earlier design round's
  Home showed both)?
- Bring back the benchmark / vol-index tiles and the 7-day calendar (new data requests to W1)?
