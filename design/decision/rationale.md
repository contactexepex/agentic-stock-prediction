# Stock decision page: rationale

Files: `template.html` + `build.py` (generator, any market and ticker), `decision-HDFCBANK.html`,
`decision-ICICIBANK.html`, `decision-AAPL.html` (self-contained, no network), `data-HDFCBANK.json` (everything the
HDFC Bank page shows), screenshots `shot-*.png`, `notes.md` (queries/commands). The layout below is the one the owner
approved; on 2026-10-07 the page was recoloured onto the Material 3 design system (`design/system/`) and the builder
made generic. What changed in that pass is listed at the end.

## How a novice reads it in 30 seconds

1. **Top-left: a big "NO" with a no-entry icon and "No edge today".** One sentence says why: the model gives
   a rise 47% (a coin flip), it has shown no skill in the back-test, and the forecaster abstained. The forecaster's
   own words follow in small type. Nothing else needs reading to act (do nothing).
2. **"What would turn this into a YES"** is a five-line checklist with red crosses and one green tick: chance
   >= 60% (now 47%), model skill (AUC 0.50, no), run before the open (no, 05:14 UTC), confirmed evidence (no,
   single source), results more than a day away (yes). The reader sees exactly what is missing.
3. **"If it were a YES, the plan would read"** is greyed and mechanical: buy at the open only if it opens at or
   below the range centre, sell at the close of D+1 or by 13 Oct, exit early below the 80% range floor, and
   the rupee outcome on Rs 10,000 (likely -Rs 235 to +Rs 256; 8 in 10 days -Rs 475 to +Rs 511) after
   Rs 22 of costs. Four KPI tiles give the track record: 0 live calls, 26/34 ranges held, 19/33 leans right,
   -0.17% per trade in the back-test.
4. **The chart**: bars are what was predicted, the black line is what happened; green ticks and red crosses
   say hit or miss, icons below say why a miss happened; the fan on the right is the next 1 and 5 days with the
   published prices on its edges.
5. **The table** repeats the chart one row per day for people who prefer numbers; **What's moving it** groups
   the drivers Company / Sector / Market with an arrow and a strength bar; **What's coming** lists the dated
   events with the typical move where history exists (results: +-1.3% typical, -5.1% last time).

Everything long (123 headlines, the maths, the data sources) is collapsed at the bottom. Every term has a "?"
tooltip (hover, focus or tap). Status is never colour alone: tick/cross glyphs, "in"/"out" words, icons.

## Design decisions

- **Decision first, giant, with a plan even when the answer is NO.** The owner's complaint was "how do I decide".
  The NO is framed as "no edge", not "sell"; the greyed plan shows what a YES would commit him to, so the page
  teaches the mechanics before the first real YES exists. The gap rule and Rs 10,000 framing are this page's
  presentation of the published range, labelled as such.
- **One chart answers "was it right, what comes next".** Inline SVG (not Lightweight Charts): per-day band
  bars with 50%/80% steps, hit/miss glyph on the close dot, cause icons in a row under the axis, and a fan whose
  only labelled numbers are the two published ranges (the shading in between is declared interpolated). SVG
  made these marks exact; the chart library would have needed custom series for bands and glyphs.
- **Honest about the model.** The strip makes visible that the calibrated chance barely moves (47-49%): the
  latest fit's Platt slope is 0.0, so the model effectively outputs the base rate. That is the real reason there
  is no edge, and the page says it in words next to the dots.
- **Labels: Live / Back-test / Mock chips** in the header and on every section and tile. Back-test chips are
  hatched, mock chips dashed, so the distinction survives without colour.
