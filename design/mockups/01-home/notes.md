# Home mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1). Payload per market, `data.json` key `markets.<market>`.
Top level: `as_of`, `cutoff`, `built_at`, `endpoint`, `read_model`, `sources`, `_example`, `_note`.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (the two blocks W1 added on 2026-10-08 ride along in the copied record; this page does not show them) | the market's record, whole |
| `companies` | Company | `market`, `ticker`, `name`, `exchange`, `sector`, `state`, `amount`, `amount_overridden`, `currency`, `last_close`, `last_close_date`, `change_pct`, `agreement_n1`, `open_trades` | the market's companies; inactive ones are kept in the payload (never shown on Home, decision 13) |
| `agreement["1".."5"]` | Agreement | `market`, `as_of_date`, `session_date`, `rank`, `ticker`, `name`, `horizon_days`, `buy`, `of`, `by_family.{rule,baseline,ai}.{buy,of}`, `avg_prob_up`, `label`, `paper` | active companies, per horizon, top 5 by `rank` |
| `head_to_head` | Head-to-head pick | `id`, `market`, `ticker`, `made_at`, `as_of_date`, `session_date`, `family`, `pick_rule`, `status`, `strategy_id`, `strongest_basis`, `ranking[].{strategy_id, rank, basis, settled_trades, net_pnl}`, `horizon_days`, `prediction_id`, `base_close`, `prob_up`, `move_pct`, `loss_pct`, `costs_pct`, `expected_gain_pct`, `candidates[].{horizon_days, prediction_id, prob_up, move_pct, loss_pct, costs_pct, expected_gain_pct, gain_per_session_pct, expected_move_pct, your_cost_pct, expected_gain_your_pct, cost_viable, eligible}`, `amount`, `currency`, `method_version` | picks whose `session_date` is the session being predicted |
| `open_trades` | Open trade | `trade_id`, `view`, `prediction_id`, `strategy_id`, `family`, `market`, `ticker`, `horizon_days`, `entry_date`, `exit_date`, `entry_price`, `quantity`, `amount`, `currency`, `target_price`, `lo80`, `lo50`, `hi50`, `hi80`, `last_price`, `last_price_date`, `unrealised_pnl`, `unrealised_pct`, `to_target_pct`, `paper` | the market's open trades |
| `trade_checks` | Intraday trade check | `id`, `check_id`, `check_row_id`, `check_at`, `session_date`, `market`, `ticker`, `trade_id`, `prediction_id`, `strategy_id`, `view`, `horizon_days`, `entry_date`, `exit_date`, `session_number`, `entry_price`, `last_price`, `ret_since_entry_pct`, `target_price`, `to_target_pct`, `lo80`, `lo50`, `hi50`, `hi80`, `band`, `target_z`, `flags`, `flagged`, `method_version`, `computed_at` | the latest check with `check_at` at or before `cutoff` (no look-ahead) |
| `eod` | End-of-day analysis | `id`, `market`, `session_date`, `settled_trades`, `results.{rule,baseline,ai}.{trades,wins,net_pnl}`, `results.{best_expected_gain,highest_probability}.{trades,net_pnl}`, `summary`, `cited_ids`, `reason_ids`, `prompt_version`, `created_at` | the market's newest analysis |
| `to_date` | Scoreboard row | `scope`, `market`, `view`, `family`, `pick_rule`, `horizon_days`, `trades`, `net_pnl`, `mean_return_pct`, `win_rate`, `sample_badge`, `basis`, `as_of` (money in the market's `currency` of the status) | rows with `scope` = `pick_rule`, `horizon_days` = `all` (head-to-head view) |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons |
| `strategies` | Strategy | `id`, `family`, `name`, `threshold`, `horizons`, `live`, `settled_trades` | all 15, keyed by id (names for picks, open trades and alerts) |
| `news` | News item | `id`, `market`, `tickers`, `primary_tickers`, `title`, `source`, `source_domain`, `url`, `published_at`, `first_seen_at`, `enrichment.{event_type, materiality, sentiment, relevance, novelty, urgency, priced_in, analyzed_at}`, `status`, `status_as_of`, `cluster_id`, `independent_origins`, `primary_ids`, `headline_history[].{seen_at, title}`, `headline_history_status`, and since W1's data request 8 `scope`, `category`, `feed`, `summary`, `summary_source`, `market_moving`, `origin`, `enrichment.geopolitical` (stored items; absent on the six invented ones) | the market's items first seen in the 3 days before the cut-off and at or before it (the News page's window), newest first; the card shows the top 5 market movers (the News page's ranking) and links to the News page |
| `settled_trades` | Paper trade (settled) | `trade_id`, `view`, `pick_rule`, `strategy_id`, `family`, `ticker`, `horizon_days`, `entry_date`, `exit_date`, `exit_date_actual`, `status`, `amount`, `currency`, `net_pnl`, `return_pct`, `reason_code`, `settled_at` | the market's settled trades with `settled_at` at or before `cutoff` (the cumulative profit chart; `rm.trades` keeps the last sessions' settled trades) |
| `horizons`, `default_horizon` | (setting) | `config/strategies.yaml` horizons 1-5; N+1 opens (decision 39) | |

Shown but computed by the page (presentation only): the KPI cards' counts and sums (trades, flagged checks, runs ok,
unrealised total), the unrealised total per company (sum of `unrealised_pnl`), the cumulative profit per family and
settlement day (sums of `net_pnl`), the expected gain in money (`expected_gain_pct` × `amount` / 100), local times
from the UTC fields and the market's `session.local_time` offset, the range bar's and chart's geometry,

Spec constants in the template (not data, named once each with their source): the go-live bar's 2 months of forward
paper trading (SPEC F7.2) and the two intraday checks per session (SPEC section 7, used for "n of N ok" and the two
intraday slots of the runs timeline). The legend shows sample values (+1.2% / −1.2%) and says so.
the expected gain in money (`expected_gain_pct` x `amount` / 100), local times from the UTC fields and the
market's `session.local_time` offset, the "clears costs / below costs" reading (`expected_gain_pct` > 0, SPEC F9),
the leader outline among the family tiles (highest `net_pnl` with trades).

Not in the catalogue and therefore not shown (no new data request made for this page): a family-level scoreboard
row (rule vs AI to date as one number per family), and the intraday alerts feed's "material news on a company with
an open trade" (the catalogue's alerts are the flagged trade checks).

Build: `python design/mockups/01-home/build.py` (deterministic; `cutoff` = the catalogue files' `as_of` clock,
`built_at` = `market_status.freshness.built_at`). Check: `node design/system/check_page.js
design/mockups/01-home/page.html design/mockups/01-home shot`.
