# Company mockup: rationale

Page 3 of docs/SPEC.md section 6 (decisions 13, 26, 39, 43, 44; F1.9-F1.10, F5, F6.1, F8, WS6), designed in the
design track from W1's data catalogue, including the two entities W1 added on request (bars, calendar events and the
market's benchmark and volatility index). Status: **built on the owner's delegated authority** (2026-10-08, the owner
away: "go with your recommendation, notify the orchestrator"); judged and landed by the track; the owner reviews it
in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example payload of `GET /api/v1/markets/{market}/stocks/{ticker}`, read models `rm.stock`, `rm.bars`,
`rm.lifecycle`, `rm.trades`; the mockup embeds every company the catalogue holds bars for, six in all, and opens on
RELIANCE or NVDA), `page.html`, `notes.md`, screenshots `shot-1280-full.png`, `shot-390-full.png`,
`shot-390-viewport.png` (RELIANCE), `shot-us-1280-full.png` (NVDA), `shot-1024-full.png`,
`shot-hdfcbank-1280-results.png` (the results digest card, HDFC Bank), `shot-390-chart.png` (the chart on a phone).

## Who reads it and how
The investor who opened one company and asks, in this order: where does it stand today (price, who would buy it, at
which horizon, with what range, is there a head-to-head trade and does it clear costs, what is coming), what does the
chart say, how are my open paper trades doing right now, what happened to the settled ones and why, what is the news
and can it be trusted, what did the last results say, what is scheduled, and what are this company's settings. The
page answers in that order and never tells the reader to buy or sell: it shows counts, chances, ranges, outcomes and
their causes, and every signal carries the Paper label until a strategy meets the go-live bar.

## Layout (desktop: head, decision card, chart, two full-width tables, then two columns; phone: one column)
1. **Page head**: ticker and name, sector, market, as-of; chips (session, regime, freshness, Paper). Under it the
   company line: last close with the day move, sector and exchange, the amount per paper trade (marked custom when
   overridden, decision 44), the state (active, or inactive since), and the actions of the spec: **Strategies**
   (page 4), **Change amount**, **Deactivate / Reactivate**, and **Ask** in the top bar (page 11 with the company
   preset). The example picker is mockup-only and says so.
2. **Paper band** (shared): "No proven strong signals today" with the go-live bar's state.
3. **At a glance** (the decision card) with the horizon tabs (N+1..N+5, opening on N+1, decision 39) and four cells:
   who would buy at N+k (n of N with the family bars and the buyers' average chance as an odds meter); the reference
   rule strategy's published range at N+k (target, the range bar, the 80% range, the exit session, its own chance and
   whether it would buy); today's head-to-head picks (family, pick rule, horizon, chance, expected gain in money with
   "clears / below market costs" and decision 51's "viable / not viable at your cost"); open trades (count, unrealised,
   flagged at the latest check) and the next company event. A plain-words line below sums it up and ends with the
   Paper caveat: a majority says the strategies lean the same way, not that they are right.
4. **Price with today's targets and ranges**: daily candles of the stored sessions (60; the last 30 on a phone),
   hollow when the close is above the open and filled when below, so direction is not colour alone; volume under
   them; the last close as the dark dotted line with its price tag on the right axis; to the right of the last bar
   the session being predicted (D) and the exit slots +1..+5: the reference strategy's targets as dots on a dashed
   line, its 50% and 80% ranges as the shaded fan, the selected horizon's exit as the vertical line and its target as
   a second tag on the price axis (the chart's own colour, next to the last-close tag, nudged apart when they would
   touch; the axis ticks they cover are dropped), and at that exit the spread of every strategy's target (the thin
   bar). Paper trades are triangles:
   entries below the low, exits above the high, hollow for still-open trades, with a count when several share a
   date and the list in the tooltip. Hover or the arrow keys read each day (open, high, low, close, the day's move,
   volume, entries and exits); Escape clears. The chart is drawn at its container's width and redrawn on resize, so
   text keeps its size on a phone. Legend under the chart. Companies without a prediction today show the candles
   alone and say so in the decision card.
5. **Today's path: open paper trades** (F5): one row per open trade on the company with the strategy, view, horizon
   and window, entry, last (the latest stored close, the basis of unrealised and the distance to the target), the
   trade's own predicted range with the entry dotted and the last close as the dark line, and the check's verdict at
   its own price (band, flags, the check price and the move since entry under it; best and worst since entry in the
   tooltip). The head names the check time
   and the session of the holding window.
6. **Settled results and why each moved** (F1.9-F1.10, decision 43): a summary strip (trades, how many made money
   after costs, net, target reached, exited inside the 80% range), then one row per settlement, newest first, both
   views: exit date, strategy and view (with the pick rule for head-to-head trades), horizon, entry -> exit (quantity,
   chance, target, best and worst in the tooltip), net after costs with the return, and **why it moved**: the
   automatic reason split as a diverging bar (market, sector, news, company parts to the right push up, to the left
   push down; the parts add up to the move) with the main reason code as a label and the full split in the tooltip.
   Predictions that could not become trades (MARUTI: one share costs more than the amount) are counted and
   explained, with the fix (raise the amount).
7. **In words: the end-of-day analyst** (F6.1): the company's AI reasons, newest first, each with its kind (head-to-
   head, biggest win #n, biggest miss #n), strategy, horizon, settlement date, the text and the cited ids (a cited
   news id shows the headline in its tooltip).
