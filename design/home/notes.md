# Notes: queries behind home.html

Built 2026-10-07 (UTC); repo read only. `python design/home/build.py --out <dir>` (about 20 s: it runs the
watchlist builder for both markets, reusing the rule replay JSON under `work/design/replayroot-<market>/`).

- Rows, header tiles, sectors: `design/watchlist/build.py` `build(market)` (see its notes.md).
- Movers: the watchlist rows sorted by day move; cause per mover from the benchmark and sector-index day moves
  already in those rows and a query of `news` unnested by ticker joined to `enriched_latest`, filtered to the
  as-of date in the market's local time (`timezone(<tz>, published_at)`), counting high-materiality items.
- Events: `core.calendar.market_events(cfg, today, today+7)` plus `events` type earnings for watchlist tickers in
  the same window (reaction session via `next_session`, the day after for `after_close`).
- Status: `model_scores_latest` (count, max computed_at), `ranges` where as_of_date = as-of (per horizon),
  `agent_reasoning` for the as-of date, `news` since the as-of date (UTC), `news_verified` distinct clusters at
  the latest pass, `ohlc` bars on the as-of date for the watchlist, `lessons` count; run before/after the open
  from `session_open_utc(cfg, today)` where today = the session after the as-of date.
- Track record: `replay-<end>.json` overall cover80/cover50 per horizon; `reviews` latest model_skill.

Numbers on 2026-10-07: India run 05:11 UTC after the 03:45 open (1-day ranges 0 of 20, 5-day 20 of 20);
US run 12:33 UTC before the 13:30 open (ranges 20 · 20). 0 YES, 0 Paper candidates, 0 live calls scored.
