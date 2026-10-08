# Rule vs AI mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1). Payload per market, `data.json` key `markets.<market>`. Top
level: `page`, `spec`, `endpoint`, `read_model`, `sources`, `as_of`, `cutoff`, `built_at`, `markets`,
`_data_requests`, `_example`, `_note`. Per market: `market`, `name`, `currency`, `as_of` (Market status `market`,
`name`, `currency`, `as_of`), `cutoff` (the catalogue files' shared `as_of`), `built_at` (Market status
`freshness.built_at`), `horizons`, `default_horizon`, `session_date` (Market status `session.session_date`), `review_due` (computed from the cut-off date
alone: the next Saturday and its iso week, F6.2; no record after the cut-off is read), then the keys below. `build.py` copies only the listed fields of every
record (`pick`), except `status`, which is the market's record whole; nested objects listed with `{...}` are copied
with the keys named.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons, for the paper band |
| `strategies` | Strategy | `id`, `family`, `name`, `description`, `compared_to`, `differs_in`, `threshold`, `horizons`, `live`, `settled_trades` | all 15, keyed by id |
| `companies` | Company | `market`, `ticker`, `name`, `sector`, `state`, `amount`, `amount_overridden`, `currency` | the market's companies (names and links) |
| `rows` | Scoreboard row | `scope`, `market`, `view`, `basis`, `strategy_id`, `family`, `pick_rule`, `ticker`, `regime`, `horizon_days`, `trades`, `net_pnl`, `mean_return_pct`, `win_rate`, `target_reached_rate`, `median_reached_session`, `avg_target_error_pct`, `range_hit_rate`, `worst_losing_streak`, `max_drawdown`, `sample_badge`, `first_entry`, `last_exit`, `as_of`, `luck_test.{method, n, m, low_pct, high_pct, excludes_zero, corrected_low_pct, corrected_high_pct, corrected}`, `your_cost.{net_pnl, mean_return_pct, win_rate, worst_losing_streak, max_drawdown, luck_test.{the same}}` | the market's rows of the head-to-head view: scopes `strategy` (all horizons and per horizon), `pick_rule`, `strategy_regime` |
| `trades` | Paper trade (settled) | `trade_id`, `prediction_id`, `strategy_id`, `family`, `view`, `pick_rule`, `ticker`, `horizon_days`, `made_at`, `entry_date`, `exit_date`, `exit_date_actual`, `status`, `amount`, `currency`, `entry_price`, `exit_price`, `net_pnl`, `return_pct`, `prob_up`, `target_price`, `target_error_pct`, `target_reached`, `range_hit`, `move_pct`, `market_pct`, `sector_pct`, `news_pct`, `company_pct`, `reason_code`, `reason_codes`, `regime`, `settled_at` | the market's settled head-to-head trades with `settled_at` at or before `cutoff` (the matches, the per-company sums, the cumulative lines) |
| `picks` | Head-to-head pick | `id`, `market`, `ticker`, `made_at`, `as_of_date`, `session_date`, `family`, `pick_rule`, `status`, `strategy_id`, `strongest_basis`, `horizon_days`, `prediction_id`, `prob_up`, `move_pct`, `loss_pct`, `costs_pct`, `expected_gain_pct`, `candidates[].{horizon_days, prediction_id, prob_up, move_pct, loss_pct, costs_pct, expected_gain_pct, gain_per_session_pct, expected_move_pct, your_cost_pct, expected_gain_your_pct, cost_viable, eligible}`, `amount`, `currency` | every pick of the market with `made_at` at or before `cutoff` (today's for the picks card; earlier sessions' to tell an open pick from a missing candidate in the matches) |
| `your_costs` | Cost view | `trade_id`, `record_id`, `net_pnl_market`, `return_pct_market`, `net_pnl_your`, `return_pct_your`, `market_costs`, `your_costs`, `your_cost_pct`, `computed_at` | the settlement rows of the settled head-to-head trades, `computed_at` at or before `cutoff` (the your-cost figures of the matches and per-company sums) |
| `reasons` | AI reason | `id`, `trade_id`, `market`, `ticker`, `strategy_id`, `session_date`, `kind`, `rank`, `text`, `cited_ids`, `reason_codes`, `created_at` | the market's notes of kind `head_to_head`, `created_at` at or before `cutoff`, newest first |
| `eod` | End-of-day analysis | `id`, `market`, `session_date`, `settled_trades`, `results.{rule, baseline, ai}.{trades, wins, net_pnl}`, `results.{best_expected_gain, highest_probability}.{trades, net_pnl}`, `summary`, `cited_ids`, `reason_ids`, `created_at` | the market's analyses, `created_at` at or before `cutoff`, newest first (the page shows the newest) |
| `reviews` | Research review | `id`, `market`, `iso_week`, `period_start`, `period_end`, `leaders[].{scope, strategy_id, net_pnl, trades}`, `findings[].{text, cited_ids}`, `proposals[].{proposal_id, kind, file, diff, rationale, cited_ids, status}`, `report_path`, `written_at` | the market's reviews with `written_at` at or before `cutoff`, newest first (none in the example: both stored reviews are written on 10 Oct, after the cut-off; a review before it is requested from W1) |

Shown but computed by the page (presentation only): who leads (the difference of the two family rows' profit), the
matches (head-to-head trades grouped by entry date, company and pick rule, the winner by net profit), the per-company
sums of the head-to-head trades, the cumulative sums by exit date, the picks' "clears / viable" counts, the luck bar
geometry.

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): the go-live bar's 2 months (SPEC F7.2),
two intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC section 6). The legend shows
sample values and says so.

Data requests to W1 (`_data_requests` in data.json), both sent and answered on 2026-10-08: head-to-head scoreboard
rows per company (answered with the heatmap cells of `heatmap_cell.json`, not read by this page yet); a research
review written before the cut-off (answered: the 2026-W40 reviews, written 3 Oct, are shown; the W41 ones of
10 Oct are after the cut-off and never read).

Build: `python design/mockups/06-rule-vs-ai/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/06-rule-vs-ai/page.html design/mockups/06-rule-vs-ai shot` and `node design/system/check_text.js
design/mockups/06-rule-vs-ai/page.html`.
