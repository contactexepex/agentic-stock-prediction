# Notes: queries and inputs behind track.html

Built 2026-10-07 (UTC); repo read only. `python design/track/build.py --out <dir>` (about 10 s; reuses the
rule replay JSON under `work/design/replayroot-<market>/` and the model back-test JSON under
`work/design/bt-<market>/`, running them when missing).

## DuckDB (run from `scripts/`, `connect(market)`)
- Live calls: `outcomes` joined to `predictions` (confidence, hit, label_basis), bucketed into the bands of
  config/review.yaml (0.50, 0.60, 0.70, 0.80, 0.90): 0 rows in both markets on 2026-10-07.
- `predictions` count, `open_predictions` count: 0 and 0.
- `range_record` (scored ranges, hit50/hit80, interval scores): 0 rows; `open_ranges`: India 60 (targets
  2026-10-05 .. 2026-10-13), US 40.
- `ranges` first as_of_date: 2026-10-01 (both markets). `lessons`: 0.
- `reviews` latest: 2026-W40 (India computed 05:14 UTC, US 04:46 UTC): model_skill false, no scored ranges
  or calls, low_sample true, India proposal "drop regime widening".
## JSON inputs
- Rule replay `replay-<end>.json`: horizons 1 and 5 (overall, by_regime, by_month, by_sector, by_ticker:
  n, days, cover50/80 with cover80_ci, widths, score80 vs naive_score80), baselines per horizon (always_up,
  momentum_1d, momentum_5d, rsi_mean_reversion: calls, hits, hit_rate, ci95), regime_days, summary,
  limitations.
- Model back-test `model-backtest-<market>-<date>.json`: results per label (n, dates, up_share, brier,
  brier_base_rate, brier_skill, log_loss, auc, auc95, reliability bins with wilson95, thresholds long/short,
  paper: mean_cost_pct, baselines, thresholds with vs), model facts (fits, cutoffs, last_platt).
## Gates (config/review.yaml)
min_n_calls 50, calibration_tolerance 0.05, model_skill {min_n 500, min_brier_skill 0.0, min_auc_low 0.5}.
India 5d open-to-close: n 6160, Brier skill -0.0186, AUC 0.5023 [0.4529, 0.5469] -> fails; 1d: skill
-0.0069, AUC 0.4853. US fails the same two tests.
