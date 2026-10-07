# Notes: inputs behind help.html

Built 2026-10-07 (UTC); repo read only. `python design/help/build.py --out <dir>` (a few seconds).

- Rules: `config/model.yaml` (model_version, refit, news lookback_hours, status and materiality weights),
  `config/ranges.yaml` (horizons, max_ai_widen, major_event_factor, regime_factor, earnings multiples),
  `config/settings.yaml` (call_scoring basis and date, model_training_cutoff, repo_url); the call line from
  `design/watchlist/build.py` CALL_THRESHOLD (0.60), the stake from `design/portfolio/build.py` STAKE (10,000);
  the strength rule, confidence range, adjustment cap, results block and single-source penalty as constants in
  `build.py` restating `design/decision/build.py` and CLAUDE.md.
- Gate: `config/review.yaml` min_n_recommend 200, min_n_calls 50, calibration_tolerance 0.05, confidence_bands,
  model_skill {min_n 500, min_brier_skill 0, min_auc_low 0.5}.
- Per market: `load_market`; as-of = `max(date) from ohlc` for the watchlist; next session via `next_session`;
  session hours from `session_open_utc` / `session_close_utc` in the market's timezone and UTC; round-trip cost
  from `marketbrief.model.settings.round_trip_cost(market, load_costs(market), 100.0)` (India 0.2225%, US
  0.0021%); symbols by role; news feed counts from `news.google_news|outlets|categories`; data kinds = the
  directories under `data/<market>/` (India 30, US 31); counts from `news`, `predictions`, `ranges`, `lessons`;
  first stored bar = `min(date) from ohlc`.
- Numbers on 2026-10-07: India session 09:15–15:30 IST (03:45–10:00 UTC), 1,920 headlines, 60 ranges, 0 calls,
  0 lessons; US 09:30–16:00 ET (13:30–20:00 UTC), 2,911 headlines, 40 ranges, 0 calls, 0 lessons.