- **Numbers large and few**: 56px verdict, 22px hero rupee outcomes, 22px KPIs; the rest is 13-15px.
- **Dataviz skill**: series blue for bands (#2a78d6), ink for the actual close, status green/red only with
  glyph + word, hairline solid gridlines, 2px line, >= 8px markers with white ring, direct labels only on the
  fan edges, crosshair tooltip listing every value at the hovered date, a hidden table view for screen readers.
- **Phone (390px)**: single column, chips collapse to one word with tooltips, the chart relabels (every second
  Monday, "Next 5 ->"), the strip hides the 5-day and close columns and keeps date / chance / band / in-out /
  cause icon; no horizontal page scroll (checked by Playwright).

## What is real, back-test, derived, mock

- **Live (stored this week)**: close Rs 711.45 and the day moves; quotes at 04:57 UTC (ADR +1.40%, S&P, Nasdaq,
  Nikkei, Hang Seng, US 10y, DXY, Brent, USD/INR, India VIX, Nifty live); model_scores for 6 Oct (47.0/47.1%
  1d, 46.9/47.1% 5d, news score and points); the live 5-day range for 13 Oct (696-731 / 679-749); the
  forecaster's bull/bear/verdict and abstain; features (RSI 46, 20d -0.1%, vs sector -4.2 pts); regime
  EVENT_HEAVY (RBI); 123 headlines with enrichment and verification status; events calendar; FII/DII and NSDL
  FPI flows; NSE index closes with P/E and P/B; delivery %; Yahoo consensus EPS; costs from config/costs.yaml.
- **Back-test (not live)**: every past band on the chart and in the strip (rule replay, 17 Aug-6 Oct), every
  "chance up" dot (walk-forward out-of-sample probability), the 1-day fan box for 7 Oct (the live 1-day range
  was withheld because the run came after the open), the skill table and the paper-strategy numbers.
- **Derived by this page from stored data**: the cause of a move when it is market-wide (index moved >= 0.75%
  the same way) or company news (stored high-materiality headlines that day, only from 4 Oct); the typical
  results-day move (8 stored reaction sessions); the gap-rule price; the Rs 10,000 outcome; strength levels.
- **Mock**: the "unexplained" causes (dotted-circle icon, dashed "mock" chip) for stock-specific days before
  the news archive starts on 4 Oct; the explainer agent that will write them is not built. Nothing else is
  invented: where history is missing (RBI days, expiry days) the page says "no stored history".

## Gaps

- No live scored call, range outcome or lesson exists yet; the live 1-day range for 6 Oct was not published,
  so the 1-day plan uses the rule replay's number (labelled).
- News-based causes exist only from 4 Oct; earlier misses are unexplained. The RBI/expiry typical moves cannot
  be computed from stored data.
- Costs are the config's "verify" rates (brokerage assumed Rs 0; slippage not modelled).
- The direction of market drivers (FII selling, oil, yields) is the conventional reading, stated in the
  tooltip, not a model output; the model's own technical contribution is 0 points.

## Recolour to Material 3 (2026-10-07)

- **Only the skin.** Same sections, order, grids, chart, strip, drivers, events and the three expansion panels.
  Colours now come from `design/system/tokens.css`: page on `surface`, elevated cards on `surface-container-lowest`,
  the decision head on `secondary-container` with the NO in `secondary` (calm, not alarming: NO means "no edge",
  not "sell"; a YES would use the up container), numbered section badges in `primary`, hit/miss marks in the
  up/down tokens with tick/cross glyphs, direction squares in the up/down/neutral/unclear containers, Live /
  Back-test (hatched) / Mock (dashed) / Paper (tertiary) tags from the system, bands and fan in chart series 1
  (`--mb-chart-1`), the actual line in on-surface ink, tooltips on the inverse surface.
- **App shell.** The page sits in the shell: navigation rail (desktop) / navigation bar (phone) with Watchlist
  marked current (this is one of its company pages) and the other sections "soon", top app bar with the title and
  the India/US segmented button (the current market pressed; switching lives on Home/Watchlist).
- **Icons** are Material Symbols Outlined (vendored, Apache 2.0) instead of hand-drawn line icons.
- **Generic builder.** `build.py --market --ticker --out`; every string that was hand-written for HDFC Bank now
  comes from stored data or config (`data.page`): company, exchange, sector, currency and stake, 52-week position,
  the why-sentence, the five checks, the plan sources, driver rows, event texts, sources. Lost in the move: the
  hand-written driver names ("Three senior exits; 52-week low") became the stored headline titles, the sector mood
  row became the peer's top headline, and the chart note's hand-written miss commentary ("misses cluster on days
  ...") became a pointer to the table. Numbers are unchanged (see notes.md).
- **Checked** with Playwright at 1280 and 390 px for all three pages: no console errors, no horizontal scroll, no
  external requests.
