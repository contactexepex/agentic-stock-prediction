# Paper portfolio page: redesign proposal (UX3)

Status: **proposal, waiting for the owner's approval.** Nothing is built yet.

Mockup: `docs/ux/paper_portfolio_redesign/mockup.html`, with screenshots `shot-desktop.png` (a row expanded) and
`shot-phone.png` (390 px). It uses real India data as built at Mon 12 Oct 2026, 18:31 IST: 209 strategy trades
entered on 12 Oct, 14 Rule vs AI picks and no own trades. The blue notes in the mockup explain the design and are not
part of the page. The US has no trades yet, so the US page shows the empty states.

## The problem

Today the page stacks five blocks: a KPI row, "All paper trades in one place", the head-to-head scoreboard,
"Open paper trades by strategy" and your own portfolio. "All paper trades" puts every hold (N+1 to N+5), every state
and every result in one 9-column table, opened by *entry* session. A 5-day hold therefore sits on a different entry
session page than a 1-day hold that sells on the same day. The page never answers the plain question: "which of
these are working?"

## The new page: five sections, in the order a reader asks

1. **How are the paper trades doing?** Three tiles that are never added together: *Every strategy's trades*
   (the accuracy view), *Rule vs AI picks* (the head-to-head view) and *Your own trades*. Each tile reads:
   "N open · N finished · W won, L lost", then the net after fees, then the open trades' result so far before fees.
2. **What finished recently?** This section shows finished trades only, grouped by the day they **sold** (chips
   for the last 10 sessions, newest first). Each row has 5 columns: Company, Who, Hold, Result, Net after fees
   (✓ made money or ✗ lost money: an icon and words, not colour alone). Tapping a row shows the buy and sell prices,
   both fee views and the automatic reason. Empty state: "The first 1-day holds sell at the close of Tue 13 Oct;
   their results show here after the after-close run (about 17:45 IST)."
3. **What is still open?** There is one tab per hold length, for example "1-day hold · 39". A tab appears only when
   that hold has trades; the baselines also hold for 2 and 4 days. Each tab opens with a line such as "Bought at the
   open of Mon 12 Oct · sells at the close of Tue 13 Oct", then the split "✓ 4 going as predicted · ✗ 35 going
   against (7 ⚠ well against) · … 0 no price yet". It then shows **three separate lists**:
   - ✓ **Going as predicted**: the price is above the buy price. Every paper trade is bought on an "up"
     prediction, so a rise means the prediction is holding so far.
   - ✗ **Going against the prediction**: the price is at or below the buy price. ⚠ marks the trades whose latest
     intraday check is flagged "against the prediction" (more than a usual day's move below the buy price). These
     are listed first and tinted.
   - … **No price yet**: the trade was bought at the open but has no check or close yet.

   Each list shows 8 rows, then "Show N more". The columns are Company, Who, Bought at, Now and So far, plus the
   expand arrow. On a phone only Company, Who and So far are shown. Tapping a row shows the shares and the amount,
   the sell date, the price's source and time, the expected range at the sale (a bar with "bought" and "now"
   marked), the latest check in words, why the trade was bought (the strategy's chance of going up, and the AI
   trader's own words), and links to the company and the strategy. A "Who" filter (All · Rule · Baselines · AI)
   sits above the tabs.
4. **Rule vs AI picks.** This keeps today's head-to-head scoreboard, with the cost switch, the luck test and the
   per-pick-rule rows. Below it are its open picks, in the same tab and list layout as section 3. These picks come
   from the same predictions as section 3, so the two sections are never added together.
5. **Your own paper trades.** The content is unchanged: positions, the euro view for US positions, recorded trades,
   the "Add own paper trade" form and its pending receipts. It now starts with a one-line summary.

The page loses the KPI row, the "All paper trades in one place" card (its 9-column table, the entry-session picker
and the filter chips), and the "Open paper trades by strategy" card. The cost switch moves into section 4, the only
section it changes. The header, the signals band, the Paper label and the "Technical details" footer stay.

## Data changes (additive only; nothing is removed from the contract)

The page needs open trades by hold and finished trades by sell day. Today the accuracy view is only paged by entry
session, so the read model gains these, as of the cut-off as now:

- **`rm.portfolio` page `open:<k>`**: every open accuracy-view trade of hold k, whatever its entry session. It is
  served by `GET /api/v1/markets/{market}/portfolios/open/{k}` and indexed by a new `all_trades.open_holds`:
  `[{horizon_days, open, going_with, going_against, flagged, pending, exit_dates}]`. The tab counts come from this
  index without fetching every list.
- **`rm.portfolio` page `finished:<D>`**: every accuracy-view trade that sold on session D, for the last 10
  sessions. It is served by `GET /api/v1/markets/{market}/portfolios/finished/{date}` and indexed by
  `all_trades.finished_sessions`. The head-to-head trades and your own trades already sit whole on page `_`.
- **New optional row fields**: `prob_up` and `reason` (from the prediction: the AI trader's own words, null for rule
  strategies), and `reason_code` on finished rows (the automatic reason, F1.10).
- The `trades:<D>` pages, `all_trades.sessions` and their route stay, so nothing that reads them breaks.

The contract gains `api/paths|schemas/paper-portfolios.yaml` entries for the two routes and the new optional
fields. `tests/test_openapi.py` and `tests/test_api_contract.py` stay green, because the new keys are added to the
page's `extra_keys`.

## Rules kept

Every figure is labelled Paper, and nothing on the page says buy or sell. Times are in the market's zone (IST or ET).
"Won" means the trade made money after fees: market fees for strategies, your fees for your own trades. Open trades
are before fees. The two views are never pooled. No table has more than 6 columns. Every empty section says when it
fills.

## Questions for the owner

1. Are tabs for every hold that has trades (1 to 5 days) right, rather than only 1, 3 and 5? The baselines trade all
   five holds.
2. Is "above / below the buy price, before fees" the right test for "going as predicted"? The stricter "⚠ well
   against" mark comes from the intraday check.
