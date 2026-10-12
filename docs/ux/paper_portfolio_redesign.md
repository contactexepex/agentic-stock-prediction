# Paper portfolio page: redesign proposal (UX3)

Status: **v3 approved by the owner on 2026-10-12 (light mode only; dark mode is a separate later change) and
built.** The implementation notes follow; v1 and v2 are kept further down for reference.

## Implementation (UX3 build)

| Part | Code |
|---|---|
| The page: hero, side cards, the daily picks, your own trades, finished trades, hold blocks, what the system learns | `web/app/(cockpit)/[market]/paper-portfolios/_parts/paper-portfolios-page.tsx`, `hold-block.tsx`, `story-ui.tsx`, `paper-portfolios.css` |
| Unchanged parts moved into their own files | `owner-card.tsx` (positions, euro view, the add-trade form), `h2h-card.tsx` (the Rule vs AI scoreboard with the luck test, now under "Scoreboard after fees") |
| Plain words, going with or against, merged rows, the one-line reasons, the story link | `web/lib/strategy-pages/portfolio-v3.ts` (tests in `lib/strategy-pages/tests/portfolio-v3.test.ts`) |
| "The full story" view | `web/app/(cockpit)/[market]/stocks/[ticker]/lifecycle/[date]/_parts/story.tsx`, opened by `#story=<prediction>&trade=<trade>` |
| Routes | `GET /api/v1/markets/{market}/portfolios/open/{hold}` and `.../portfolios/finished/{date}` (`web/lib/data/paper-portfolios.ts`) |
| Read model | `scripts/marketbrief/warehouse/trade_why.py` (each row's `why`, `direction`, `prob_up`, `reason`, `sessions`; the `learning` block; the lifecycle additions), `trade_pages.py` (`open:<k>`, `finished:<D>` and their indexes), wired in `all_trades.py`, `rm_portfolio.py`, `rm_company.py` |
| Contract (additive) | `api/paths/paper-portfolios.yaml`, `api/schemas/paper-portfolios.yaml` (PortfolioHold, PortfolioFinished, OpenSplit, OpenHold, FinishedSession, TradeWhy, PortfolioLearning; new optional row fields), `api/schemas/company.yaml` (LifecyclePage: `checks_attribution`, `deviation_notes`, `lessons`, `prediction_reasons`) |
| Tests | `tests/test_b13_all_trades.py`, `tests/test_ux3_trade_why.py`, `web/lib/data/tests/b13-pages.test.ts`, UI harness `web/tests/ui/cases/paper-portfolios.mjs` on the real stored pages in `web/tests/ui/ux3/` |

Where the build differs from the mockup, and why:
- **The hero gives no "% of the amount traded".** The payload carries no traded amount per side, and adding one only
  for this line was not worth it. The hero shows the result so far, the open, finished, won and lost counts, the
  win/lose bar and the first results line.
- **"Price vs expected" uses the app's existing range bar** (the 50% and 80% bands, the target, a dotted buy line
  and a dark "now" line; the header's tooltip explains it) rather than the mockup's dot, so it matches the company
  pages.
- **The progress bar towards the sale counts market sessions exactly.** A new row field, `sessions` (held of
  k + 1), comes from the market calendar, so the bar never estimates.
- **The finished-trades illustration is not on the page.** With nothing finished, the page shows the empty state
  only. The UI harness checks the finished layout on a day made from the 1-day hold's trades.
- **The lifecycle page carries `prediction_reasons`.** The AI trader's own words for each prediction are added
  here, so the story can quote them; the page's prediction fields stay as they were.
- **A read model built before UX3** shows "This page fills after the next data sync" in place of the new sections.
  Your own trades and the add form still show.

## v3 (owner feedback of 2026-10-12, second round)

Files in `paper_portfolio_redesign/`:
- `mockup-v3.html`: the page.
- `story.html`: the "Full story" of one trade.
- `make_mockup_v3.py`: rebuilds both mockups.
- Screenshots: `v3-{desktop,phone}-{light,dark}-top.png`, `v3-{desktop,phone}-light-hold.png` (a "why" popover
  open), `v3-{desktop,phone}-light-full.png` and `v3-story-{desktop,phone}-{light,dark}.png`.

The mockup uses real stored data for India, as built at Mon 12 Oct 2026, 18:31 IST:
- `rm.portfolio`;
- the latest intraday check of each ticker (market, sector and own move);
- the deviation-explainer notes;
- the predictions' chance of a rise and the AI reasons;
- the week-41 research review.

Only the finished-trades rows are an illustration with sample numbers, labelled as such: nothing has finished yet.
At 390 px there is no horizontal scroll (`scrollWidth` 390), and no table overflows its card.

### The reader's questions, in order

1. **Am I up or down?** One hero card for every strategy's open trades:
   - the result so far, large, coloured and with an arrow (−₹2,13,564);
   - "−1.0% on ₹2.06 crore in 209 open trades, before fees";
   - "Nothing finished yet — first results Tue 13 Oct, ~17:45 IST";
   - open / finished / won · lost;
   - a bar of trades going as predicted against trades going the other way.
2. **Which bets are working?** Three side cards, side by side: Rule strategies, Simple benchmarks and AI traders.
   - Each card shows its result so far, a win/lose bar, the as-predicted and against counts, and finished, won and
     lost.
   - When Rule has no trades, its card says "No trades today: the signal model saw no clear rise ⓘ". The popover
     gives the reason: the highest chance today was 50%, below its 55% bar.
   - Next to the cards: "Rule vs AI: the daily picks" (Rule side and AI side) and "Your own trades".
   - These views are never added together.
3. **Why?** Every losing trade carries the reason in three layers:
   - **One line, always visible**, from the latest intraday check. Examples: "Fell mostly on its own (−2.9%); the
     market added −0.7%. Its sector −2.0%." or "Fell with the whole market (Nifty −1.0%, so −1.5% for this stock);
     −0.9% on its own." When a deviation-explainer note exists, an "AI note" chip sits beside the line.
   - **An ⓘ popover**: what was expected (the chance of a rise and the range), what happened so far, the main cause
     and the sell date.
   - **"Full story →"** opens `story.html`, which is the company page's lifecycle view. It has:
     - the trade's hero;
     - "Why is it going against the prediction?": bars splitting the move into the whole market's part and the
       company's own part, plus the sector as context;
     - "What happened, step by step": the prediction with its AI reason, the buy, each check with its split and AI
       note, then the steps still to come;
     - "What the system learned".

   Finished losses get the same line from B2's automatic reason and the end-of-day AI reason.
4. **What does the system learn?** A card with three parts, described honestly:
   - **Lessons**: written after each AI forecast settles. Only the AI forecaster reads them, from the next morning.
     None exist yet.
   - **End-of-day reasons**: they explain and change nothing. The first ones come after the close of Tue 13 Oct.
   - **Weekly research review**: it proposes changes and nothing changes without the owner's approval. The card
     quotes the real week-41 finding: no change was proposed, and the next review is Fri 16 Oct.

   The card also says that rule strategies and simple benchmarks never adjust themselves.

### Plain words

- "Baseline" becomes **"Simple benchmarks"** (ⓘ: the yardsticks the others must beat), and "Rule" becomes **"Rule
  strategies"**.
- The section titles are questions.
- Explanations live in ⓘ popovers.

### Open trades

There is one block per hold length (1–5 days), always visible and never in tabs. Each block has:
- a header with the sell date, a progress bar towards the sale, and the result so far;
- a Rule · Benchmark · AI strip (count, win/lose bar, ✓/✗, result so far);
- the losing trades first, each with its reason line, then the trades going as predicted.

Rows with identical trades from strategies on the same side are merged. For example, "Always buy + Follow
yesterday" for the same stock becomes one row marked ×2, with the two results added. Each list shows 3 rows, then
"Show N more".

The columns are Company, Who, *Price vs expected* (a small range bar: the tick is the buy price, the dot is now)
and So far. On a phone, Who moves under the company and the range bar is hidden.

### Visual design

The page stays on Material 3 with the app's tokens, components and icon sprite:
- a large hero figure, an 8 px spacing grid and borderless cards;
- tabular, right-aligned ₹ figures with Indian grouping, and signed values shown with both colour and an arrow;
- red and green used for money and the win/lose bars only;
- side colours from the chart tokens;
- polished empty states.

Dark mode uses `design/system/tokens-dark.css`. The owner decided on 2026-10-12 to leave it out of this change; it
came app-wide as its own change (UX4, 2026-10-12): the web app imports the file and the top bar has a light / dark /
system toggle.

### Additive data for v3, beyond v2's

- **Open rows:** the latest check's `market_pct`, `sector_pct`, `own_pct` and `beta` (from intraday_checks), the
  latest deviation-explainer note's text (from intraday_explanations), and `prob_up`, `direction` and `reason` (from
  strategy_predictions).
