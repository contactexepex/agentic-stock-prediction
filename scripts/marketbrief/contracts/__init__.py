"""Interfaces later sessions code against (W1; docs/SPEC.md section 10): signatures, record formats and
docstrings only, no logic. A function raises NotImplementedError until the owning session builds it, then delegates
to that session's module:

- `protocol`   the F1 paper-trading protocol (built by B2: delegates to `marketbrief/lab/protocol.py`)
- `watchlist`  the company-list accessor of F8.2 (built by B1: delegates to `marketbrief/lifecycle/accessor.py`)
- `horizons`   the per-horizon model-score and range records of F2.7 (session B10 extends model/ and ranges)
- `strategies` the registry format of config/strategies.yaml (F2.1), with the allowed values the test checks

Stored records (strategy_predictions, paper_trades_settled, ...) are the column dicts of
`marketbrief.core.schema_lab` / `schema_lifecycle`; the types here name only what no stored kind holds yet."""
