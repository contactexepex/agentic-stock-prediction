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
   `collect_news.py` (Google News + outlet RSS, incl. Business Standard and BusinessLine for India,
   PR Newswire, Business Wire earnings and GlobeNewswire releases for the US), `collect_filings.py` (SEC, US
   only), `collect_macro.py` (US: Treasury yield curve, FRED credit spreads, Cboe put/call),
   `collect_shorts.py` (US: FINRA short-sale volume and short interest) and
   `collect_flows_india.py` (India: NSDL FPI flows, NSE sector index closes and valuations).
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
10. **Charts and report** (`charts.py`, `report.py`, `html_report.py`): three single-purpose
    chart images (price ranges, sector moves, track record); the markdown report and the Slack
    draft carry every number from the scripts, the agents add only narrative; after the
    validation gate (`validate.py`, which also checks every narrative number) passes, a self-contained HTML report per day (filters by sector and company, a price chart,
    plain-language range and reasons per company) is built from the filled report and the data.
11. **Save** to this repo (append-only data) and **notify** Slack: one thread per market (summary,
    chart images, the HTML file).
12. **Neo4j copy** (optional, `neo4j_sync.py`): the same data and results as a graph (companies,
    holders, news, events, trades, holdings, connections, predictions, ranges, outcomes) for
    analysis. The repo stays the source of truth; `--full` rebuilds the graph from it.

Storage is date-partitioned files under `data/<market>/`, queried with DuckDB. See `sql/views.sql`.
The graph model and example Cypher queries are in [`docs/DESIGN.md`](docs/DESIGN.md) section 12.

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
   For the threaded post with chart images and the HTML file, add bot scopes `chat:write` and
   `files:write`, install the app, invite the bot to `#market-brief`, put its token in
   `SLACK_BOT_TOKEN` and allow `slack.com` and `files.slack.com`. The channel id is
   `slack_channel_id` in `config/settings.yaml`. Without the token the webhook text post is used.