- **Finished rows:** B2's automatic reason (reason_code and its market, sector, news and company parts) and the
  end-of-day AI reason (trade_reasons_ai), when there is one.
- **rm.portfolio `_`:** a small `learning` block with:
  - the lessons count and the newest lesson (lessons);
  - the newest research review's week, its first finding, its proposals count and the next review's date
    (research_reviews);
  - for the empty Rule card, the highest rule `prob_up` of the session and the bar.
- **rm.lifecycle** (B12's page, additive): `checks_attribution` (per check: market, sector and own move, and beta)
  and `deviation_notes` (intraday_explanations for the ticker within the page's window), plus `lessons` and
  `eod_reasons` for the page's trades. The prediction, its chance, the AI reason, the range, the trade checks, the
  settlement and the AI reasons are already on it. The "Full story" link points to
  `/[market]/stocks/[ticker]/lifecycle/[entry date]`.

---

## v2 and v1 (superseded)


Status: **revised proposal (v2), waiting for the owner's approval.** Nothing is built yet.

This version applies the owner's feedback on v1, given on 2026-10-12. v1 (`paper_portfolio_redesign/mockup.html`,
`shot-*.png`) is kept for reference.

Mockup v2: `paper_portfolio_redesign/mockup-v2.html`. It uses the app's own `web/styles/tokens.css`,
`components.css` and fonts, and the icon sprite from `design/system/icons.svg`. Screenshots:
- `v2-desktop-top.png` and `v2-desktop-hold.png` (one row's popover open)
- `v2-phone-top.png` and `v2-phone-hold.png`
- `*-full.png` for the whole page

The data is the real India `rm.portfolio`, built at Mon 12 Oct 2026, 18:31 IST: 209 strategy trades and 14 Rule vs
AI picks, all open. To rebuild the mockup, run `make_mockup_v2.py <repo> <payload.json> <out.html>`. Tinted notes on
the page explain the design and are not part of it. Nothing has finished yet, so "What finished recently" shows a
labelled **illustration with sample numbers**; these are not stored results.

## Page, top to bottom

1. **How are the paper trades doing?** Each box is split by side, and the sides sit next to each other:
   - **Every strategy's trades**: one table with a row each for Rule, Baseline and AI. The columns are Open, Finished,
     Won, Lost, Net after fees, and Open so far (before fees).
   - **Rule vs AI picks**: a Rule side card and an AI side card, each showing open, finished, won and lost, net after
     fees, and open so far.
   - **Your own trades**: open and finished counts, plus the add-trade button.

   These views are never added together.
2. **What finished recently?** Filter chips for the day the trades sold, covering the last 10 sessions. Below them, a
   comparison strip for Rule, Baseline and AI (won, lost, net after fees), then a lean table: Company, Who (a side
   tag and the strategy), Hold, Won or Lost (a label with an icon), Net after fees, and ⓘ. The ⓘ popover gives the
   stored reason: the automatic reason saying whether the market, the sector, the news or the company drove the
   move. It also gives the buy and sell prices and the result after your fees.
3. **Still open: every strategy's trades.** There are **no tabs**. Each hold length that has trades (1, 2, 3, 4 and
   5 days) gets its own block, always visible and stacked. Each block has:
   - a header: "N-day hold", when it sells, the number open, and the result so far before fees
   - chips: ✓ as predicted, ✗ against (with ⚠ for trades far against at the latest check), and no price yet
   - a **Rule · Baseline · AI comparison**: open, as predicted, against, profit so far, loss so far and net so far
     (the profit and loss columns are hidden on a phone)
   - the trade table, split into "✓ Going as predicted" and "✗ Going against the prediction", each with its count
     and net. It shows 3 rows, then "Show N more". Its columns are Company, Who, Bought at, Now, So far and ⓘ; a
     phone shows Company, Who, So far and ⓘ. The ⓘ popover holds the shares, the sell date, the expected range, the
     latest check and why the trade was bought.
4. **Still open: Rule vs AI picks.** The same blocks, with a Rule vs AI comparison only, because the baselines never
   pick. The head-to-head scoreboard (luck test, the two pick rules, the cost switch) moves into an ⓘ or "details"
   area of this section's summary.
5. **Your own paper trades.** Positions, the euro view, recorded trades and the add form, all as now.

Explanations sit in ⓘ popovers and header tooltips instead of paragraphs. The page leads with numbers.

"Going as predicted" means above the buy price, before fees, for an "up" call; a "down" call flips the test (owner,
2026-10-12). Every paper trade today is bought on an "up" call, so the build adds `direction` to the rows and the
test reads it.

## Visual design

The design follows Material 3 through the app's own tokens and components (B7):
- `md-card` surfaces on `surface-container-low`, with the type scale (headline-small, title-large and
  title-medium, body, label)
- `md-chip` for the chips (filter chips for the sell day), `md-table` for the tables, `mb-label`
  success and danger for won and lost, `mb-delta` for money, and `md-tooltip-rich` for the popovers
- the side colours from the chart tokens (Rule = chart-1, Baseline = chart-2, AI = chart-3), always shown with
  the side's name
- Material Symbols from the sprite, so the icons are never colour alone

Both themes work through the existing tokens. At 390 px the page has no horizontal scroll (measured: `scrollWidth`
is 390).

## Data changes (additive only)

- **`rm.portfolio` page `open:<k>`**: every open accuracy-view trade of hold k, served by
  `GET /api/v1/markets/{market}/portfolios/open/{k}`. Its index `all_trades.open_holds` holds, per hold: the counts
  and the profit, loss and net so far per side, so the comparison strips render without loading the lists.
- **`rm.portfolio` page `finished:<D>`**: every accuracy-view trade that sold on session D, for the last 10
  sessions, served by `GET .../portfolios/finished/{date}`. Its index `all_trades.finished_sessions` holds the
  per-side won, lost and net.
- **New optional row fields**: `direction`, `prob_up`, `reason` (the AI trader's words), and on finished rows
  `reason_code` with the automatic reason's parts (market, sector, news and company %).
- `trades:<D>`, `all_trades.sessions` and their route stay. The head-to-head and own trades stay on page `_`.

## Rules kept

Paper on every figure and never buy or sell advice; times in IST or ET; the views are never pooled; at most 7
columns on desktop and 4 to 5 on a phone; every empty section says when it fills.
