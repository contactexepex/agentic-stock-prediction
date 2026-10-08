# Watchlist mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1). Payload per market, `data.json` key `markets.<market>`.
Top level: `as_of`, `cutoff`, `built_at`, `endpoint`, `read_model`, `sources`, `_example`, `_note`.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label` | the market's record |
| `companies` | Company | `market`, `ticker`, `name`, `exchange`, `sector`, `state`, `state_since`, `amount`, `amount_overridden`, `currency`, `last_close`, `last_close_date`, `change_pct`, `agreement_n1`, `open_trades` | the market's companies; rows for active ones, the inactive named under the table (decision 13) |
| `agreement["1".."5"]` | Agreement | `market`, `as_of_date`, `session_date`, `rank`, `ticker`, `name`, `horizon_days`, `buy`, `of`, `by_family.{rule,baseline,ai}.{buy,of}`, `avg_prob_up`, `label`, `paper` | active companies, per horizon, by rank |
| `open_trades` | Open trade | `trade_id`, `view`, `prediction_id`, `strategy_id`, `family`, `market`, `ticker`, `horizon_days`, `entry_date`, `exit_date`, `entry_price`, `quantity`, `amount`, `currency`, `target_price`, `lo80`, `lo50`, `hi50`, `hi80`, `last_price`, `last_price_date`, `unrealised_pnl`, `unrealised_pct`, `to_target_pct`, `paper` | the market's open trades (counted and summed per company by the page) |
| `trade_checks` | Intraday trade check | `id`, `check_id`, `check_row_id`, `check_at`, `session_date`, `market`, `ticker`, `trade_id`, `prediction_id`, `strategy_id`, `view`, `horizon_days`, `entry_date`, `exit_date`, `session_number`, `entry_price`, `last_price`, `ret_since_entry_pct`, `target_price`, `to_target_pct`, `lo80`, `lo50`, `hi50`, `hi80`, `band`, `target_z`, `flags`, `flagged`, `method_version`, `computed_at` | the latest check with `check_at` at or before `cutoff` |
| `ranges` | Prediction | `id`, `strategy_id`, `family`, `ticker`, `made_at`, `as_of_date`, `session_date`, `exit_date`, `horizon_days`, `direction`, `prob_up`, `qualifies`, `base_close`, `target_price`, `lo50`, `hi50`, `lo80`, `hi80`, `range_widen`, `regime`, `quality` | the reference rule strategy's (`rule.model_news.v1`) predictions for the as-of date, `made_at` at or before `cutoff` (the range column) |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` | of the reference strategy's accuracy row, all horizons |
| `strategies` | Strategy | `id`, `family`, `name`, `threshold`, `horizons`, `live`, `settled_trades` | all 15, keyed by id |
| `horizons`, `default_horizon` | (setting) | `config/strategies.yaml` horizons 1-5; N+1 opens (decision 39) | |

Shown but computed by the page (presentation only): per company the open-trade count and the unrealised sum, the
flagged-check count; the KPI counts and sums; sorting and filtering; the geometry of the bars and meters.

Spec constants in the shared shell (`design/mockups/_shared/shell.js`, named once with their source): the go-live
bar's 2 months (SPEC F7.2), two intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC
section 6). The legend shows sample values and says so.

Build: `python design/mockups/02-watchlist/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/02-watchlist/page.html design/mockups/02-watchlist shot` and `node design/system/check_text.js
design/mockups/02-watchlist/page.html`.
