"""Interfaces later sessions code against (W1; docs/SPEC.md section 10): signatures, record formats and
docstrings only, no logic. Every function here raises NotImplementedError until the owning session builds it:

- `protocol`   the F1 paper-trading protocol (session B2 builds `marketbrief/lab/`)
- `watchlist`  the company-list accessor of F8.2 (session B1 builds `marketbrief/lifecycle/`)
- `horizons`   the per-horizon model-score and range records of F2.7 (session B10 extends model/ and ranges)
- `strategies` the registry format of config/strategies.yaml (F2.1), with the allowed values the test checks

Stored records (strategy_predictions, paper_trades_settled, ...) are the column dicts of
`marketbrief.core.schema_lab` / `schema_lifecycle`; the types here name only what no stored kind holds yet."""
