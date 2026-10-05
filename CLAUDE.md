# market-brief

Personal research project: a scheduled Claude Code routine collects free news, prices and
SEC filings, reasons over them with subagents, makes small, scored directional predictions,
stores everything in this repo and posts a digest to Slack. Research only: never place
trades, never connect to brokerage tools, and nothing here is investment advice.

## Layout
- `config/` watchlist and feeds (edit these to change coverage)
- `scripts/` deterministic Python: collectors, scoring, context pack. Schemas live in `scripts/common.py`.
- `sql/views.sql` derived DuckDB views (returns, news by ticker/day, track record)
- `data/<kind>/YYYY/MM/YYYY-MM-DD.<ext>` raw, append-only records (UTC dates)
- `summaries/daily|weekly|monthly/` layered narrative memory written by Claude
- `reports/YYYY-MM-DD.md` the daily report linked from Slack
- `.claude/agents/` subagents: news-analyst, bull-researcher, bear-researcher, forecaster
- `routine/PROMPT.md` the routine's saved prompt

## Data rules
1. Files under `data/` are append-only. Never edit, reorder or delete existing lines or files.
   Corrections are new records (e.g. a newer `news_enriched` row for the same id).
2. Agents append via a temp file in `work/` then `cat work/x.jsonl >> data/...`. Never use a
   tool that overwrites an existing data file.
3. All timestamps are ISO 8601 UTC. Never use information published after a prediction's `made_at`.
4. Numbers come from `scripts/context.py` or DuckDB (`python -c "from common import connect; ..."`
   run from `scripts/`), never from memory or estimation.
5. Don't read raw data files in bulk. Use the context pack, DuckDB queries and the summaries.

## Prediction rules
- One record per call: `id` = `<as_of_date>-<ticker>-<horizon>d`; skip if the id already exists.
- `direction` is `up` or `down`; `horizon_days` is 1 or 5 (trading days); `confidence` 0.50-0.90.
- `as_of_date` = the latest price date in the context pack for that ticker.
- `evidence_ids` must reference news/filing ids. Abstaining is always allowed and often right.
- Calibrate against the track record: if a confidence band hits less often than its stated
  confidence, use lower confidence or abstain.
- `prompt_version` identifies the agent instructions used (bump it when agent files change).
