# Company mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1). One payload per (market, ticker): `data.json` key
`markets.<market>.pages.<ticker>` holds every company the catalogue has bars for (India: RELIANCE, HDFCBANK, MARUTI;
US: NVDA, AAPL, JPM); the market-level keys are shared by the market's companies. Top level: `page`, `spec`,
`endpoint`, `read_model`, `sources`, `as_of`, `cutoff`, `built_at`, `markets`, `_pages`, `_example`, `_note`.
Per market: `market`, `name`, `currency`, `as_of` (Market status `market`, `name`, `currency`, `as_of`), `cutoff` (the
catalogue files' shared `as_of`), `built_at` (Market status `freshness.built_at`), `reference_strategy` (the registry's
reference rule strategy id, `rule.model_news.v1`), `default_ticker` (the example opened without a hash), `horizons`,
`default_horizon`, then the keys below; each `pages.<ticker>` payload also carries `ticker`. `build.py` copies only the
listed fields of every record (`pick`), except `status`, which is the market's record whole; nested objects listed with
`{...}` are copied whole with the keys named.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (the two blocks ride along in the copied record; this page does not show them) | the market's record, whole |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons |
| `strategies` | Strategy | `id`, `family`, `name`, `threshold`, `horizons`, `live`, `settled_trades` | all 15, keyed by id |
| `companies` | Company | `market`, `ticker`, `name`, `exchange`, `sector`, `state`, `state_since`, `added_at`, `amount`, `amount_overridden`, `currency`, `yahoo`, `nse_symbol`, `cik`, `last_close`, `last_close_date`, `change_pct`, `agreement_n1.{buy, of}`, `open_trades` | the market's companies (names for the example picker and links) |
| `pages.<ticker>.company` | Company | the same fields | the page's company |
| `pages.<ticker>.lifecycle` | Lifecycle event | `id`, `event`, `ticker`, `market`, `effective_from`, `recorded_at`, `amount`, `reason`, `requested_by`, `channel`, `supersedes` | the company's events with `recorded_at` at or before `cutoff`, oldest first |
| `pages.<ticker>.agreement["1".."5"]` | Agreement | `market`, `as_of_date`, `session_date`, `rank`, `ticker`, `name`, `horizon_days`, `buy`, `of`, `by_family.{rule,baseline,ai}.{buy,of}`, `avg_prob_up`, `label`, `paper` | the company's row per horizon |
| `pages.<ticker>.head_to_head` | Head-to-head pick | `id`, `market`, `ticker`, `made_at`, `as_of_date`, `session_date`, `family`, `pick_rule`, `status`, `strategy_id`, `strongest_basis`, `ranking[].{strategy_id, rank, basis, settled_trades, net_pnl}`, `horizon_days`, `prediction_id`, `base_close`, `prob_up`, `move_pct`, `loss_pct`, `costs_pct`, `expected_gain_pct`, `candidates[].{horizon_days, prediction_id, prob_up, move_pct, loss_pct, costs_pct, expected_gain_pct, gain_per_session_pct, expected_move_pct, your_cost_pct, expected_gain_your_pct, cost_viable, eligible}`, `amount`, `currency` | the company's picks for the session being predicted, `made_at` at or before `cutoff` (rows with `status` other than `picked` are the "no candidate" rows) |
| `pages.<ticker>.predictions` | Prediction | `id`, `strategy_id`, `family`, `ticker`, `made_at`, `as_of_date`, `session_date`, `exit_date`, `horizon_days`, `direction`, `prob_up`, `qualifies`, `base_close`, `target_price`, `lo50`, `hi50`, `lo80`, `hi80`, `range_widen`, `regime`, `quality` | the company's predictions for the as-of date, `made_at` at or before `cutoff` (the reference strategy's rows draw the fan; every strategy's target draws the spread) |
| `pages.<ticker>.open_trades` | Open trade | `trade_id`, `view`, `prediction_id`, `strategy_id`, `family`, `market`, `ticker`, `horizon_days`, `entry_date`, `exit_date`, `entry_price`, `quantity`, `amount`, `currency`, `target_price`, `lo80`, `lo50`, `hi50`, `hi80`, `last_price`, `last_price_date`, `unrealised_pnl`, `unrealised_pct`, `to_target_pct`, `paper` | the company's open trades |
| `pages.<ticker>.trade_checks` | Intraday trade check | `id`, `check_id`, `check_row_id`, `check_at`, `session_date`, `market`, `ticker`, `trade_id`, `prediction_id`, `strategy_id`, `view`, `horizon_days`, `entry_date`, `exit_date`, `session_number`, `entry_price`, `last_price`, `ret_since_entry_pct`, `target_price`, `to_target_pct`, `lo80`, `lo50`, `hi50`, `hi80`, `band`, `target_z`, `flags`, `flagged`, `quality`, `target_reached`, `target_reached_session`, `high_since_entry_pct`, `low_since_entry_pct`, `sessions_left`, `last_time` | the latest check with `check_at` at or before `cutoff` |
| `pages.<ticker>.settled` | Paper trade (settled) | `id`, `trade_id`, `prediction_id`, `strategy_id`, `family`, `view`, `pick_rule`, `market`, `ticker`, `horizon_days`, `made_at`, `entry_date`, `exit_date`, `exit_date_actual`, `status`, `flags`, `amount`, `currency`, `entry_price`, `exit_price`, `quantity`, `gross_pnl`, `costs`, `net_pnl`, `return_pct`, `prob_up`, `target_price`, `lo80`, `hi80`, `range_hit`, `target_reached`, `target_reached_session`, `max_favourable_pct`, `max_adverse_pct`, `move_pct`, `market_pct`, `sector_pct`, `news_pct`, `company_pct`, `reason_code`, `reason_codes`, `news_ids`, `reason_detail.{benchmark, benchmark_pct, beta, sector_source, news_statuses, note}` (`note` on skipped rows only), `regime`, `settled_at` | the company's settlements with `settled_at` at or before `cutoff`, newest exit first (skipped rows are counted, not listed) |
| `pages.<ticker>.reasons` | AI reason | `id`, `trade_id`, `market`, `ticker`, `strategy_id`, `session_date`, `kind`, `rank`, `text`, `cited_ids`, `reason_codes`, `created_at` | the company's notes with `created_at` at or before `cutoff` |
| `pages.<ticker>.news` | News item | `id`, `market`, `tickers`, `primary_tickers`, `title`, `source`, `source_domain`, `url`, `published_at`, `first_seen_at`, `enrichment.{event_type, materiality, sentiment, relevance, novelty, urgency, priced_in, analyzed_at}`, `status`, `status_as_of`, `cluster_id`, `independent_origins`, `primary_ids`, `headline_history[].{title, seen_at}` | stories tagged with the company, `first_seen_at` at or before `cutoff`, newest first |
| `pages.<ticker>.results` | Results digest | `id`, `release_kind`, `ticker`, `release_at`, `release_date`, `release_timing`, `period_end`, `fiscal_label`, `basis`, `currency`, `status`, `numbers_status`, `numbers_as_of`, `numbers.{revenue, net_profit, eps_diluted, net_margin_pct, revenue_yoy_pct, net_profit_yoy_pct, eps_yoy_pct, revenue_qoq_pct, profit_before_tax, pbt_margin_pct, operating_profit, prev_year_period_end, derived}` (which keys a digest has depends on the filing), `consensus.{note, status, eps_estimate, eps_reported, surprise_pct, surprise_basis}`, `reaction.{from, to, stock_pct, benchmark_pct, excess_pct}`, `bullets[].{topic, text, quote, source_id, source_kind}`, `sources[].{id, kind, doc, url, available_at}`, `created_at` | the company's digests with `created_at` at or before `cutoff`, newest release first (the page shows the newest) |
| `pages.<ticker>.events` | Calendar event | `market`, `date`, `type`, `name`, `ticker`, `timing`, `reaction_sessions`, `major`, `widens`, `provisional`, `release`, `source`, `event_id` | from the session being predicted on: the company's own events, the market's major events and closed days |
| `pages.<ticker>.bars` | Bar | `date`, `open`, `high`, `low`, `close`, `volume`, `adjusted` | the company's stored sessions up to the as-of date (60 in the example) |
| `pages.<ticker>.on_company` | Scoreboard row | `scope`, `market`, `view`, `strategy_id`, `family`, `ticker`, `horizon_days`, `trades`, `net_pnl`, `win_rate`, `sample_badge` | `scope` = `strategy_company`, accuracy view, all horizons (carried for the "By strategy" link's context; not drawn) |
| `horizons`, `default_horizon` | (setting) | `config/strategies.yaml` horizons 1-5; N+1 opens (decision 39) | |

Shown but computed by the page (presentation only): the open-trade sums and flagged counts; the settled summary
(won, net, reached, in range); the "why" bar geometry (the four parts of the automatic reason, scaled to the largest
row); the chart geometry (price and volume scales, the fan from the last close to each horizon's exit, the spread of
the strategies' targets at the selected horizon, trade entry and exit marks grouped per date); the plain-words
sentence (counts of the rows above); the pending requests of the confirm dialogs (mockup state, never sent).

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): the go-live bar's 2 months (SPEC F7.2), two
intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC section 6). The legend shows sample
values and says so.

Build: `python design/mockups/03-company/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/03-company/page.html design/mockups/03-company shot` and `node design/system/check_text.js
design/mockups/03-company/page.html` (the default company of each market; the other four companies were scanned from
copies of the page with their ticker as the default).
