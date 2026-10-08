# Strategy lab mockup: rationale

Page 5 of docs/SPEC.md section 6 (F2 and F2.8, F7, decisions 42 and 50; the luck guard of section 6), designed in
the design track from W1's data catalogue. Status: **built on the owner's delegated authority** (2026-10-08, the
owner away: "go with your recommendation, notify the orchestrator"; the owner asked for this page to be "elegant,
easy to understand, easy to use, a good comparison with the reasoning"); judged and landed by the track; the owner
reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example payload of `GET /api/v1/markets/{market}/strategies`, read model `rm.strategies`),
`page.html`, `notes.md`, screenshots `shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png`.

## Who reads it and how
The owner comparing strategies: which one is ahead after costs, is that luck or an edge, what does it do differently
from the reference, where does it win (which horizon, company, regime, kind of move) and how far is it from the
go-live bar. A retail investor reads the same page top-down: the leader and the yardstick first, then the ranked
table, then one strategy in plain words, then the lines and maps. The page compares; it never says buy or sell, and
every figure carries Paper until a strategy is proven.

## Layout (desktop: controls, KPIs, scoreboard, detail beside the lines, heatmaps; phone: one column)
1. **Page head** (count of strategies by family, as-of, chips) and the **Paper band**.
2. **Controls** in one row, each with a help icon: **View** (accuracy / head-to-head), **Basis** (forward /
   back-test: never pooled, F2.3; the back-test rows of W1's `scoreboard_backtest_row.json` show with the run's
   facts, the strategies it did not run read "not run"), **Costs** (market cost = the
   ranking view; your cost = the go-live view, decision 50; the ranking never changes with the switch, the numbers
   do) and **Horizon** (all pooled, or N+1..N+5).
3. **KPIs**: the leader after market cost (with the trade count and "too few to rank"), the best baseline as the
   yardstick, how many strategies beat it, and the rule strategy or AI trader nearest to the go-live bar (trades and
   months to go; baselines are yardsticks, never candidates).
4. **Scoreboard**: all 15 strategies of the registry, baselines in the same list marked "yardstick", ranked by profit
   after market cost (strategies without trades follow, by family). Columns: rank, strategy (name as the selector,
   family label, what it differs in), profit after the selected cost with the other cost view under it, trades, win
   rate, per-trade return (with target-reached and range-hit in the tooltip), drawdown, the **luck test drawn**: a
   thin bar for the 95% interval of the mean return per trade, a thick bar for the interval corrected for the rows
   compared at once, a tick at zero and the mean as a dot, with "edge" only when the thick bar clears zero, and the
   go-live chips (trades to go, months, beats the yardstick). In the head-to-head view a second table shows the
   family × pick-rule portfolios (gain-pick vs probability-pick). Columns by width: go-live chips from 1500 px,
   per-trade and drawdown from 1280 px, rank and trades from 901 px, the luck bar from 1001 px (its label stays).
