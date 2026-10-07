# Notes: queries and commands behind the watchlist pages

Built 2026-10-07 (UTC); repo read only. `python design/watchlist/build.py --market india|us --out <dir>` (about
10 s; the rule replay for the window is reused from `work/design/replayroot-<market>/` or run there).

## DuckDB (run from `scripts/`, `connect(market)`)
- Prices: `ohlc`, last 21 bars per symbol (watchlist tickers, benchmark, vol index, sector indices/ETFs): day move =
  last/previous − 1, 5-day = last/close 5 bars back, 20-session = first of the 21; sparkline = the 21 closes.
- `model_scores_latest` at its latest `as_of_date` (P(up) 1d/5d, news score, computed_at = "last model run").
- `ranges_latest` at the latest as_of per ticker and horizon (the 5-day 80%/50% range and its target date).
- `features_latest` at the latest as_of per ticker (RSI, rel_sector_5d, days_to_earnings, quality).
- `agent_reasoning` at its latest as_of (decision_1d/5d); `predictions` at the latest as_of (verdict), `outcomes`
  joined to predictions (scored calls): 0 rows on 2026-10-07 for both markets.
- `quotes_latest` on its latest day (ADR cues `<T>:ADR` for India, pre-market quotes `<T>` for the US, benchmark
  live quote).
- `regime` latest by computed_at; `flows_daily` latest (India); `reviews` latest (model_skill, week).
- News: `news` unnested by ticker, last 72 hours of the archive, joined to `enriched_latest` (high materiality
  count); `news_verified` level cluster → best status per ticker in the order confirmed_primary > corroborated >
  single_source > unverified > rumour > promotional > contradicted.
- Events: `events` type earnings, first date >= today per ticker.
- Session status: `marketbrief.pipeline.market_status.status(cfg, now)`.
- Back-test: `replay-<end>.json` of `scripts/replay.py` (horizons 1 and 5, `by_ticker.cover80`, `n`).

## Numbers on 2026-10-07
India: 20 rows, 0 YES, 0 Paper candidates (all P(up) 47%), 20 abstained, 1 blocked (TCS: results in 1 day),
462 headlines in 72 h (70 high); regime EVENT_HEAVY (RBI policy decision). US: 20 rows, 0 YES, 0 candidates,
20 abstained; regime TRENDING. Model skill: not shown (review 2026-W40) in both markets.
