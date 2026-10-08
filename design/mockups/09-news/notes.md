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
| `news` | News item | `id`, `market`, `tickers`, `primary_tickers`, `title`, `source`, `source_domain`, `url`, `published_at`, `first_seen_at`, `status`, `status_as_of`, `independent_origins`, `primary_ids`, `cluster_id`, `scope`, `category`, `feed`, `summary`, `summary_source`, `market_moving`, `origin`, `enrichment.{event_type, materiality, sentiment, relevance, novelty, urgency, priced_in, analyzed_at}` and `enrichment.geopolitical` (on the stored items; null for the six invented ones, which predate the field) | the market's items with `first_seen_at` after `window.from` and at or before the cut-off (no look-ahead; nothing older than 3 days), newest first, at most 50 (29 per market in the example: 28 real stored items of W1's data request 8 plus one invented one; the older invented items are hidden by the window: 1 in India, 2 in the US, counted in `window.older_hidden`; the US invented item first seen 2026-10-07T12:28:07Z, after the cut-off, is excluded) |
| `calendar` | Calendar event | `market`, `date`, `type`, `name`, `ticker`, `timing`, `reaction_sessions`, `major`, `widens`, `provisional`, `release`, `source`, `event_id` | the market's events from the session being predicted to 7 days after it, by date, major first |
| `companies` | Company | `market`, `ticker`, `name`, `sector`, `state`, `open_trades` | the market's companies, by ticker (the rail's "By company" and the feed's company filter); the catalogue holds four companies per market, so a story tagged with another ticker (US BAC, GOOGL; India ICICIBANK, LT ...) is in the feed but not in the rail |

Shown but computed by the page (presentation only): the market movers (the band: a story qualifies when the engine's
`market_moving` flag is set, or it is market-wide, a results story or scored high materiality; ranked flagged first,
then market-wide, results, materiality, newest; the same headline stored twice shows once; at most `NEWS_MOVERS_MAX`),
the filters (last 24 h = first seen in the `NEWS_RECENT_HOURS` before the cut-off; market-wide = `scope` market; market moving =
the flag; can carry a call = confirmed or corroborated; one company), the kind word (a market-wide story's `category`
when it is not `company` or `general`, else the event type in words), the "not verified per company" badge for the
empty status of a market-wide story, the day groups (the
local date of `first_seen_at`; the time shown on a row and in the band is the outlet's `published_at`, with the
stored time in the tooltip, the owner's decision of 2026-10-08), the pagination (`NEWS_PAGE_SIZE` a page), "n h/days before the cut-off" (from
`published_at` against the cut-off, never the viewer's clock), the per-company counts and the sentiment mix (positive
above `SENTIMENT_FLAT_BAND`, negative below its negative), and a note under the filters when more than half of the
stories have no summary line. The page never shows the stored text: the headline links to the outlet's article (`url`) and the `summary` is the
catalogue's one-or-two-line summary (`summary_source` article or analyst; empty for most US items, whose analyst
summaries are templated).

Spec constants in the shared shell (`design/mockups/_shared/shell.js`): `NEWS_MOVERS_MAX` = 10, `NEWS_PAGE_SIZE` = 10
and `NEWS_RECENT_HOURS` = 24 (the owner's rules of 2026-10-08), `SENTIMENT_FLAT_BAND` = 0.05 (the sentiment words,
shared with the shell's arrow); the 3-day window and the 50-item cap are the build's (`window`). The go-live,
intraday, luck and assistant constants are not used on this page.

Data request 8 (`_data_requests` in data.json), sent to W1 and answered on 2026-10-08: market-wide items, a summary
line per item, volume and an engine-side `market_moving` flag, as 56 real stored items (28 per market). Not in the
stored data and not invented: a region, confirmed or corroborated statuses on the stored items (only four of the six invented
items carry them, so the "can carry a call" filter finds one India story and none in the US; the filter's empty state says so), clusters with more
than one origin, and summaries for most US items.

Build: `python design/mockups/09-news/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/09-news/page.html design/mockups/09-news shot` and `node design/system/check_text.js
design/mockups/09-news/page.html`.
