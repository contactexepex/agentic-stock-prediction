"""The AI traders, the EOD analyst and the weekly research director (docs/SPEC.md F4 and F6; session B3; notes in
docs/ws/b3.md). Deterministic code only: the agents are `.claude/agents/trader-*.md`, `forecaster.md` (the Opus
combined trader), `eod-analyst.md` and `research-director.md`; this package prepares their inputs and gates their
output before anything reaches data/. Built against `marketbrief.contracts` (B2's engine, B10's per-horizon ranges and
scores, B1's watchlist). Research only: a prediction or paper trade is a record, never an order.

- registry       the four traders: config/strategies.yaml entries + agent-file settings (kill switch, budget)
- sessions       D, the exit session of N+k, the deadline (D's open - 15 minutes)
- inputs         what the gate checks against (GateInputs), loaded as of the run's clock
- gate, gate_evidence   one prediction's rules (shared with prediction_rules and the forecast-v11 anchor)
- run, outcome   a trader's file: validate, add with one retry, abstention records
- prepare        the trader's input file
- track_record   its own record per confidence band
- settle_step    post-close settlement through contracts.protocol.settle
- eod_facts, eod_gate, eod, numbers   the EOD analyst's facts, gate and storage
- director_facts, director, director_report   the weekly research director
- cli            the command line (`python -m marketbrief.traders`)"""
