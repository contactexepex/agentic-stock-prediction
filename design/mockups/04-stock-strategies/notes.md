# Stock strategies mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1). One payload per (market, ticker); `data.json` key
`markets.<market>` holds the example company of each market (RELIANCE, NVDA). Top level: `page`, `spec`, `endpoint`,
`read_model`, `sources`, `as_of`, `cutoff`, `built_at`, `markets`, `_pages`, `_example`, `_note`. Per payload:
`market`, `ticker`, `name`, `currency`, `as_of` (Market status `market`, `name`, `currency`, `as_of`; `ticker` the
page's company), `cutoff` (the catalogue files' shared `as_of`), `built_at` (Market status `freshness.built_at`), then
the keys below. `build.py` copies only the listed fields of every record (`pick`).

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (the two blocks W1 added on 2026-10-08 ride along in the copied record; this page does not show them) | the market's record, whole |
| `company` | Company | `market`, `ticker`, `name`, `exchange`, `sector`, `state`, `amount`, `amount_overridden`, `currency`, `last_close`, `last_close_date`, `change_pct`, `agreement_n1.{buy, of}`, `open_trades` | the page's company |
| `agreement["1".."5"]` | Agreement | `market`, `as_of_date`, `session_date`, `rank`, `ticker`, `name`, `horizon_days`, `buy`, `of`, `by_family.{rule,baseline,ai}.{buy,of}`, `avg_prob_up`, `label`, `paper` | this company's row per horizon |
| `head_to_head` | Head-to-head pick | `id`, `market`, `ticker`, `made_at`, `as_of_date`, `session_date`, `family`, `pick_rule`, `status`, `strategy_id`, `strongest_basis`, `ranking[].{strategy_id, rank, basis, settled_trades, net_pnl}`, `horizon_days`, `prediction_id`, `base_close`, `prob_up`, `move_pct`, `loss_pct`, `costs_pct`, `expected_gain_pct`, `candidates[].{horizon_days, prediction_id, prob_up, move_pct, loss_pct, costs_pct, expected_gain_pct, gain_per_session_pct, expected_move_pct, your_cost_pct, expected_gain_your_pct, cost_viable, eligible}`, `amount`, `currency`, `method_version` | this company's picks for the session being predicted, `made_at` at or before `cutoff` |
| `predictions` | Prediction | `id`, `strategy_id`, `family`, `ticker`, `made_at`, `as_of_date`, `session_date`, `exit_date`, `horizon_days`, `direction`, `prob_up`, `confidence`, `threshold`, `qualifies`, `base_close`, `target_price`, `lo50`, `hi50`, `lo80`, `hi80`, `range_widen`, `model_prob`, `agent_adjustment`, `adjustment_reason`, `evidence_ids`, `reason`, `regime`, `quality`, `amount`, `currency` | this company's predictions for the as-of date, `made_at` at or before `cutoff` |
| `on_company` | Scoreboard row | `scope`, `market`, `view`, `basis`, `strategy_id`, `family`, `ticker`, `horizon_days`, `trades`, `net_pnl`, `mean_return_pct`, `win_rate`, `target_reached_rate`, `median_reached_session`, `avg_target_error_pct`, `range_hit_rate`, `worst_losing_streak`, `max_drawdown`, `sample_badge`, `first_entry`, `last_exit`, `luck_test.{method, n, m, low_pct, high_pct, excludes_zero, corrected_low_pct, corrected_high_pct, corrected}`, `as_of` | `scope` = `strategy_company`, accuracy view, this company (all horizons and per horizon) |
| `overall` | Scoreboard row | the same fields | `scope` = `strategy`, accuracy view, all horizons (the best overall and the "overall" column) |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons |
| `strategies` | Strategy | `id`, `family`, `name`, `description`, `compared_to`, `differs_in`, `parameters` (the strategy's settings: `signal`, `model`, `inputs`, `news_weight`, `news_statuses`, `news_materiality`, `regime_filter`, `cross_market`, `sees_model_score`; which keys a strategy has depends on it), `threshold`, `horizons`, `live`, `settled_trades` | all 15, keyed by id |
| `horizons`, `default_horizon` | (setting) | `config/strategies.yaml` horizons 1-5; N+1 opens (decision 39) | |

Shown but computed by the page (presentation only): the ranking order (profit after costs, then trades), the best
row per scope, the expected gain in money (`expected_gain_pct` × `amount` / 100), the chart geometry.

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): the go-live bar's 2 months (SPEC F7.2),
two intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC section 6). The legend shows
sample values and says so.

Build: `python design/mockups/04-stock-strategies/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/04-stock-strategies/page.html design/mockups/04-stock-strategies shot` and
`node design/system/check_text.js design/mockups/04-stock-strategies/page.html`.
