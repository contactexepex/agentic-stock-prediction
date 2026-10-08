# Companies mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1); seven files (`open_trade` is not read: the open-trade counts are
the company record's). Payload per market, `data.json` key `markets.<market>`. Top
level: `page`, `spec`, `endpoint`, `read_model`, `sources`, `as_of`, `cutoff`, `built_at`, `markets`, `_example`,
`_note`. Per market: `market`, `name`, `currency`, `as_of` (Market status `market`, `name`, `currency`, `as_of`),
`cutoff` (the catalogue files' shared `as_of`), `built_at` (Market status `freshness.built_at`), `horizons`,
`default_horizon`, `deleted_count` (how many delete tombstones were excluded on read), then the keys below.
`build.py` copies only the listed fields of every record (`pick`), except `status`, which is the market's record
whole; nested objects listed with `{...}` are copied with the keys named.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons (carried for the shared shell; this page shows no signal band) |
| `default_amount` | Owner's paper portfolio | `default_amounts.<market>` | the market's default money per paper trade (decision 26) |
| `companies` | Company | `market`, `ticker`, `name`, `exchange`, `sector`, `state`, `state_since`, `added_at`, `amount`, `amount_overridden`, `currency`, `yahoo`, `nse_symbol`, `cik`, `last_close`, `last_close_date`, `change_pct`, `agreement_n1.{buy, of}`, `open_trades` | the market's companies, active first (a deleted company is not in the catalogue's list and would never be shown, decision 12) |
| `lifecycle` | Lifecycle event | `id`, `event`, `ticker`, `market`, `effective_from`, `recorded_at`, `name`, `exchange`, `sector`, `amount`, `reason`, `requested_by`, `channel`, `command_id`, `idempotency_key`, `onboarding.{identifiers, backfill, collect_gate}` on seed adds and `onboarding.{identifiers, not_etf, listing, backfill_prices, backfill_news, collect_gate}` on a real add (each ok/failed/skipped), `supersedes` | the market's events with `recorded_at` at or before `cutoff`, newest first, of the companies shown (events of a deleted company are excluded, their count in `deleted_count`) |
| `commands` | Command | `id`, `market`, `received_at`, `channel`, `actor`, `agent`, `tool`, `kind`, `arguments.{market, symbol, ticker}` (which keys a command has depends on its tool), `idempotency_key`, `result`, `refusal_code`, `message`, `record_ids`, `budget_left`, `completed_at` | the market's company commands (`add_company`, `deactivate_company`, `reactivate_company`, `set_paper_amount`, `delete_company`) with `received_at` at or before `cutoff`, newest first; for a command about a company deleted later, its symbol in `arguments`, its echo in `message`, its `idempotency_key` and its `record_ids` are masked (decision 12) |
| `news_inactive` | News item | `id`, `market`, `tickers`, `primary_tickers`, `title`, `source`, `published_at`, `first_seen_at`, `status`, `enrichment.{event_type, materiality, sentiment, relevance, novelty, urgency, priced_in, analyzed_at}` | stories tagged with an inactive company and first seen since it went inactive, at or before `cutoff` (none in the example) |

Shown but computed by the page (presentation only): the counts (active, inactive, custom amounts, pending), the
open-trade counts come from the company record, the pending requests of the dialogs (mockup state, never sent).

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): the go-live bar's 2 months and about 300
trades (SPEC F7.2), two intraday checks per session (SPEC section 7), 20 settled trades to rank (SPEC section 6),
the back-test's 15 years (F2.3), the luck test's 95% interval (lab/luck.py). This page uses none directly.

Build: `python design/mockups/10-companies/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/10-companies/page.html design/mockups/10-companies shot` and `node design/system/check_text.js
design/mockups/10-companies/page.html`.
