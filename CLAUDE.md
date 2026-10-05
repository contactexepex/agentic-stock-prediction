# market-brief

Personal research project: two scheduled Claude Code routines (India and US) collect free
prices, overnight cues, news, events and SEC filings, compute PASDS indicators and the market
regime, reason over them with subagents, make small, scored predictions, store everything in
this repo and post one Slack digest per market. Research only: never place trades, never
connect to brokerage tools, and nothing here is investment advice. Design: `docs/DESIGN.md`.

## Layout
- `config/markets/<market>.yaml` per market: exchange calendar, timezone, market-level symbols
  (benchmark, vol index, cues, factors), regime thresholds, sectors, tickers, news feeds
- `config/events.yaml` scheduled market events (rules and fixed dates)
- `scripts/` deterministic Python. Every script takes `--market india|us` (or `MB_MARKET`).
  Collectors: `collect_prices`, `collect_quotes`, `collect_events`, `collect_news`,
  `collect_filings`. Then `score_predictions` (calls and ranges), `features` (indicators +
  regime), `calibrate`, `context`, and after the forecaster `ranges`. `backtest` evaluates the
  range formula walk-forward. Formulas: `indicators.py` (PASDS file 06), `regime.py` (file 07),
  `events.py` (calendar), `rangelib.py` (ranges; settings in `config/ranges.yaml`).
  Schemas live in `scripts/common.py`.
- `sql/views.sql` derived DuckDB views (bars, returns, latest features/regime/quotes, events,
  news by ticker/day, track record)
- `data/<market>/<kind>/YYYY/MM/YYYY-MM-DD.<ext>` raw, append-only records (UTC dates, except
  prices/features/regime which use the trading date)
- `summaries/<market>/daily|weekly|monthly/` layered narrative memory written by Claude
- `reports/<market>/YYYY-MM-DD.md` the daily report linked from Slack
- `.claude/agents/` subagents: news-analyst, bull-researcher, bear-researcher, forecaster
- `routine/PROMPT.md` the routines' saved prompt (one per market)

## Data rules
1. Files under `data/` are append-only. Never edit, reorder or delete existing lines or files.
   Corrections are new records (e.g. a newer `news_enriched` row for the same id).
2. Agents append via a temp file in `work/` then `cat work/x.jsonl >> data/...`. Never use a
   tool that overwrites an existing data file.
3. All timestamps are ISO 8601 UTC. Never use information published after a prediction's `made_at`.
4. Numbers come from `scripts/context.py` or DuckDB (run from `scripts/`:
   `python -c "from common import connect; print(connect('us').execute('...').df())"`),
   never from memory or estimation.
5. Don't read raw data files in bulk. Use the context pack, DuckDB queries and the summaries.
6. A market's agents only read and write that market's `data/<market>/`, `summaries/<market>/`
   and `reports/<market>/`.

## Prediction rules
- One record per call: `id` = `<as_of_date>-<ticker>-<horizon>d`; skip if the id already exists.
- `direction` is `up` or `down`; `horizon_days` is 1 or 5 (trading days); `confidence` 0.50-0.90.
- `as_of_date` = the latest price date in the context pack for that ticker.
- `evidence_ids` must reference news/filing ids. Abstaining is always allowed and often right.
- No new call for a ticker with indicator quality `BLOCKED`, or with earnings within 1 day
  (`days_to_earnings` <= 1). Lower confidence in `EVENT_HEAVY` and `UNSTABLE` regimes.
- Price ranges are computed by `scripts/ranges.py`, never by hand. The forecaster may only
  widen a range (`range_widen` 0-0.5), never narrow it.
- Calibrate against the track record: if a confidence band hits less often than its stated
  confidence, use lower confidence or abstain.
- `prompt_version` identifies the agent instructions used (bump it when agent files change).