5. **In plain words** (the selected strategy; opens on the leader, `#market/strategyId` deep link, also the target
   of the Stock strategies page's links): name, family, live state, the registry's description, the one setting it
   changes against the strategy it is compared to with both values ("if its results differ, that setting is why",
   F2.5), its settings as chips, the probability bar, horizons and settled trades; then its numbers in the selected
   view: profit per horizon as diverging bars, per market regime (F2.6: measured, not assumed; all horizons), per
   company (linked to the Stock strategies page, "too few" marked; the selected horizon), the settled-trade count in
   this market, and the **go-live checklist** on your cost: trades to go, months
   forward, beats the best baseline, drawdown within the limit, holds in calm and volatile regimes, each with a tick,
   a cross or "not enough data yet".
6. **Cumulative profit after market cost** (F2.8; always market cost, the view the settled trades carry): one line
   per strategy by exit date, the selected one thick, the selected and the three highest coloured and named at the
   line end (names cut at 22 characters, the legend has them in full; colours follow the registry order), the rest
   grey; the zero line dotted; hover or arrow keys list every line's value at a date. On the Back-test basis the
   chart, the reason map and the regime and company splits show an empty state: the settled trades are forward
   trades and are never pooled, and the back-test stores no split by regime or company.
7. **Where each strategy wins and loses** (F2.8, decision 42): four heatmaps for the selected view, by horizon, by
   company, by market regime and by the reason the price moved (the settled trades' automatic reason code), with a
   Profit / Win rate switch. Green for profit (or a win rate above half), red for loss, darker for larger, and the
   number in every cell so colour never stands alone; a dot for no trade; every cell's tooltip has the trade count.
   One stored week in the example data; the real page adds a week picker.
8. **Legend** and **footer**.

## Data and contract
- `data.json` is composed from five catalogue files only (`notes.md` lists each field): the registry, every
  scoreboard row of the market (all scopes, both views, every horizon), the settled trades for the lines and the
  reason map, the companies' names and the market status. Selection and ordering only.
- No look-ahead: settled trades by `settled_at` at or before the cut-off; the scoreboard rows are computed to the
  as-of close.
- Two data requests to W1 (in `data.json` `_data_requests`), both answered on 2026-10-08: back-test rows (basis
  `backtest`), answered with `scoreboard_backtest_row.json` (always-up and momentum on the stored bars, without the
  15-year history cache; model-only and the rule strategies not run; the US order fee at an assumed EUR/USD), now
  read into the same `rows` list with their basis and shown on the Back-test basis with the run's facts (`backtest_run`);
  weekly rows plus a per-reason-code scope for the heatmaps over time, answered with `heatmap_cell.json` and
  `cumulative_line.json`, not read yet (the heatmaps and lines still come from the settled trades of the one stored
  week; reading the cells is a follow-up).

## Design rules kept
Design system v2 only (every colour a token; the heatmap scale mixes the up/down tokens into the surface); light
theme; phone and desktop (the scoreboard and the per-company table fit their wrapper at every width 390-1700 px in
both markets; the line chart is drawn at its container's width and redrawn on resize); never colour alone (numbers in
every heatmap cell, the luck test labelled "edge" or "luck?", the go-live checks with icons and words, the sign on
every number); keyboard: the controls are buttons with `aria-pressed`, the strategy names are buttons, the line
chart is focusable with arrow keys and Escape, every heatmap cell and tooltip focusable; plain language with the
statistics explained in tooltips; Paper on every signal; "No proven strong signals today"; research only; the
horizon selector N+1..N+5 (plus All, since the lab compares horizons).

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text in the default state. A sweep of 390-1700 px in
steps of 10, both markets, in every combination of view, basis and cost: the scoreboard, the pick-rule table and the
per-company table are never wider than their wrapper. A chart-text check at 390, 768, 1024, 1280 and 1680 px in both
views: no line-chart label clipped by the card or overlapping another. A script switched every control (view, basis,
cost, horizon, metric), selected a strategy from the keyboard (the detail card and the hash follow) and read the line
chart with the arrow keys; no script error; every tooltip element is focusable. Rebuild is byte-identical.

After W1's back-test rows (2026-10-08): the same checks rerun clean, and a render of the Back-test basis in both markets at 1280 and 390 px shows the run's facts above the table, the two back-tested baselines ranked with their market-cost and your-cost profit, every other strategy as "not run", the detail card's per-horizon figures for a back-tested strategy, and "not stored" for the luck test on the your-cost view (the back-test stores it for market cost only); no table wider than its wrapper, no page error.

Judge round 1 of the back-test batch (2026-10-08) found six blockers, all fixed before round 2: the your-cost view
fell back to the market figure where a back-test row stores none (win rate, drawdown, losing streak: now "not
stored"); a null target miss printed 0.00% (now "—", and the tooltip says the basis has no targets or ranges); the
cumulative card still said no back-test rows are stored; the go-live block looked up the row on the shown basis and
said "no forward row" for a strategy that has one (now always the forward accuracy row); the heatmap header said
"week to 6 Oct" on the back-test and the company and regime maps were blank (now the run's span, and each map says
the back-test stores no such split); and "edge" was shown on a corrected interval wholly below zero (now "loss", in
red with words, and "edge" only when the corrected interval lies above zero; the legend has all three).

Judge round 1 (2026-10-08) found eight blockers, all fixed before round 2: the Back-test basis still drew forward
lines and the forward reason map; the line chart's heading followed the cost switch while plotting market cost;
line-chart labels overflowed and overlapped; the pick-rule table and the your-cost scoreboard overflowed at some
widths; a baseline was named nearest to go-live; the settled-trade chip counted both markets; "about 300", "95%" and
"15-year" were literals; the notes' "registry order" and the rationale's "both values" were false for the sort and
for the threshold strategy.

## Decisions taken for the owner (reported to the orchestrator)
- One scoreboard for all 15 strategies with the baselines in the same list (SPEC F7.1), ranked on market cost with
  the your-cost figure beside it (decision 50) and a cost switch, instead of two tables.
- The luck test is drawn as a bar (uncorrected thin, corrected thick, zero tick) with a one-word label, so a retail
  reader sees "edge" or "luck?" without reading the interval; the numbers stay in the tooltip.
- The strategy detail is the "comparison with the reasoning": the one setting that differs, with both values, and
  the go-live checklist with ticks and crosses, rather than a paragraph.
- Four heatmaps with the numbers in the cells and a Profit / Win rate switch, rather than win rate and profit maps
  side by side (eight maps); the weekly dimension waits for weekly rows from W1.
- Back-test is a switch, not a hidden mode: forward and back-test are never shown on the same table; on the Back-test
  basis the run's facts (bars covered, no history cache, which strategies were not run, the assumed EUR/USD) sit
  above the table, and a strategy without a row reads "not run" rather than "no trades yet".
