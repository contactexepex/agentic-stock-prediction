# Rule vs AI mockup: rationale

Page 6 of docs/SPEC.md section 6 (the head-to-head view of F1, F6.1-F6.2, F7.1; decisions 41-43, 50-51), designed in
the design track from W1's data catalogue. Status: **built on the owner's delegated authority** (2026-10-08, the owner
away: "go with your recommendation, notify the orchestrator"; the owner asked that the rule-versus-AI comparison be
"elegant, easy to understand, with the reasoning"); judged and landed by the track; the owner reviews it in the
morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example payload of `GET /api/v1/markets/{market}/compare`, read models `rm.compare` and
`rm.review`), `page.html`, `notes.md`, screenshots `shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png`.

## Who reads it and how
The owner asking the project's central question: do the AI traders beat the rule strategies, on the same company-days,
after costs, and is the gap more than luck? Then: what will both pick today, who won each match, does the pick rule or
the regime matter, which company each side reads better, and what the end-of-day analyst and the weekly research
director say about why. The page answers top-down in that order and never turns the answer into a buy or sell.

## Layout (desktop: scorecard, picks, matches, slices, two columns, why, review; phone: one column)
1. **Page head** and the **Paper band**; a **Costs** switch (market cost = the ranking view; your cost adds the
   owner's broker charges, decision 50).
2. **Scorecard**: Rule strategies vs AI traders side by side from the head-to-head scoreboard rows (the family's
   strongest strategy named): profit after the selected cost (large), trades and the rank badge, win rate, average
   target error, return per trade, and the luck test drawn (thin uncorrected, thick corrected, zero tick) with
   "edge" or "luck?"; between them the verdict ("Rule ahead by …", "AI ahead", "Level") with the trade count. The
   leading side is outlined. A note repeats the luck guard: a lead on a handful of trades is mostly luck.
3. **Today's picks** per family: the strongest strategy, each pick with the company, pick rule, horizon chip, the
   chance as an odds meter, the expected gain in money, "clears / below market costs" and decision 51's "viable /
   not viable at your cost"; the head counts both.
4. **Match by match**: one row per company, entry session and pick rule from the settled head-to-head trades, the
   rule result and the AI result (net after the selected cost, strategy, horizon, return, target reached and error),
   and who won (a draw when both picked the same horizon and therefore the same trade; "waiting" while the other
   side's pick is still open, shown as "open · N+k"; "no match" when that family had no candidate that day, or when
   no pick of that family is stored for the day, "no pick stored"). The head totals the matches and names the cost
   view.
5. **Gain-pick vs probability-pick, and by regime** (F7.1, F2.6): the pick-rule rows and the regime rows of the
   head-to-head view, each with trades, profit, win rate, target error and the luck test.
6. **Per company**: rule vs AI per company summed from the settled head-to-head trades after the selected cost (the
   your-cost figures per trade come from the cost views; a per-company head-to-head scoreboard row is requested from
   W1), with "ahead" per company, beside the **cumulative profit** lines of the two families by exit date (F2.8,
   market cost), starting at zero on the first entry date.
7. **Why: the end-of-day analyst** (F6.1): the latest session's results per family (rule, baselines, AI: net, trades,
   wins) and per pick rule, the analyst's summary, and the head-to-head reasons (at most 60 words each, citing ids).
8. **The week's research review** (F6.2): who leads per family, findings with cited ids, and proposals as config
   diffs with their status ("proposed" until the owner approves; nothing is applied). In the example data both
   stored reviews are written on 10 Oct, after the cut-off, so the card shows its honest empty state and names the
   next due Saturday (computed from the cut-off date, not from the stored reviews); a review before the cut-off is
   requested from W1.
9. **Legend** and **footer**.

## Data and contract
- `data.json` is composed from nine catalogue files only (`notes.md` lists each field). Selection and ordering only;
  the page computes who leads, the matches, the per-company sums and the cumulative sums.
- No look-ahead: picks by `made_at`, trades by `settled_at`, reasons and analyses by `created_at`, reviews by
  `written_at`, all at or before the cut-off.
- Data requests to W1 (both in `data.json` `_data_requests`, sent 2026-10-08): per-company head-to-head scoreboard
  rows; a research review before the cut-off.

## Design rules kept
Design system v2 only; light theme; phone and desktop (the scorecard is one column up to 1000 px; the tables fit their
wrapper at every width 390-1700 px in both markets; the line chart is drawn at its container's width); never colour
alone (the verdict in words, "edge"/"luck?" labels, icons on the winner labels, the sign on every number); keyboard:
the cost switch, the strategy and company links, every tooltip and chart point focusable; plain language; a Paper tag
on every card that shows a pick or a trade (scorecard, picks, matches, pick-rule and regime slices, per company,
cumulative lines, the EOD analyst); "No proven strong signals today"; research only.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. A sweep of 390-1700 px in steps of 10, both
markets: no table wider than its wrapper. Rebuild is byte-identical.

Judge round 1 (2026-10-08) found four blockers, all fixed before round 2: an open AI pick shown as "no candidate" (the
earlier sessions' picks are now in the payload), the review card's wording read from reviews written after the
cut-off (now computed from the cut-off date), two rationale claims (Paper tags added to the picks, matches and
per-company cards; the review data request recorded in this page's `_data_requests`), and the matches and
per-company tables ignoring the cost switch (now per-trade your-cost figures from the cost views, labelled). Round 2
found the Paper claim still short of two cards (the slices and the EOD analyst); both carry the tag now.

## Decisions taken for the owner (reported to the orchestrator)
- The page opens with a two-sided scorecard and a one-word verdict, with the luck test drawn, rather than a table:
  the question is "who is ahead and does it mean anything".
- Matches are listed per company-day and pick rule with a draw when both families made the same trade, so identical
  picks are not counted as wins.
- The weekly review is shown as an empty state rather than with a review written after the cut-off: no look-ahead,
  even in a mockup.