8. **News with its status** (DESIGN 3b): every story tagged with the company, newest first: sentiment arrow, headline
   (link), status badge with its meaning in the tooltip, outlet, materiality, category, independent origins, filings,
   published and first-seen times, earlier headlines at the same link.
9. **Latest results** (WS6): fiscal label, release date and timing, three number tiles (revenue, net profit, diluted
   EPS, each with its year-on-year change), the margin and quarter-on-quarter line, the consensus collected before the
   release (context only) with the surprise, the reaction (stock and beyond the market), the quoted bullets or the
   reason there are none (India: numbers only until a PDF reader exists), and the sources. Without a digest the card
   names the next results date.
10. **Coming up**: from the session being predicted to 8 weeks after it: the company's results and ex-dividend dates
    (highlighted, "widens ranges", the reaction sessions, timing when known), the market's major events ("major": the
    regime goes EVENT_HEAVY two days before, every range in the window widens) and closed days; provisional dates
    say so.
11. **On the watchlist** (F8): state and since when, added when and through which channel, the amount per paper
    trade with a Change button, identifiers, the event history in one line, and the link to the Companies page. The
    **Change amount / Deactivate / Reactivate** buttons open a confirm dialog that states what the request does, that
    it is recorded with the sign-in and an idempotency key and imported by the next run, and that nothing is bought
    or sold; confirming shows the request as pending on the card (mockup state, nothing is sent). Delete is not
    offered here: it needs the typed confirmation of the Companies page (decision in SPEC F8).
12. **Legend** and **footer**.

## Data and contract
- `data.json` is composed from sixteen catalogue files only (`notes.md` lists each field); selection and ordering
  only. The page computes counts, sums and the geometry.
- No look-ahead: lifecycle events by `recorded_at`, picks and predictions by `made_at`, trade checks by `check_at`,
  settlements by `settled_at`, reasons and digests by `created_at`, news by `first_seen_at`, every one at or before
  the cut-off; bars up to the as-of date; events from the session being predicted on.
- The catalogue holds today's predictions for RELIANCE and NVDA only; the other four companies show the chart without
  a fan and say so, which is the page's real empty state. HDFC Bank's four head-to-head rows are "no candidate" rows
  and render as such; JPM and HDFC Bank have a results digest; MARUTI's ten skipped trades show the skipped state.
- No new data request: the earlier requests (bars; calendar events with the benchmark and volatility blocks) were
  met by W1 on 2026-10-08.

## Design rules kept
Design system v2 only (every colour a token; the candles use the up/down tokens with hollow/filled bodies, the fan
the band tokens, the parts of the reason split the four chart series); light theme; phone and desktop (tables fit
their wrapper at every width 390-1700 px for all six companies; wide columns from 1280 px for open trades and 1200 px
for settled ones, the range and "why" columns from 761 px); never colour alone (labels and icons on every status, the
sign on every number, hollow vs filled candles); keyboard: tabs, links, buttons, the chart (focusable, arrow keys,
Escape), every trade mark and tooltip focusable, the dialog's buttons, Escape closes the drawer and the dialog; plain
language with the reasons explained in tooltips; Paper on every signal and trade; "No proven strong signals today";
research only; horizon selector N+1..N+5 opening on N+1.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets) on the page and on copies opened on each of the other four companies: no clipped, overflowing
or overlapping text. A sweep of 390-1700 px in steps of 10 for all six companies: neither table is ever wider than
its wrapper. A script loaded each market at 390 and 1280 px and switched through every company with the picker:
no script error, all eleven sections present, no chart text clipped by the chart or overlapping another chart text,
the price tag never narrower than its text, no "null" in the dialogs. Keyboard script: the arrow keys read the chart,
Escape clears, every tooltip element is focusable, the amount dialog opens, records a pending request and the horizon
tabs move the chart's exit line and the range cell together. Rebuild is byte-identical.

Judge round 1 (2026-10-08) found six blockers, all fixed before round 2: a script error when switching to a company
without predictions (stale spread state), "null" text in the deactivate dialog, chart labels clipped (the price tag
was a fixed width) and overlapping (ticks under the tag, the target label over the trade-mark counts), open-trade
rows mixing the check price with close-based figures, three nested keys missing from notes.md and agreement rows
copied unpicked, and a hard-coded "two companies".

## Decisions taken for the owner (reported to the orchestrator)
- The page opens with a decision card, not the chart: the spec's "decision card" is read as "what the strategies say
  today, in numbers a retail investor can act on without a calculator", with the plain-words line as the one
  sentence to read when in a hurry.
- The chart projects the reference strategy's ranges as a fan to N+5 and shows every strategy's target at the
  selected horizon as a spread, rather than fifteen target lines, to keep it readable; the Stock strategies page has
  each strategy's own numbers.
- The two tables sit full width above the two-column part, because the open-trade and settlement rows need the
  room and are read before the news; the narrative cards (AI reasons, results, settings; news, events) share the
  columns.
- The "why it moved" split is drawn as a diverging bar per trade so the market/sector/news/company story is read at
  a glance; the numbers stay in the tooltip.
- Change amount / deactivate are confirm dialogs that record a pending request (F10), never an immediate change,
  and delete is left to the Companies page's typed confirmation.