2. **Cloud environment** (claude.ai/code → environment settings):
   - Network access: **Custom**, tick "Also include default list of common package managers", and allow:
     `query1.finance.yahoo.com`, `query2.finance.yahoo.com` (all Yahoo data), `fc.yahoo.com` (cookie),
     `guce.yahoo.com`, `consent.yahoo.com` (yfinance's cookie fallback when `fc.yahoo.com` fails),
     `finance.yahoo.com` (only the earnings-calendar page `collect_events.py` reads first, with
     dates, times and EPS; if it fails the query1 screener supplies the dates, see
     docs/DESIGN.md section 11),
     `news.google.com`, `www.sec.gov`, `data.sec.gov`, `feeds.bbci.co.uk`,
     `economictimes.indiatimes.com`, `www.livemint.com`, `hooks.slack.com`, plus any outlet you add.
     Macro, flows and press releases (issue #9): `home.treasury.gov`, `fred.stlouisfed.org`,
     `cdn.cboe.com`, `cdn.finra.org`, `api.finra.org`, `fpi.nsdl.co.in`, `nsearchives.nseindia.com`,
     `www.business-standard.com`, `www.thehindubusinessline.com`, `www.prnewswire.com`,
     `feed.businesswire.com`, `www.globenewswire.com`.
     (Moneycontrol and CNBC come in through Google News queries, so their own domains are not needed.)
   - Environment variable: `SEC_USER_AGENT=your-name your@email.com` (SEC requires contact info).
   - Optional, Neo4j copy: `NEO4J_URI` (`neo4j+s://<id>.databases.neo4j.io`), `NEO4J_USER`,
     `NEO4J_PASSWORD` (and `NEO4J_DATABASE` only if it is not the `<id>` in the host, as on Aura),
     and allow the host `<id>.databases.neo4j.io` in the network settings. The sync uses the HTTPS
     Query API (port 443), not Bolt. Check with `cd scripts && python neo4j_sync.py --market us --probe`,
     load everything once with `--full`; the routine then syncs incrementally.
   - Setup script: `bash setup.sh`
3. **Routines** (claude.ai/code/routines → New routine), one per market, both on this repo and environment:
   - **India**: prompt = `routine/PROMPT.md` with `MARKET=india`; schedule weekdays 08:10 Asia/Kolkata.
   - **US**: prompt = `routine/PROMPT.md` with `MARKET=us`; schedule weekdays 08:15 America/New_York.
   - Connectors: keep only Slack. Remove everything else, especially anything that can trade.
4. **First run**: backfill two years of prices once (needed for beta and the range backtest).
   In a Claude Code session on the repo:
   `cd scripts && python collect_prices.py --market india --period 2y && python collect_prices.py --market us --period 2y`,
   then `python backtest.py --market india` and `--market us` (writes `reports/<market>/backtest-*.md`),
   and `python replay.py --market india` and `--market us` (historical replay of all rule-based
   parts: ranges, regime and direction baselines scored day by day; writes a self-contained
   `reports/<market>/replay-<end>.html` with a plain-language summary, a `.json` with every number,
   and a row in `data/<market>/replays/`; `--start`/`--end` pick the as-of window),
   commit, push. Then click **Run now** on each routine and read the transcript (a green
   status only means the session ran, not that the task succeeded).
5. **After adding a symbol** to a market config, backfill it once the same way (bars already
   stored are skipped, so only the new symbol's history is added). Pending one-off backfill:
   the India sector indices `NIFTYBANK`, `NIFTYIT` and `NIFTYPHARMA` (added 2026-10-05; the
   daily 1-month window gives them only ~18 bars, so their 20-day return is empty):
   `cd scripts && python collect_prices.py --market india --period 2y`, then commit and push `data/`.
6. **AI replay before going live** (optional; `scripts/ai_replay.py`, docs/DESIGN.md section 7). It
   tests the AI agents on past days after the model's training data (as-of dates after 2026-06-30),
   strictly as of that day. The script never runs an LLM: the orchestrating session runs the agents.
   ```
   cd scripts
   python ai_replay.py dates --market us                        # the sample: every 5th trading day, 2026-07-01..09-25
   python ai_replay.py backfill --market us --source ../work/replay/src-us --since 2026-06-01
   #  -> copy of data/us plus SEC filings, Form 4 and 13D/13G since then (India: NSE announcements,
   #     results filings, PIT insider trades, bulk/block deals) in a scratch source, never data/
   python ai_replay.py prepare --market us --date 2026-07-01 --root ../work/replay/us-2026-07-01 \
       --source ../work/replay/src-us
   #  -> as-of copy of data/us (only what was public before the next session's pre-open start), then
   #     features, calibrate, context (work/context.md in the root) and ranges as of that time;
   #     prints what was kept or dropped. Run the agents with MB_ROOT=<root> and that context pack;
   #     the forecaster writes <root>/work/predictions.jsonl (an empty file = it abstained on all).
   python ai_replay.py record --market us --date 2026-07-01 --root ../work/replay/us-2026-07-01 \
       --calls ../work/replay/us-2026-07-01/work/predictions.jsonl --results ../work/ai_replay
   python ai_replay.py score --market us --results ../work/ai_replay --out ../work/ai_replay/us.html
   ```
   `record` validates every call (schema and CLAUDE.md prediction rules, evidence ids must exist in
   the as-of root) and stores the valid ones in `<results>/<market>/calls.jsonl` with `replay: true`,
   never in `data/`. `score` checks them against the real stored closes and writes a plain-language
   HTML page and a `.json` next to it. Use a `backfill` source: the repo's own data has no SEC
   filings before 2026-09-28, no news before October 2026 and no NSE announcements, so without it
   there is nothing citable on the sample days. Upcoming earnings dates are not known honestly as of
   a past day (no source stores when a date was announced); `prepare --assume-earnings-known 14`
   uses the actual dates and labels them as an assumption.

## Local development
```
pip install -r requirements.txt
pytest -q                      # offline tests with synthetic data and fixtures
cd scripts && python collect_prices.py --market us && python features.py --market us && python context.py --market us
```
