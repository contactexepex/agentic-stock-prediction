# News mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1); five files. Payload per market, `data.json` key `markets.<market>`.
Top level: `page`, `spec`, `endpoint`, `read_model`, `sources`, `as_of`, `cutoff`, `built_at`, `markets`, `_example`,
`_note`, `_data_requests`. Per market: `market`, `name`, `currency`, `as_of` (Market status `market`, `name`,
`currency`, `as_of`), `cutoff` (the catalogue files' shared `as_of`), `built_at` (Market status `freshness.built_at`),
`horizons`, `default_horizon`, `window` (the build's rule: `days` 3, `from` = cut-off minus 3 days, `to` = the cut-off,
`max_items` 50, `stored_in_window`, `older_hidden` = stored items first seen before the window), `calendar_days` (7),
then the keys below. `build.py` copies only the listed fields of every record (`pick`), except `status`, which is the
market's record whole; nested objects listed with `{...}` are copied with the keys named.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole (the shell's chips and footer; `session.session_date` starts the calendar) |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons (carried for the shared shell; this page shows no signal band) |
| `news` | News item | `id`, `market`, `tickers`, `primary_tickers`, `title`, `source`, `source_domain`, `url`, `published_at`, `first_seen_at`, `status`, `status_as_of`, `independent_origins`, `primary_ids`, `cluster_id`, `enrichment.{event_type, materiality, sentiment, relevance, novelty, urgency, priced_in, analyzed_at}` | the market's items with `first_seen_at` after `window.from` and at or before the cut-off (no look-ahead; nothing older than 3 days), newest first, at most 50 (the example holds 1 per market in the window; W1's data request 8 adds market-wide items, summaries and volume) |
| `calendar` | Calendar event | `market`, `date`, `type`, `name`, `ticker`, `timing`, `reaction_sessions`, `major`, `widens`, `provisional`, `release`, `source`, `event_id` | the market's events from the session being predicted to 7 days after it, by date, major first |
| `companies` | Company | `market`, `ticker`, `name`, `sector`, `state`, `open_trades` | the market's companies, by ticker (the rail's "By company" and the feed's company filter) |

Shown but computed by the page (presentation only): the market movers (the band's ranking: a story counts when it is
market-wide (no ticker), a results story or scored high materiality; ranked market-wide first, results next, then
materiality, then newest; at most `NEWS_MOVERS_MAX`), the filters (last 24 h = first seen in the 24 hours before the
cut-off; market-wide = no ticker; can carry a call = confirmed or corroborated; one company), the day groups (the
local date of `first_seen_at`), the pagination (`NEWS_PAGE_SIZE` a page), "n h/days before the cut-off" (from
`first_seen_at` against the cut-off, never the viewer's clock), the per-company counts and the sentiment mix (positive
above +0.05, negative below −0.05). A story's scope is derived: no ticker = market-wide. The page never shows the
stored text; a headline links to the outlet's article (`url`).

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): `NEWS_MOVERS_MAX` = 10 and `NEWS_PAGE_SIZE` =
10 (the owner's rules of 2026-10-08); the 3-day window and the 50-item cap are the build's (`window`). The go-live,
intraday, luck and assistant constants are not used on this page.

Data request (`_data_requests` in data.json, sent to W1 as request 8 on 2026-10-08): market-wide items with a scope
and region, a one-or-two-line `summary` per item, about 30 items per market in the window with at least 12 in the
last 24 hours and every status, and if cheap an engine-side `market_moving` flag. Until then the band's ranking is the
page's and no summary line is shown.

Build: `python design/mockups/09-news/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/09-news/page.html design/mockups/09-news shot` and `node design/system/check_text.js
design/mockups/09-news/page.html`.
