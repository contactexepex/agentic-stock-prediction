# Watchlist mockup: rationale

Page 2 of docs/SPEC.md section 6 (decisions 13, 30, 39), designed in the design track from W1's data catalogue.
Status: **built on the owner's delegated authority** (2026-10-08: the owner approved Home, then asked for the
remaining pages to be designed autonomously on my recommendations while away, with every decision reported to the
orchestrator); judged and landed by the track; the owner reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through the shared
`design/mockups/_shared/mockup.py`), `data.json` (the example payload of `GET /api/v1/markets/{market}/watchlist`,
read model `rm.watchlist`, one payload per market), `page.html`, `notes.md`, screenshots `shot-1280-full.png`,
`shot-390-full.png`, `shot-390-viewport.png` (India, N+1), `shot-us-1280-full.png`, `shot-1024-full.png`,
`shot-768-full.png`, `shot-1440-table-n5.png` (the table with every column, horizon N+5).

## Who reads it and how
The retail investor who wants to choose a company to look at: one row per active company, the few numbers that
matter at a glance (last close and move, who agrees at the chosen horizon, today's published range, open paper
trades), then a click to the company page. No decision is made here; the page says who agrees and where the
strategies expect the price, and the Paper band says nothing is proven.

## Layout (desktop: KPI row, toolbar, one table; phone: the same in one column)
1. **Shell** (shared): the semi-dark sidebar with Watchlist current, top bar with the market switch and Ask.
2. **Page head**: "Watchlist", one-line subtitle, chips (session, regime, freshness, Paper).
3. **Paper band**: "No proven strong signals today" with the go-live bar's position (`go_live` of the reference
   strategy's scoreboard row); a success band if `proven` ever becomes true.
4. **KPI cards**: companies followed (with the inactive count and a link to the Companies page, decision 13); most
   agreed company at the horizon; open paper trades with the unrealised total; flagged open trades of the latest
   intraday check (or "no check yet").
5. **Toolbar**: a filter box (symbol or name), sector chips with counts, the **horizon selector** N+1..N+5 opening
   on N+1 (decision 39): it sets the agreement, chance and range columns.
6. **Table**, sortable by the column heads (agreement by default: buyers, then average chance; day move; name;
   open trades; last): company (icon tile, ticker as the link, name and sector), last close and day move (sign and
   colour), **agreement** "n of N buy" with a stacked bar by family (rule, baselines, AI), the buyers' average
   **chance** as an odds meter, **buyers by horizon** mini bars (the selected horizon dark), the **range** at the
   horizon (the reference rule strategy's published 50% and 80% bands, the target as the triangle, the last close
   as the dark line; "—" when the example holds no prediction for that company), **open** paper trades (count,
   unrealised, a flagged label when the latest check flagged any), and an Open link. The whole row is clickable.
   Columns by width: the Open link from 1360 px, buyers-by-horizon from 1280 px, chance and range from 1200 px,
   the open-trades column from 761 px; a phone keeps company, last and agreement.
7. **Not listed** line: the inactive companies by name with the date they went inactive and a link to the
   Companies page (decision 13: shown only there).
8. **Legend** and **footer** (`as_of`, `cutoff`, `built_at`, the endpoint).

## Data and contract
- `data.json` is composed from eight catalogue files only (`notes.md` lists each field); selection and ordering
  only. The page computes counts and sums (open trades and unrealised per company, flagged counts) and sorts.
- The range column reads the reference rule strategy's prediction for the as-of date; the catalogue's prediction
  examples cover one company per market (RELIANCE, NVDA), so the other rows show "—" with a tooltip saying why.
  The real read model has one per active company and horizon.
- No new data request: the catalogue has everything this page shows. The earlier round's watchlist also showed a
  20-session sparkline, the next results date and a news count; those would be new requests (bars, calendar,
  news counts per company) and are left to the Company page and the calendar request already sent to W1.
- No look-ahead: checks after the cut-off are excluded; predictions only when `made_at` <= cutoff.

## Design rules kept
Design system v2 only (no page-local colour); light theme; phone and desktop; never colour alone (signs, glyphs,
words); keyboard: links, buttons, sortable heads (`aria-sort`), every tooltip focusable, Escape closes the drawer;
plain language; Paper on every signal; "No proven strong signals today"; research only (no buy/sell instruction);
horizon selector N+1..N+5 opening on N+1.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js`
(twelve widths, both markets): no clipped, overflowing or overlapping text. Rebuild is byte-identical.

## Decisions taken for the owner (reported to the orchestrator)
- The table is the page; no second chart. The visual parts are the stacked agreement bar, the odds meter, the
  buyers-by-horizon bars and the range bar, which the owner approved on Home.
- Inactive companies are not rows (decision 13); they are named once under the table with a link.
