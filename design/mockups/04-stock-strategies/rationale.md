# Stock strategies mockup: rationale

Page 4 of docs/SPEC.md section 6 (decision 30; decisions 38, 39, 41, 42; the luck guard of section 6), designed in
the design track from W1's data catalogue. Status: **built on the owner's delegated authority** (2026-10-08, the
owner away: "go with your recommendation, notify the orchestrator"); judged and landed by the track; the owner
reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through
`design/mockups/_shared/mockup.py`), `data.json` (the example payload of
`GET /api/v1/markets/{market}/stocks/{ticker}/strategies`, read model `rm.stock_strategies`, page_key = ticker; the
mockup embeds the two companies whose predictions the catalogue holds, RELIANCE and NVDA), `page.html`, `notes.md`,
screenshots `shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png` (RELIANCE, N+1), `shot-us-1280-full.png`
(NVDA), `shot-1024-full.png`, `shot-1680-table.png` (the ranked table with every column).

## Who reads it and how
The investor who clicked a company and asks: do the strategies agree on it, at which horizon, which strategy has
actually made money on it, and what does each strategy say for today? The page answers in that order and guards
against luck as the spec demands: the trade count and the luck test sit next to every profit, strategies with
fewer than 20 trades on the company are greyed "too few to rank", and the best strategy overall is shown beside the
per-company best.

## Layout (desktop: KPI row, two cards side by side, one table; phone and widths up to 1000 px: one column)
1. **Page head**: ticker and name, last close with the day move, sector, the amount per paper trade, a link to the
   company page; chips (session, regime, freshness, Paper).
2. **Paper band** (shared).
3. **KPI cards**: agreement at the selected horizon (n of N, average chance); **best on this company** (profit after
   costs on it, trades, "too few to rank"); **best overall** (the market's best across all companies, the luck guard);
   head-to-head trades today, how many clear market costs and how many are viable at the owner's own cost (decision 51).
4. **Who agrees, by horizon**: a grouped stacked bar chart, one bar per horizon N+1..N+5, stacked by family (rule,
   baselines, AI) with "n/N" on top; the selected horizon is full colour, the others dimmed; clicking a bar or a tab
   selects the horizon (opens on N+1, decision 39). Under it, three family bars for the selected horizon and the
   catalogue's own sentence ("Reliance Industries: 12 of 15 strategies buy at N+1").
5. **Today's head-to-head picks** (decisions 41-42): Rule and AI boxes naming the family's strongest strategy and
   the basis it was ranked on (this company from 20 trades, else all companies; the full ranking in the tooltip),
   one row per pick rule with the horizon chip, the chance as an odds meter, the expected gain after market costs in
   money and percent with "clears / below market costs" and decision 51's "viable / not viable at your cost", the three
   inputs, and "Why these horizons" (every buyable horizon with both cost views).
   The no-candidate state says so.
6. **Every strategy on the company**: all 15 strategies, baselines included, ranked by profit after costs on this
   company (accuracy view, all horizons pooled); rows with no settled trade follow, greyed. Columns: rank, strategy
   (name with its family label and the one setting it differs in, linked to the Strategy lab), profit after costs
   (with the trade count under it on every width, the per-trade mean, and in the tooltip the luck test's uncorrected and
   corrected intervals), trades, win rate, average target error, the same
   strategy overall (all companies), **today at N+k** (the chance as an odds meter with the model probability and
   the trader's adjustment and reason in the tooltip, "would buy" or "no trade" or "down, no trade", the target),
   and the range bar (50% and 80% bands, the target as the triangle, the last close as the dark line). The best
   strategy on the company is highlighted. Columns by width: overall from 1600 px, win rate and target error from
   1360 px, range from 1200 px, rank and trades from 761 px; a phone keeps strategy, profit and today.
7. **Legend** and **footer**.

## Data and contract
- `data.json` is composed from seven catalogue files only (`notes.md` lists each field); selection and ordering
  only. The page sorts, picks the best rows (highest profit after costs with trades) and draws.
- The catalogue holds today's predictions for RELIANCE and NVDA (67 each: 15 strategies, rule and baselines at
  N+1..N+5, AI at N+1, N+3, N+5), head-to-head picks for both, and per-company scoreboard rows for the five
  strategies that have settled trades on them; the other ten show "no trades yet". No new data request.
- No look-ahead: predictions with `made_at` at or before the cut-off only.

## Design rules kept
Design system v2 only; light theme; phone and desktop (the agreement chart is drawn at its container's width, so its
text keeps its size on a phone); never colour alone; keyboard: tabs, links, the chart's bars
(focusable, Enter selects), every tooltip focusable, Escape closes the drawer; plain language; Paper on every
signal and trade; "No proven strong signals today"; research only ("would buy" describes the strategy's paper
rule, never an instruction); horizon selector N+1..N+5 opening on N+1.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js`
(twelve widths, both companies): no clipped, overflowing or overlapping text. A sweep of 390-1700 px in steps of
10, both companies: the ranked table is never wider than its wrapper. Rebuild is byte-identical.

## Decisions taken for the owner (reported to the orchestrator)
- The agreement is a chart (grouped stacked bars per horizon), not a table, because the question "at which horizon
  do they agree" is visual; the numbers sit on the bars and in the tooltips.
- The ranked table shows the strategy's own today's prediction at the selected horizon rather than every horizon,
  to keep the table readable; the horizon tabs switch it.
