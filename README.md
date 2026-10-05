# market-brief

A scheduled Claude Code routine that collects free market data, reasons over it with
subagents, logs scored directional predictions, and posts a daily digest to Slack.
No paid APIs: RSS feeds, SEC EDGAR, yfinance, DuckDB, and your Claude subscription.

Research only. Nothing here is investment advice, and the routine never trades.

## How it works
1. **Collect** (Python, no LLM): `collect_news.py` (Google News RSS + outlet RSS via feedparser),
   `collect_prices.py` (yfinance), `collect_filings.py` (SEC EDGAR JSON).
2. **Score** past predictions against actual prices (`score_predictions.py`).
3. **Context pack** (`context.py`): returns, news activity/sentiment, filings, track record via DuckDB.
4. **Reason** (Claude subagents): news-analyst → bull-researcher + bear-researcher → forecaster.
5. **Remember**: daily summaries, rolled up into weekly and monthly ones.
6. **Save** to this repo (append-only data) and **notify** Slack.

Storage is date-partitioned files under `data/`, queried with DuckDB. Aggregate any window with
`time_bucket(INTERVAL '2 weeks', day)` etc. See `sql/views.sql`.

## Reused open source
- [feedparser](https://github.com/kurtmckee/feedparser): RSS parsing
- [DuckDB](https://github.com/duckdb/duckdb): SQL over JSONL/CSV files
- [yfinance](https://github.com/ranaroussi/yfinance): daily prices (unofficial Yahoo Finance access; personal use)
- [TradingAgents](https://github.com/TauricResearch/TradingAgents): the analyst/bull/bear/decision
  agent pattern, re-implemented as Claude Code subagents so no LLM API calls are billed
- Optional later: [edgartools](https://github.com/dgunning/edgartools) for parsing filing financials

## Setup
1. **Repo**: create a private GitHub repo, push this folder to `main`. Make sure `main` is not
   protected against pushes from your account (the routine commits data there).
2. **Coverage**: edit `config/watchlist.yaml` (tickers, aliases) and `config/feeds.yaml` (categories, outlets).
3. **Slack**: create a channel `#market-brief`; connect the Slack connector at claude.ai/customize/connectors.
4. **Cloud environment** (claude.ai/code → environment settings):
   - Network access: **Custom**, tick "Also include default list of common package managers", and allow:
     `news.google.com`, `feeds.bbci.co.uk`, `www.cnbc.com`, `www.sec.gov`, `data.sec.gov`,
     `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `fc.yahoo.com`, plus any outlet you add.
   - Environment variable: `SEC_USER_AGENT=your-name your@email.com` (SEC requires contact info).
   - Setup script: `bash setup.sh`
5. **Routine** (claude.ai/code/routines → New routine):
   - Prompt: paste `routine/PROMPT.md` (replace `OWNER/REPO`).
   - Repository: this repo. Environment: the one from step 4.
   - Trigger: Schedule → Weekdays, e.g. 07:07 (avoid exactly on the hour).
   - Connectors: keep only Slack. Remove everything else, especially anything that can trade.
6. **First run**: backfill prices once so 20-day returns work. In a Claude Code session on the repo:
   `cd scripts && python collect_prices.py --period 3mo`, commit, push. Then click **Run now** on the
   routine and read the transcript (a green status only means the session ran, not that the task succeeded).

## Local development
```
pip install -r requirements.txt
pytest -q                      # offline tests with fixtures
cd scripts && python collect_news.py && python context.py
```
