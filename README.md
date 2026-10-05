# market-brief

Two scheduled Claude Code routines, one for India (NSE) and one for the US, that collect free
market data before the open, compute PASDS indicators and the market regime, reason over them
with subagents, log scored predictions and post one daily digest per market to Slack.
No paid APIs: RSS feeds, SEC EDGAR, yfinance, DuckDB, and your Claude subscription.
Design and roadmap: [`docs/DESIGN.md`](docs/DESIGN.md).

Research only. Nothing here is investment advice, and the routines never trade.

## How it works
1. **Holiday check** (`market_status.py`): exchange calendar; on holidays post one line and stop.
2. **Collect** (Python, no LLM): `collect_prices.py` (daily bars for 20 tickers plus benchmark,
   vol index, cues and global factors), `collect_quotes.py` (overnight / pre-market snapshot:
   futures, Asian markets, ADRs, pre-market gaps), `collect_events.py` (earnings, ex-dividend),
   `collect_news.py` (Google News + outlet RSS), `collect_filings.py` (SEC, US only).
3. **Score** past predictions against actual prices (`score_predictions.py`).
4. **Indicators and regime** (`features.py`): PASDS file 06 indicators per ticker (returns, EMA
   ratio, RSI, ATR, realized and EWMA volatility, Bollinger width, OBV, volume ratio, beta,
   sector-relative strength) and the file 07 regime (CALM / TRENDING / EVENT_HEAVY / UNSTABLE)
   from the vol index, benchmark trend and the event calendar (`config/events.yaml`).
5. **Calibrate** (`calibrate.py`): range quantiles from two years of standardized returns plus
   live scored ranges, recency-weighted (self-calibration).
6. **Context pack** (`context.py`): everything above as compact tables for the agents.
7. **Reason** (Claude subagents): news-analyst → bull-researcher + bear-researcher → forecaster.
8. **Ranges** (`ranges.py`): 50% and 80% price ranges per ticker for 1 and 5 trading days,
   widened for earnings, major events and the regime, centre nudged by overnight cues and
   the AI call. Scored daily against a naive baseline; `backtest.py` checks the formula
   walk-forward on history.
9. **Remember**: daily summaries, rolled up into weekly and monthly ones, per market.
10. **Charts and report** (`charts.py`, `report.py`): one chart per stock (60 days of prices,
    past ranges hit/miss, today's range cone with the call) plus an overview grid; the report
    and the Slack draft carry every number from the scripts, the agents add only narrative.
11. **Save** to this repo (append-only data) and **notify** Slack with one message per market.

Storage is date-partitioned files under `data/<market>/`, queried with DuckDB. See `sql/views.sql`.

## Coverage
`config/markets/india.yaml` and `config/markets/us.yaml`: 10 sectors x 2 companies each, plus
the market-level symbols. Edit tickers, sectors, regime thresholds and news feeds there.

## Reused open source
- [feedparser](https://github.com/kurtmckee/feedparser): RSS parsing
- [DuckDB](https://github.com/duckdb/duckdb): SQL over JSONL/CSV files
- [yfinance](https://github.com/ranaroussi/yfinance): daily prices and quotes (unofficial Yahoo Finance access; personal use)
- [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars): trading days and holidays
- [TradingAgents](https://github.com/TauricResearch/TradingAgents): the analyst/bull/bear/decision
  agent pattern, re-implemented as Claude Code subagents so no LLM API calls are billed

## Setup
1. **Slack**: create a channel `#market-brief`. Create a Slack app (api.slack.com/apps → Create New App →
   From scratch), turn on **Incoming Webhooks**, **Add New Webhook to Workspace**, pick `#market-brief`,
   and copy the webhook URL into the environment variable `SLACK_WEBHOOK_URL`. Allow `hooks.slack.com`
   in the network settings. (Routines created in the claude.ai UI can use the Slack connector instead.)
2. **Cloud environment** (claude.ai/code → environment settings):
   - Network access: **Custom**, tick "Also include default list of common package managers", and allow:
     `query1.finance.yahoo.com`, `query2.finance.yahoo.com` (all Yahoo data), `fc.yahoo.com` (cookie),
     `guce.yahoo.com`, `consent.yahoo.com` (yfinance's cookie fallback when `fc.yahoo.com` fails),
     `finance.yahoo.com` (only the earnings-calendar page `collect_events.py` reads first, with
     dates, times and EPS; if it fails the query1 screener supplies the dates, see
     docs/DESIGN.md section 11),
     `news.google.com`, `www.sec.gov`, `data.sec.gov`, `feeds.bbci.co.uk`,
     `economictimes.indiatimes.com`, `www.livemint.com`, `hooks.slack.com`, plus any outlet you add.
     (Moneycontrol and CNBC come in through Google News queries, so their own domains are not needed.)
   - Environment variable: `SEC_USER_AGENT=your-name your@email.com` (SEC requires contact info).
   - Setup script: `bash setup.sh`
3. **Routines** (claude.ai/code/routines → New routine), one per market, both on this repo and environment:
   - **India**: prompt = `routine/PROMPT.md` with `MARKET=india`; schedule weekdays 08:10 Asia/Kolkata.
   - **US**: prompt = `routine/PROMPT.md` with `MARKET=us`; schedule weekdays 08:15 America/New_York.
   - Connectors: keep only Slack. Remove everything else, especially anything that can trade.
4. **First run**: backfill two years of prices once (needed for beta and the range backtest).
   In a Claude Code session on the repo:
   `cd scripts && python collect_prices.py --market india --period 2y && python collect_prices.py --market us --period 2y`,
   then `python backtest.py --market india` and `--market us` (writes `reports/<market>/backtest-*.md`),
   commit, push. Then click **Run now** on each routine and read the transcript (a green
   status only means the session ran, not that the task succeeded).
5. **After adding a symbol** to a market config, backfill it once the same way (bars already
   stored are skipped, so only the new symbol's history is added). Pending one-off backfill:
   the India sector indices `NIFTYBANK`, `NIFTYIT` and `NIFTYPHARMA` (added 2026-10-05; the
   daily 1-month window gives them only ~18 bars, so their 20-day return is empty):
   `cd scripts && python collect_prices.py --market india --period 2y`, then commit and push `data/`.

## Local development
```
pip install -r requirements.txt
pytest -q                      # offline tests with synthetic data and fixtures
cd scripts && python collect_prices.py --market us && python features.py --market us && python context.py --market us
```
