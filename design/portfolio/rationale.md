# Paper portfolio screen: rationale

Files: `template.html` + `build.py` (`--out DIR`, both markets, in-page India/US switch), `portfolio.html`
(self-contained, no network), `data-portfolio.json`, screenshots `shot-*.png`, `notes.md`. Same shell and
design system as the other screens (`design/system/`).

## What it is for
The owner's question "would following it have made money?" answered with a pretend account that follows the
cockpit's plan to the letter, 10,000 per trade, after real costs. Nothing trades. Two books per market:
- the **live book**: every live call stored in `predictions` with its outcome once scored (none yet on 7 Oct:
  the page says so and when the first trade would appear);
- the **rehearsal book** (back-test): the walk-forward model's out-of-sample rows, the exact rows
  `scripts/model_backtest.py` scores for its paper strategy, so the trades and the mean per day match the
  back-test JSON; a check table on the page proves it.

## Layout
1. **Guide**: what the page is, the rule (follow the model from the 60% Paper-candidate line; buy next open; sell close of D+4; costs),
   live vs rehearsal, green profit / red loss.
2. **Live book**: a sentence, four tiles (open, closed, profit or loss after costs, trades that made money),
   the trade table when trades exist.
3. **Rehearsal book**: a 55/60/65% selector ("follow the model when it is at least … sure"), a plain
   sentence (trades, days, total, per-trade average, win share, against buying everything), six tiles (trades,
   book total, average per trade on the back-test's per-day measure, win share, largest drop, best/worst
   trade), the running-total chart against "buy everything" (zero line = break-even).
4. **Month by month** and **company by company** tables (trades, made-money share bar, per-trade, total;
   companies link to their decision pages).
5. **The trades**, newest first (newest 400 kept per book; 15 shown, button for all): called on, company,
   how sure, bought at, sold at, move, costs, after costs.
6. **The rules of the book** in plain words and the **check against the back-test** table.
7. Collapsed data sources.

## Real, back-test, derived
- Live: predictions + outcomes (+ costs at the entry open).
- Back-test: the model's out-of-sample rows with entry open and return, re-derived with the back-test's own
  library (model.walk_forward, model.backtest.with_trade_columns, model.paper.prepare) and checked against
  the JSON.
- Derived: running total = cumulative sum of each day's average net return × 10,000; win share; largest drop;
  per-month and per-company totals.

## Checked
Playwright, pre-installed Chromium, 1280 and 390 px: no console errors, no horizontal scroll, no external
requests. India 60%: 999 trades on 76 days, mean per day −0.1724%, identical to the back-test JSON.
