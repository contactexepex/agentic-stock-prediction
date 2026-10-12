# Paper portfolio page: redesign proposal (UX3)

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
