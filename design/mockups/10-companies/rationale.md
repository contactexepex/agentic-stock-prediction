# Companies mockup: rationale

Page 10 of docs/SPEC.md section 6 (F8 company lifecycle, F10 governed tools; decisions 12-15, 20, 26, 33, 44),
designed in the design track from W1's data catalogue. Status: **built on the owner's delegated authority**
(2026-10-08, the owner away: "go with your recommendation, notify the orchestrator"; the owner asked that
configuration pages be judged on how they are used, usability and ease of access); judged and landed by the track;
the owner reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example payload of `GET /api/v1/markets/{market}/companies`, read model `rm.companies`), `page.html`,
`notes.md`, screenshots `shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png`.

## Who reads it and how
The owner managing the watchlist: who is being predicted, who is paused, what each company's paper amount is, what
requests are waiting, and what changed when and through which channel. It is the one configuration page, so every
action is a short dialog that says what will happen and when it takes effect, and every write is a recorded request
imported by the next run, never an immediate change. The page carries no signal and never says buy or sell.

## Layout (desktop: KPIs, two tables, two columns; phone: one column, actions behind one Manage button)
1. **Page head** (count, as-of, chips) and **KPIs**: active companies, inactive ones (named), the market's default
   amount per paper trade with how many companies have a custom one, pending requests.
2. **Active companies** with the **Add company** button: company (ticker linked to its page, name, sector,
   exchange), last close and day move, amount per paper trade (a "custom" tag when it differs from the default,
   decision 44), how many strategies buy at N+1 today (decision 30), open paper trades, on the list since (the seed
   counts from the start of stored history), identifiers (Yahoo, NSE or CIK), and the actions **Amount**,
   **Deactivate**, **Delete**. Columns by width: identifiers from 1360 px, buyers and open trades from 1200 px, the
   list date from 901 px; below 1200 px the action buttons are icons with accessible names, below 901 px a single
   **Manage** button opens the actions, and below 600 px the amount moves under the company name.
3. **Inactive companies** (decision 13: shown here only): since when, with the deactivation reason in the requester's
   words, last close, news stored since (titles in the tooltip; the example data holds none), open paper trades
   (they still settle), and **Reactivate** and **Delete**.
4. **Requests** (F10): pending requests recorded on this page (mockup state) and the recent company commands from
   any channel with who asked (from the channel's sign-in), the result (accepted, pending, refused, duplicate,
   failed), the message and the refusal reason; a company deleted later is masked (decision 12).
5. **Lifecycle history** (F8): every add, deactivate, reactivate and amount event of the shown companies, newest
   first, with the channel, the requester, when it counts (the next pre-open run; the seed from the start of stored
   history) and the onboarding checks of a real add; the count of excluded delete tombstones in the head.
6. **Dialogs**: **Add** asks for the exchange symbol, an optional name and amount (F8.3), then a **summary step**
   with Confirm and Cancel (F8.7; the real page fills the summary from the identifier check: name, exchange, sector,
   Yahoo symbol, CIK, amount); **Amount** shows the current value and the India one-share rule; **Deactivate /
   Reactivate** say what stays collected and when it takes effect (F8.4); **Delete** carries a warning, requires the
   ticker typed exactly (the button stays disabled until then), says it is dashboard-only and what a tombstone does
   (F8.5). Confirming records a pending request on the page; nothing is sent (mockup).
7. **Legend** and **footer**.

## Data and contract
- `data.json` is composed from eight catalogue files only (`notes.md` lists each field). Selection and ordering only;
  the page computes counts and the pending state.
- No look-ahead: lifecycle events by `recorded_at`, commands by `received_at`, news by `first_seen_at`, all at or
  before the cut-off.
- Decision 12 on read: the catalogue's company list holds no deleted company; its lifecycle events are excluded and
  counted, and its symbol and name are masked in the command log's echo. No new data request.

## Design rules kept
Design system v2 only; light theme; phone and desktop (both tables fit their wrapper at every width 390-1700 px in
both markets); never colour alone (results and events as labelled badges, the sign on every number, the delete
button's warning in words); keyboard: every action is a button with an accessible name, the dialogs are native
`<dialog>` elements with a labelled title, Escape closes them, every tooltip focusable; plain language; Paper in the
head chips and the legend ("every trade is a paper record"); research only.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. A sweep of 390-1700 px in steps of 10, both
markets: neither table wider than its wrapper. A script ran the add flow (symbol -> summary -> confirm), the delete
dialog (the button is disabled until the ticker is typed, case-insensitive) and a reactivation; the pending list and
the KPI count them; no script error; every tooltip element focusable; neither market's page names the deleted
company. Rebuild is byte-identical.

## Decisions taken for the owner (reported to the orchestrator)
- Active and inactive companies are two tables rather than one with a state filter, because the spec gives the
  inactive ones their own section with their own columns (news since, reactivate).
- Every write is a dialog that ends in a recorded, pending request (F10), with delete behind a typed confirmation
  and dashboard-only, as F8.5 requires; the add flow shows the summary step of F8.7 even though the mockup cannot
  resolve identifiers.
- A company deleted later is masked everywhere on the page (its events excluded, its echo in the command log
  replaced), following decision 12 even in example data.
- On phones the three row actions collapse into one Manage button that opens the same dialogs, so the table stays
  readable without hiding actions.
