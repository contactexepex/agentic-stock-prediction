# Strategy lab mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1). Payload per market, `data.json` key `markets.<market>`. Top
level: `page`, `spec`, `endpoint`, `read_model`, `sources`, `as_of`, `cutoff`, `built_at`, `markets`,
`_data_requests`, `_example`, `_note`. Per market: `market`, `name`, `currency`, `as_of` (Market status `market`,
`name`, `currency`, `as_of`), `cutoff` (the catalogue files' shared `as_of`), `built_at` (Market status
`freshness.built_at`), `reference_strategy` (the registry's reference rule strategy id), `horizons`,
`default_horizon` (`all`), `bases` (the distinct `basis` values of the rows), `backtest_run` (Back-test scoreboard row file, `runs.<market>.{history, first_date, last_date, eurusd, note}`: the run's facts shown on the Back-test basis), then the keys below. `build.py` copies
only the listed fields of every record (`pick`), except `status`, which is the market's record whole; nested objects
listed with `{...}` are copied with the keys named.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons, for the paper band |
| `strategies` | Strategy | `id`, `family`, `name`, `description`, `compared_to`, `differs_in`, `parameters` (the strategy's settings: `signal`, `news_weight`, `news_statuses`, `news_materiality`, `cross_market`, `regime_filter`, `model`, `inputs`, `sees_model_score`; which keys a strategy has depends on it), `threshold`, `horizons`, `live_from`, `live`, `settled_trades` | all 15, keyed by id |
| `companies` | Company | `market`, `ticker`, `name`, `sector`, `state` | the market's companies (names for the heatmap and the per-company table) |
| `rows` | Scoreboard row | `scope`, `market`, `view`, `basis`, `strategy_id`, `family`, `pick_rule`, `ticker`, `regime`, `horizon_days`, `trades`, `net_pnl`, `mean_return_pct`, `win_rate`, `target_reached_rate`, `median_reached_session`, `avg_target_error_pct`, `range_hit_rate`, `worst_losing_streak`, `max_drawdown`, `sample_badge`, `first_entry`, `last_exit`, `as_of`, `luck_test.{method, n, m, low_pct, high_pct, excludes_zero, corrected_low_pct, corrected_high_pct, corrected}`, `your_cost.{net_pnl, mean_return_pct, win_rate, worst_losing_streak, max_drawdown, luck_test.{the same}}`, and on `strategy` rows `go_live.{proven, months_forward, trades_needed, beats_best_baseline, best_baseline_net_pnl, drawdown_limit, drawdown_within_limit, holds_in_calm_and_volatile, cost_view}` | every row of the market: scopes `strategy` (all horizons and per horizon), `strategy_company`, `strategy_regime`, `pick_rule`; both views; every basis stored: `forward` from the Scoreboard row file and `backtest` from the Back-test scoreboard row file (`scoreboard_backtest_row.json`, scope `strategy` only, the same fields except no `as_of`, no `go_live`, no `pick_rule`, `ticker` or `regime` (set to null), and `your_cost.{net_pnl, mean_return_pct}` only); the page filters every table on the basis, never pooling them |
| `trades` | Paper trade (settled) | `trade_id`, `strategy_id`, `family`, `view`, `pick_rule`, `ticker`, `horizon_days`, `entry_date`, `exit_date`, `exit_date_actual`, `status`, `amount`, `currency`, `net_pnl`, `return_pct`, `reason_code`, `reason_codes`, `regime`, `settled_at` | the market's settled trades with `settled_at` at or before `cutoff`, by exit date (the cumulative lines and the reason-code heatmap) |

Shown but computed by the page (presentation only): the ranking order (profit after market cost, then trades; strategies
without trades follow by family, then id); the KPI picks (leader, best baseline, how many beat it, nearest to
go-live); the luck bar geometry; the per-horizon, per-regime and per-company bars of the detail card; the cumulative
sums per strategy by exit date; the heatmap cells by horizon, company and regime (scoreboard rows) and by reason code
(counts and sums of the settled trades' `reason_code`); the colour scale (largest absolute cell = darkest). Heatmap cells show a compact profit: at most three significant digits with a unit (k; lakh L and crore Cr for rupees, M for dollars), the sign always, no currency symbol (the metric switch names the currency).

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): the go-live bar's 2 months (SPEC F7.2),
two intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC section 6). The legend shows
sample values and says so.

Data requests to W1 (`_data_requests` in data.json), both answered on 2026-10-08: scoreboard rows with basis
`backtest` (F2.3), answered with `scoreboard_backtest_row.json` (always-up and momentum on the stored bars, without the
15-year history cache; model-only and the rule strategies not run), now read into `rows` and shown on the Back-test
basis with the run's facts (`backtest_run`); weekly scoreboard rows and a per-reason-code scope for the F2.8 heatmaps
over time, answered with `heatmap_cell.json` and `cumulative_line.json`, not read yet (the mockup still derives the
heatmaps and the lines from the settled trades of the one stored week; reading the cells is a follow-up).

Build: `python design/mockups/05-strategy-lab/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/05-strategy-lab/page.html design/mockups/05-strategy-lab shot` and `node design/system/check_text.js
design/mockups/05-strategy-lab/page.html`.
