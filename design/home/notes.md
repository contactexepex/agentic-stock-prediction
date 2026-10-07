# Notes: queries behind home.html

Built 2026-10-07 (UTC); repo read only. `python design/home/build.py --out <dir>` (about 20 s: it runs the
watchlist builder for both markets, reusing the rule replay JSON under `work/design/replayroot-<market>/`).

- Rows, header tiles, sectors: `design/watchlist/build.py` `build(market)` (see its notes.md).
- Movers: the watchlist rows sorted by day move; cause per mover from the benchmark and sector-index day moves
  already in those rows and a query of `news` unnested by ticker joined to `enriched_latest`, filtered to the
  as-of date in the market's local time (`timezone(<tz>, published_at)`), counting high-materiality items.
- Events: `core.calendar.market_events(cfg, today, today+56)` plus `events` of type earnings or ex_dividend for
  watchlist tickers in the same window (reaction session via `next_session`, the day after for `after_close`);
  `this_week` marks the first seven days, the rest sits behind the "Next 8 weeks" button.
- News card (`news_card` in build.py), window = the 24 hours before `max(published_at)` of `news`:
  market-wide = `news` with no tickers joined to `enriched_latest`, event_type macro, materiality medium or
  high, grouped in Python by the analyst's `summary` (or the title when none): headline and url of the newest
  item, distinct sources, item count, mean sentiment, max materiality; ranked by materiality, outlets, items;
  the first six shown. Company stories = `news_clusters_latest` with `last_reported_at` in the window, each
  joined to its newest `news_verified` cluster row (`qualify row_number() over (partition by cluster_id order
  by as_of desc) = 1`), lead headline = the cluster's highest-materiality, newest item; `can_carry` = status in
  (confirmed_primary, corroborated); the rest `set_aside` with counts per status.
- Status: `model_scores_latest` (count, max computed_at), `ranges` where as_of_date = as-of (per horizon),
  `agent_reasoning` for the as-of date, `news` since the as-of date (UTC), `news_verified` distinct clusters at
  the latest pass, `ohlc` bars on the as-of date for the watchlist, `lessons` count; run before/after the open
  from `session_open_utc(cfg, today)` where today = the session after the as-of date.
- Track record: `replay-<end>.json` overall cover80/cover50 per horizon; `reviews` latest model_skill.

Numbers on 2026-10-07: India run 05:11 UTC after the 03:45 open (1-day ranges 0 of 20, 5-day 20 of 20);
US run 12:33 UTC before the 13:30 open (ranges 20 · 20). 0 YES, 0 Paper candidates, 0 live calls scored.
News card: India window 6 Oct 04:59 to 7 Oct 04:59 UTC, 388 macro and 152 company headlines, groups 4, can
carry 1 (LT confirmed_primary), set aside single_source 11, rumour 4, unverified 20, promotional 3; US window
6 Oct 12:26 to 7 Oct 12:26 UTC, 455 macro and 644 company headlines, 136 groups, can carry 1 (TSLA
confirmed_primary), set aside single_source 8, unverified 84, promotional 115, rumour 3.
