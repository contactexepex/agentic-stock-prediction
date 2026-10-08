# Paper portfolios mockup: rationale

Page 7 of docs/SPEC.md section 6 (F1.11, F7.1, F10, WS4; decisions 11, 26, 41-42, 44, 50), designed in the design track
from W1's data catalogue. Status: **built on the owner's delegated authority** (2026-10-08, the owner away: "go with
your recommendation, notify the orchestrator"); judged and landed by the track; the owner reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example payload of `GET /api/v1/markets/{market}/portfolios`, read models `rm.portfolio` and
`rm.trades`), `page.html`, `notes.md`, screenshots `shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png`.

## Who reads it and how
The owner checking the paper money: how the two head-to-head portfolios (rule vs AI) stand, which paper trades are open
right now under each strategy and how they are doing at the latest check, and their own manual paper trades, with the
euro view of US holdings. A retail reader sees three blocks top-down, each labelled Paper, and one action: record an
own paper trade, which is a request, never an order.

## Layout (desktop and phone: one column; the open-trades table drops columns by width)
1. **Page head** and the **Paper band**; a **Costs** switch (market cost = the ranking view; your cost adds the owner's
   broker charges, decision 50; open trades are before costs).
2. **KPIs**: open paper trades (count, unrealised, flagged), the head-to-head rule portfolio with the AI portfolio under
   it, the owner's own positions (value, profit), pending requests.
3. **Head-to-head portfolios** (F7.1): one box per family naming the strongest strategy, profit after the selected cost
   (large) with trades, win rate, drawdown and the luck test drawn, and under it the two pick-rule portfolios (best
   expected gain, highest probability) each with trades, win rate, luck label and profit; "too few to rank" beside
   any profit on fewer than 20 trades, and the luck label reads "edge? too few" rather than "edge" on such rows.
   Link to Rule vs AI.
4. **Open paper trades by strategy**: filter chips (family; accuracy / head-to-head view), then one group row per
   strategy (name linked to the Strategy lab, family label, count, unrealised sum) and one row per trade: company
   (H2H tag for a pick), horizon and window, entry, last close, unrealised in money and percent, the trade's own
   predicted range with the entry dotted and the last close as the dark line, distance to the target, and the latest
   intraday check's verdict at its own price. Columns by width: to-target from 1360 px, entry, last, the percent
   and the entry-to-exit dates from 1200 px, the range from 761 px; the owner's average price and last close from
   1001 px and its cost column from 761 px.
5. **Your own paper portfolio** (WS4, F1.11): positions (shares, average price, last close, cost, value, profit with
   percent), the **euro view** of each US position as four tiles (euros paid at the buy-date rate plus markup, euros
   back at today's rate minus markup, profit in euros beside the dollar profit, and the part due to the rate alone,
   with the fee note from the data: the BUX FX fee of `config/costs.yaml`, owner-confirmed 2026-10-08), the recorded trades (side, quantity, price and basis, date, channel,
   note), and the **Add own paper trade** button: a dialog with company (active ones), side, shares, price basis (the
   session's open or close, or a typed price inside the day's range), price and date; recording it shows a pending
   request on the card (mockup state; the real page appends to the inbox with the sign-in and an idempotency key,
   F10, and the import checks the price against the stored bar).
6. **Legend** and **footer**.

## Data and contract
- `data.json` is composed from seven catalogue files only (`notes.md` lists each field). Selection and ordering only;
  the page computes sums, filters and the pending state.
- No look-ahead: trade checks by `check_at`, own trades by `entered_at`, at or before the cut-off; the scoreboard rows
  are computed to the as-of close. No new data request.

## Design rules kept
Design system v2 only; light theme; phone and desktop (both tables fit their wrapper at every width 390-1700 px in
both markets); never colour alone (labels and icons on checks and sides, the sign on every number, "edge"/"luck?" in
words); keyboard: the cost switch and filter chips are buttons with `aria-pressed`, the links, the dialog's fields and
buttons, every tooltip focusable; plain language; Paper on every figure; "No proven strong signals today"; research
only (a paper trade is a record, never an order, said on the page, in the dialog and in the pending note).

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. A sweep of 390-1700 px in steps of 10, both
markets: neither table wider than its wrapper. A script switched the family and view filters (chips show the
selection), the cost switch (the head-to-head figures change), opened the dialog and recorded a trade (a pending
request appears and the KPI counts it); no script error; every tooltip element focusable. Rebuild is byte-identical.

Judge round 1 (2026-10-08) found three blockers, all fixed before round 2: two figures of the pick-rule rows ran
together ("1 trade100% won"), the pending note did not say a paper trade is a record (it does now), and the "too few
to rank" badge was missing beside profits on fewer than 20 trades while a bare "edge" showed (now the badge shows and
the luck label is qualified).

## Decisions taken for the owner (reported to the orchestrator)
- The head-to-head portfolios are two family boxes with the pick-rule portfolios inside, not a four-row table, so the
  rule-vs-AI question stays visible at a glance.
- Open trades are grouped by strategy (the spec's "by strategy") with family and view filters, and reuse the Home
  page's row design so the two pages read the same.
- The euro view is four tiles with the formula in each tooltip, rather than a second table, and keeps the data's
  fee note visible (the BUX FX fee, owner-confirmed 2026-10-08; it read "provisional, verify" until the owner confirmed the
  broker charges).
- Adding an own paper trade is a dialog that records a pending request, with the WS4 price rule stated in it.
