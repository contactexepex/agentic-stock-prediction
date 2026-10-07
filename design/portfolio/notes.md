# Notes: queries and inputs behind portfolio.html

Built 2026-10-07 (UTC); repo read only. `python design/portfolio/build.py --out <dir>` (about 40 s: it
rebuilds the model panel and the walk-forward out-of-sample rows for both markets).

- Live book: `predictions p left join outcomes o on o.prediction_id = p.id` (as_of_date, ticker, horizon,
  direction, confidence, model_prob; entry_date, entry_open, target_date, target_close, actual_return, hit);
  cost = `round_trip_cost(market, costs, entry_open)`; net = actual_return − cost; P&L = net × 10,000.
  0 rows in both markets. First live range as_of: `min(as_of_date) from ranges` = 2026-10-01.
- Rehearsal book: `build_panel(cfg, read_inputs(con, market), warmup)` → `walk_forward(panel, (market,
  'open_to_close', 5), settings)` → `with_trade_columns(oos[up notna], panel, 5)` → `paper.prepare(done,
  market, costs)` (entry_open, cost, net). Books per threshold of config/model.yaml (0.55, 0.60, 0.65):
  rows with prob ≥ t. Statistics: per-date mean of net (the back-test's measure), cumulative × 10,000 for the
  running total, per-trade win share, best/worst, max drawdown of the running total, by month, by ticker.
- Check: the mean per day and the number of trades per threshold against
  `work/design/bt-<market>/model-backtest-<market>-<date>.json` → identical for every threshold:
  India 0.55 1592 / −0.6947%, 0.60 999 / −0.1724%, 0.65 403 / +0.2753%; US 0.55 1970 / +0.4036%, 0.60 1 /
  −5.4934%, 0.65 0 trades.
- Costs: India 0.2225% per round trip (₹22.25 on ₹10,000); US 0.0021% ($0.21).
