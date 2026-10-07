# Notes: queries and commands behind decision-HDFCBANK.html

All runs on 2026-10-07 (UTC). The repo was read only; everything written lives in this folder.

## Commands

- `python scripts/model_backtest.py --market india --out <this>/bt` (11m50s): walk-forward JSON/HTML with the
  skill table (Brier, AUC, Platt, paper strategy vs baselines). Aggregates only, no per-row output.
- Rule replay into a scratch root, so nothing lands in `data/` or `reports/`:
  `replayroot/data/india/<kind>` are symlinks to the repo's data folders, `replayroot/data/india/replays`
  and `replayroot/reports/india` are real empty folders;
  `MB_ROOT=<this>/replayroot python scripts/replay.py --market india --start 2026-08-17 --end 2026-10-06`
  -> `replayroot/reports/india/replay-2026-10-06.json` (3 s). Aggregates only as well.
- `extract.py`: calls the library behind both scripts for per-row output:
  `rule_replay.inputs.load_inputs` + `rule_replay.range_rows.replay_rows(cfg, ranges_config, bars, extra, start, end)`
  (per as-of day x ticker: base, center, lo/hi 50/80, target_date, actual, hit50/hit80, regime, major, earn) and
  `model.walk_forward.walk_forward(panel, ('india','open_to_close', h), settings)` on
  `model.panel.build_panel(cfg, model.panel_inputs.read_inputs(con,'india'), warmup)` (per date x ticker: prob,
  prob_raw, calibrated, base_rate, cutoff, ret, end, up). Filtered to HDFCBANK, 2026-08-17..2026-10-06 ->
  `hdfcbank_history.json`.
- `build.py`: DuckDB reads (below), cause derivation, costs, calendar -> `data.json`, and inlines it into
  `template.html` -> `decision-HDFCBANK.html` (257 KB, no external requests).
- `node shoot.js`: Playwright with `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`; checks console
  errors/warnings, page errors, non-file requests and horizontal overflow at 1280 and 390; writes the shots.
  Final run: "no console errors, no overflow, no external requests". `node crop.js`: per-section phone crops.
- Palette check (dataviz skill): `node scripts/validate_palette.js "#2a78d6,#3c3b38" --mode light` (the ink is a
  text token, so its band/chroma failure is expected; CVD and normal-vision separation pass);
  `"#0ca30c,#d03b3b,#2a78d6" --pairs all`: good vs critical fail CVD (dE 4.1), which is why every hit/miss mark
  carries a tick/cross glyph and the word "in"/"out", never colour alone.

## DuckDB queries (run from `scripts/`, `connect('india')`)

- Prices: `select date, ticker, open, close from ohlc where ticker in ('HDFCBANK','NIFTY50','NIFTYBANK','INDIAVIX') and date >= '2026-08-10'`
  -> day moves of the stock, Nifty 50, Nifty Bank, India VIX (cause derivation).
- Live rows: `model_scores` (2 runs for 2026-10-06: 05:08 and 05:11 UTC; `model_scores_latest`), `ranges`
  (2026-10-01 1d+5d made 2026-10-05 14:53; 2026-10-06 5d made 2026-10-07 05:14, notes
  `regime EVENT_HEAVY x1.1, major event x1.15, late: 2026-10-07 opened before made_at, cue +1.40% x0.5`; no 1d
  row for 2026-10-06), `agent_reasoning` (2026-10-06-HDFCBANK, abstain/abstain, forecast-v12),
  `features_latest`, `regime` (latest by computed_at: EVENT_HEAVY, RBI policy decision), `quotes_latest` day
  2026-10-07, `flows_daily`, `fpi_latest`, `indices_latest`, `delivery_stats`, `earnings_estimates`.
- `predictions`, `outcomes`, `range_outcomes`: 0 rows each (nothing live is scored yet).
- News: `news` where `list_contains(tickers,'HDFCBANK')` (123 rows, 2026-10-04 15:48 .. 2026-10-07 04:47 UTC)
  joined to `enriched_latest` (sentiment, materiality, event_type, priced_in, summary) and `news_verified`
  level `cluster` (id = `HDFCBANK-<newsid>|*@...`): statuses are `single_source` (ba14ee8a9b2558de Reuters
  wire; dd31e044314de2b7 BusinessLine) and `unverified`; items without a cluster row are "not assessed".
- Events: `events` type `earnings` for HDFCBANK (2023-10-16 .. 2026-10-17; `timing` before_open/after_close/
  during); `ex_dividend`. Market events come from `core.calendar.market_events(cfg, 2026-10-07, 2026-12-15)`
  (RBI 7 Oct and 4 Dec, F&O expiry 27 Oct / 23 Nov, FOMC 29 Oct / 10 Dec, US jobs 6 Nov / 4 Dec, weekly
  expiries). Next sessions: `sessions_ahead(cfg, 2026-10-06, 6)` -> 7, 8, 9, 12, 13 Oct; reaction session of
  the 17 Oct (Saturday) results: `next_session` -> 2026-10-19.
- Results-day moves: for each stored earnings date with a stored bar window, close-to-close move on the
  reaction session (before_open/during: first session on/after the date; after_close: first session after):
  2024-10-21 +2.79, 2025-01-22 +1.44, 2025-04-21 +1.07, 2025-07-21 +2.20, 2025-10-20 +0.04, 2026-01-19 -0.34,
  2026-04-20 -0.56, 2026-07-20 -5.12 (median |move| 1.26%).
- Costs: `model.settings.load_costs('india')`, `round_trip_cost('india', costs)` = 0.0022248 (Rs 22.25 per Rs 10,000).

## Derived numbers on the page

- Cause of a day's move (deterministic, in build.py): "market-wide" when Nifty 50 or Nifty Bank moved >= 0.75%
  the same way; else "company news" when stored high-materiality headlines exist for that IST day (only from
  4 Oct); else "unexplained" (labelled mock: explainer agent coming). 5-day rows use the biggest day in the window.
- Gap rule price = base close x exp(published centre): 1d 712 (rule replay), 5d 716 (live).
- Rs 10,000 outcome = 10,000 x (edge / base - 1) - 22.25, for the 50% and 80% edges.
- Back-test summaries for HDFCBANK 17 Aug..6 Oct: 1d 80% band held 26/34, 50% band 13/34; 5d 26/30 and 16/30;
  model lean right 19/33 (1d) and 16/30 (5d); calibrated P(up) range 47.1..48.6% (1d), 47.0..49.1% (5d).
- All-20-stock skill (bt JSON): 1d otc n 6640 Brier 0.2514 vs 0.2496, AUC 0.4853 [0.4563, 0.5174]; 5d otc
  n 6160 Brier 0.2555 vs 0.2509, AUC 0.5023 [0.4529, 0.5469]; Platt of the latest fit [0.0, -0.1159] (slope 0,
  which is why the calibrated probability is flat). 5d paper long at >= 0.60: 999 positions / 76 dates, mean
  -0.17% after costs, 95% CI [-0.84, 0.28]; always-up baseline -0.42%.
