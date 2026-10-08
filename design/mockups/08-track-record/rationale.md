# Track record mockup: rationale

Page 8 of docs/SPEC.md section 6 ("prediction accuracy over time, calibration, scoring bases apart"; decision 17;
read model `rm.track_record`), designed in the design track from W1's data catalogue, after W1 answered the track's
data request 5 with the `track_record` entity (the dashboard's read model, one payload per market). Status: **built
on the owner's delegated authority** (2026-10-08, the owner away: "go with your recommendation, notify the
orchestrator"; the owner asked for visualisation and tooltips over long text, and pages a retail investor can read);
judged and landed by the track; the owner reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example payload of `GET /api/v1/markets/{market}/track-record`), `page.html`, `notes.md`,
screenshots `shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png`.

## Who reads it and how
A retail investor asking "can these predictions be trusted?" The answer is given in this order: the signal model's
skill verdict from the weekly review (the band at the top: "Paper only — no proven edge yet" until the review says
otherwise), four figures at a glance, then the evidence: the forecaster's direction calls scored per basis with hit
rates and their uncertainty, how well the stated confidence matched reality (calibration), whether the published
ranges held, the weekly review's back-test, and the historical replay kept apart. Every figure is a paper record;
the page ranks and explains, it never says buy or sell.

## Layout (desktop: band, KPIs, calls table, calibration beside ranges and over-time, back-test, replay; phone: one column)
1. **Page head** and the **skill band**: the read model's own label and the review it comes from; the skill rule in
   the info icon; the back-test card below says why in full.
2. **KPIs**: the signal model's state; calls scored on the first basis with hits, hit rate and its Wilson 95% interval
   (or "not enough history yet" below `min_sample`); the edge against always-up in points; the Brier score with its
   skill against the base rate and the log loss. Each tooltip explains the measure in one sentence.
3. **Calls by scoring basis**: one basis at a time (a segmented control when more than one basis has calls; the
   example holds close→close only, and the head says so), never pooled; rows for all horizons and each horizon (an
   old window marked "legacy", never pooled with N+k); the hit rate as an interval bar (thick line = Wilson 95%
   interval, dot = the hit rate, dashed tick = 50%, orange tick = the always-up baseline), always-up, edge, mean
   confidence, Brier, log loss and Brier skill with the sign. Rows below `min_sample` are greyed with the gate's
   words. Columns by width: log loss and mean confidence from 1360 px; always-up, edge and Brier skill from 1001 px;
   on a phone the first column wraps and the bars shrink. A note names the example block (`example_parts`).
4. **Calibration**: the reliability bands of the selected basis drawn at the card's width: stated confidence (band)
   on the x axis, the share that came true on the y axis, the dashed diagonal where a well-calibrated forecaster
   sits, each band a dot with its Wilson interval and its call count, an empty band a hollow mark on the axis
   (its tooltip and the table say "no calls"); every band is a focusable
   hit area with the numbers in its tooltip; the same numbers in a small table under it.
5. **Ranges held** (empty state until a range is scored: the catalogue's `ranges` is empty and names no fields; the
   page expects per-horizon rows with the inside-50% and inside-80% shares and their Wilson intervals) and
   **Accuracy over time** (empty state: the weekly series is not in the read model; recorded in `_data_requests`).
6. **Signal model back-test** (the weekly review's walk-forward test, "not live"): its verdict sentence, the data
   block as tiles (companies, bars from, scored days, rows, the round-trip cost), the **scores** per horizon and basis
   (rows and days, Brier against the base-rate Brier, Brier skill with the sign, AUC with its 95% interval on a
   0.40–0.60 axis, "skill shown" yes/no as a labelled badge), and the **paper long against the baselines** grouped
   by horizon and basis (the bar, positions, days, the mean per entry date of the return over the window with its
   95% interval around zero, the engine's verdict as a badge: "not distinguishable", "fewer than 20 dates", "no
   positions"). On narrow screens the bar and the badge move under the row's name, so rows of one baseline at
   different bars stay apart.
7. **Historical replay**: "not live" tag; the empty state when none is stored by the cut-off (the example).
8. **Legend** (Paper, Wilson interval, Brier, the gate, legacy) and **footer**.

## Data and contract
- `data.json` is composed from three catalogue files only (`notes.md` lists each field): the market status and the
  go-live block for the shell, and the Track record read model whole. The page computes nothing but presentation.
- No look-ahead: the read model is as of the catalogue's cut-off (`as_of` checked at build time); the W40 review is
  the newest computed before it.
- The numbers the page shows are the read model's; where it has an honest gap the page says so: the calls block is
  computed from the forecaster's example calls (no call is scored in the stored data yet), no range is scored, no
  replay is stored, and the weekly series does not exist yet. New data request: the weekly series of hit rate and
  Brier per basis (to the read model's owner, B4), recorded in `_data_requests`.

## Design rules kept
Design system v2 only (every colour a token; the chart and the bars use the chart tokens); light theme; phone and
desktop (every table fits its wrapper at every width 390-1700 px in both markets; the chart is drawn at the card's
width and redrawn on resize); never colour alone (every badge has words, every bar a number, the sign on every
signed figure); keyboard: the basis control and the market switch are buttons, every chart band is focusable with
its numbers in the tooltip, every tooltip element focusable; plain language with the statistical words explained
in tooltips and the legend; Paper in the band, the KPI and the legend; research only, said in the head and the band.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. A sweep of 390-1700 px in steps of 10, both
markets: no table wider than its wrapper. A script at six widths in both markets: no SVG text of the calibration
chart clipped or overlapping, every tooltip element focusable, no page error; the market switch and a keyboard pass
over the chart's bands work. Rebuild is byte-identical.

Judge round 1 (2026-10-08) found four blockers, all fixed before round 2: the back-test's strategy column said "mean
per day" where the engine averages the whole window's return per entry date; the bar (threshold) column was hidden
at and below 1000 px with nothing replacing it, so rows of one baseline at different bars read alike on a phone;
this file misstated the calls table's column breakpoints; and it said the "why" sentence appears once while the band's
info icon also held it. The cosmetics fixed with them: the three KPI icons that were not in the icon sheet, the
negative Brier skill's colour and minus sign, empty calibration bands moved from the diagonal to the axis, the Brier and always-up KPIs stay neutral below `min_sample`, the round-trip cost and base-rate wordings,
and the "wide interval" remark only below `min_sample`.

## Decisions taken for the owner (reported to the orchestrator)
- The skill verdict leads the page as a band with the review it comes from; the band's info icon holds only the skill
  rule, and the long "why" sentence appears once, as the back-test card's verdict, so the top of the page stays short.
- Uncertainty is drawn, not only written: every hit rate carries its Wilson interval as a bar with the always-up
  baseline as a tick, so a reader sees at once that four calls prove nothing.
- Calibration is a chart with the diagonal, the pages' usual way of showing "did the confidence mean anything",
  with the bands' table under it for the numbers.
- Scoring bases are never pooled: one basis at a time with a control, and old windows carry a "legacy" tag.
- Empty states say exactly what is missing and why (no range scored, no replay stored, the weekly series not in the
  read model), rather than hiding the cards.
