# Track record mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1); three files. Payload per market, `data.json` key
`markets.<market>`. Top level: `page`, `spec`, `endpoint`, `read_model`, `sources`, `as_of`, `cutoff`, `built_at`,
`markets`, `_example`, `_note`, `_data_requests`. Per market: `market`, `name`, `currency`, `as_of` (Market status
`market`, `name`, `currency`, `as_of`), `cutoff` (the catalogue files' shared `as_of`), `built_at` (Market status
`freshness.built_at`), `horizons`, `default_horizon`, then the keys below. `build.py` copies only the listed fields of
every record (`pick`), except `status`, which is the market's record whole; nested objects listed with `{...}` are
copied with the keys named, and the Track record's nested blocks are copied whole as the read model gives them.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole (the shell's chips and footer) |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons (carried for the shared shell; this page's band is the read model's own skill label) |
| `track` | Track record | `market`, `as_of`, `skill.{state, label, why, rule, review.{id, computed_at}}`, `calls[].{basis, key, label, all, by_horizon}` where `all` and each `by_horizon.<key>` block hold `n`, `hits`, `share`, `wilson_lo`, `wilson_hi`, `always_up`, `edge`, `mean_confidence`, `scores.{n, brier, log_loss, brier_skill}`, `reliability[].{bin, lo, hi, n, mean_conf, hit_rate, wilson_lo, wilson_hi}` and the `by_horizon` blocks also `h`, `horizon_label`, `name`; `ranges[]` (empty in the example: no range scored yet; the page expects `name` or `key`, `n`, `hit50.{share, wilson_lo, wilson_hi}`, `hit80.{the same}` once a row exists); `replay` (`null` in the example); `min_sample`; `backtest.{computed_at, verdict, json, data.{panel_rows, first_bar, first_panel_date, last_panel_date, tickers, round_trip_cost_pct_at_100}, scores[].{key, n, dates, brier, brier_base_rate, brier_skill, auc, auc95, skill}, strategy[].{key, threshold, positions, baseline, dates, mean_pct, ci95_pct, verdict}, reliability}`; `example_parts` | the market's record (`as_of` at or before `cutoff`); the page shows the first `calls[]` basis until another is chosen |

Shown but computed by the page (presentation only): the "not enough history yet" gate (`n` below `min_sample`), the
interval bars (hit rate with its Wilson interval and the always-up tick; AUC with its 95% interval on a 0.40-0.60
axis; the mean per entry date of the paper long's return over the window, with its 95% interval around zero), the
calibration chart (each band's `mean_conf` against its `hit_rate` with the Wilson interval, the diagonal, empty bands
as hollow marks on the axis), the grouping of the back-test's strategy
rows by `key`, the words for a back-test key (`1d close_to_close` = "1 session · close→close"), the baseline names
(`always_up` = "Always up", `momentum_5d`, `rsi_mean_reversion`, `benchmark_long_per_date`, `–` = "(no baseline)"),
and the verdict badge colour (a verdict that beats is green, one that loses red, anything else neutral; the example
holds only "not distinguishable", "fewer than 20 dates" and "no positions").

Honesty marks: `example_parts` lists the blocks computed from example calls (the catalogue's `calls` block: no call is
scored in the stored data yet), shown as a note on the calls card. The weekly series of hit rate and Brier (accuracy
over time) is not in the read model; `_data_requests` records it (a request to the read model's owner, B4) and the
card shows an empty state.

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): the go-live bar's 2 months and about 300
trades (SPEC F7.2), two intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC section 6), the
back-test's 15 years (F2.3), the luck test's 95% interval (lab/luck.py), the 60-word reason limit. This page uses
none directly: its thresholds (`min_sample`, the skill rule) come from the read model.

Build: `python design/mockups/08-track-record/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/08-track-record/page.html design/mockups/08-track-record shot` and `node design/system/check_text.js
design/mockups/08-track-record/page.html`.
