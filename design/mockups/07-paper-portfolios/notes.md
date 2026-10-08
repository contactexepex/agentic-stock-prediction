# Paper portfolios mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1). Payload per market, `data.json` key `markets.<market>`. Top
level: `page`, `spec`, `endpoint`, `read_model`, `sources`, `as_of`, `cutoff`, `built_at`, `markets`, `_example`,
`_note`. Per market: `market`, `name`, `currency`, `as_of` (Market status `market`, `name`, `currency`, `as_of`),
`cutoff` (the catalogue files' shared `as_of`), `built_at` (Market status `freshness.built_at`), `horizons`,
`default_horizon`, then the keys below. `build.py` copies only the listed fields of every record (`pick`), except
`status`, which is the market's record whole; nested objects listed with `{...}` are copied with the keys named.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons, for the paper band |
| `strategies` | Strategy | `id`, `family`, `name`, `threshold`, `horizons`, `live`, `settled_trades` | all 15, keyed by id |
| `companies` | Company | `market`, `ticker`, `name`, `sector`, `state`, `amount`, `amount_overridden`, `currency`, `last_close`, `last_close_date` | the market's companies (names, links, the add-trade form's list of active companies) |
| `h2h_rows` | Scoreboard row | `scope`, `market`, `view`, `basis`, `strategy_id`, `family`, `pick_rule`, `horizon_days`, `trades`, `net_pnl`, `mean_return_pct`, `win_rate`, `target_reached_rate`, `avg_target_error_pct`, `range_hit_rate`, `worst_losing_streak`, `max_drawdown`, `sample_badge`, `first_entry`, `last_exit`, `as_of`, `luck_test.{method, n, m, low_pct, high_pct, excludes_zero, corrected_low_pct, corrected_high_pct, corrected}`, `your_cost.{net_pnl, mean_return_pct, win_rate, worst_losing_streak, max_drawdown, luck_test.{the same}}` | the market's head-to-head rows of scopes `strategy` (the family portfolios) and `pick_rule` (per pick rule), all horizons and per horizon |
| `open_trades` | Open trade | `trade_id`, `view`, `prediction_id`, `strategy_id`, `family`, `market`, `ticker`, `horizon_days`, `entry_date`, `exit_date`, `entry_price`, `quantity`, `amount`, `currency`, `target_price`, `lo80`, `lo50`, `hi50`, `hi80`, `last_price`, `last_price_date`, `unrealised_pnl`, `unrealised_pct`, `to_target_pct`, `paper` | every open trade of the market, by strategy |
| `trade_checks` | Intraday trade check | `id`, `check_at`, `session_date`, `market`, `ticker`, `trade_id`, `strategy_id`, `view`, `horizon_days`, `session_number`, `entry_price`, `last_price`, `ret_since_entry_pct`, `target_price`, `to_target_pct`, `band`, `flags`, `flagged`, `quality`, `high_since_entry_pct`, `low_since_entry_pct` | the latest check with `check_at` at or before `cutoff` |
| `owner.trades` | Owner's paper portfolio | `owner_trades[].{id, market, ticker, side, quantity, price, price_basis, trade_date, source, idempotency_key, entered_at, note, supersedes}` | the market's own trades with `entered_at` at or before `cutoff` |
| `owner.positions` | Owner's paper portfolio | `positions[].{market, ticker, quantity, avg_price, last_close, last_close_date, currency, cost, value, pnl, pnl_pct, eur_view.{ticker, quantity, mark_date, eurusd_at_buy, eurusd_now, fx_fee_rate, cost_usd, value_usd, cost_eur, value_eur, fx_effect_eur, pnl_eur, note}}` | the market's positions |
| `owner.default_amount`, `owner.paper` | Owner's paper portfolio | `default_amounts.<market>`, `paper` | |

Shown but computed by the page (presentation only): the KPI sums (open trades' unrealised, flagged count, positions'
value and profit), the per-strategy group sums, the filters, the luck bar geometry, the pending requests of the
add-trade dialog (mockup state, never sent).

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): the go-live bar's 2 months (SPEC F7.2),
two intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC section 6). The legend shows
sample values and says so.

Build: `python design/mockups/07-paper-portfolios/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/07-paper-portfolios/page.html design/mockups/07-paper-portfolios shot` and
`node design/system/check_text.js design/mockups/07-paper-portfolios/page.html`.
