# Dip-Watch Build Brief for Claude Code

Build a `dip-watch` module inside the existing `market-brief` repo: Python scripts do prices, maths and backtests; a Claude Code cloud routine runs hourly during US market hours, judges the cause of each dip and posts alerts to Slack. Research only: it never places trades.

## 1. Context

- The repo `market-brief` already exists on GitHub with collectors for news (Google News RSS), prices (yfinance) and filings (SEC EDGAR), DuckDB views and a cloud environment whose network allowlist already includes Google News, SEC and Yahoo Finance.
- The old market-brief routines are paused and stay paused. Reuse their code; do not re-enable them.
- Connectors available inside the routine: Bigdata.com (news, earnings calendar, financials, tearsheets) and Slack.
- Bigdata.com runs on prepaid credits, so call it only for flagged tickers.
- Broker is Revolut: only alert on tickers listed in `config/revolut_available.yaml`.
- Cost rule: Python does all cheap, exact work; Claude is only invoked when something is flagged. Quiet runs post nothing.

## 2. Strategy rules

### Universe

- US-listed companies with market cap at least $1 billion, from mid-caps up to trillion-dollar names (include recent large IPOs such as SpaceX, ticker SPCX).
- S&P 500 is the core universe; extend with other US stocks above $1B.
- Minimum liquidity: average daily dollar volume of at least $20 million (configurable).
- Smaller companies (under $10B) get smaller position sizes.

### Quality check

- Revenue growing over the last 4 quarters (TTM vs prior TTM).
- Manageable debt: debt-to-equity and interest coverage within configurable limits; flag high-debt names into a `speculative` bucket instead of excluding them.
- No recent going-concern warnings or major negative filings.
- Positive operating margin (configurable exceptions for the speculative bucket).

### Mode A: long-term dip

- Trigger: price at least 15% below the 52-week closing high; stronger signals at 20% and 25%+.
- Buy in 3 stages, one third each at 15%, 20% and 25%+ below the high. If a stock is already past 25% when first flagged, stage 1 starts at the current price and later stages are measured as further drops from the entry price.
- Sell alerts when a holding is up 15%, then 20%, then 30%+. Recovery may take days to months.

### Mode B: short-term quick dip

- Trigger: the market falls sharply in one day (S&P 500 down at least 2%, configurable) and a healthy stock falls at least 5% that day with no company-specific bad news.
- Sell target 5-10% gain; stop-loss set at purchase (default 7% below entry, configurable); review if neither is hit within about 7 trading days.
- Logged separately from long-term positions.

### Cause of the dip (judged by Claude)

Each flagged dip is classified as one of:

1. **Market-wide:** usually a candidate.
2. **Sector:** a candidate if fundamentals still hold.
3. **Company-specific bad news:** a warning, normally skip.
4. **Quarterly results:** a candidate only if the numbers are decent and the drop looks like an overreaction.

### Blackout and risk

- No new buys within 3 trading days before a company reports results.
- Maximum amount per stock, a smaller cap for the speculative bucket and for sub-$10B names, and a cash reserve that is never used. All in `config/rules.yaml`.
- Each buy candidate includes a suggested limit price about 3% below the last price (configurable).

## 3. Repo layout

Add under `dip-watch/` in the market-brief repo, reusing `scripts/common.py`, the existing collectors and DuckDB setup where possible:

```
dip-watch/
  config/
    rules.yaml              # all thresholds: dip levels, stops, targets, caps, blackout days
    universe.yaml           # optional extra tickers beyond the screened universe (e.g. SPCX)
    revolut_available.yaml  # tickers confirmed tradeable on Revolut (user maintains)
  data/
    positions.csv           # user's real buys and sells (append-only)
    signals/YYYY/MM/*.jsonl # every signal ever raised (append-only, UTC)
    universe/YYYY-MM-DD.csv # daily snapshot of the screened universe
  scripts/
    build_universe.py
    fetch_prices.py
    indicators.py
    quality.py
    scan.py
    positions.py
    backtest.py
    report.py
  routine/
    PROMPT.md
  tests/
  README.md
```

Rules: data files are append-only, all timestamps in UTC, configuration only in YAML (no thresholds hard-coded in scripts), and no bulk reading of raw data by Claude; it reads the compact output of `scan.py`.

## 4. Scripts

### build\_universe.py

- Build the universe once a day: S&P 500 members plus other US-listed stocks with market cap of at least $1B and the liquidity floor, plus anything in `universe.yaml`.
- Use free sources (yfinance, public index constituent lists). Cache the result to `data/universe/`.
- Output columns: ticker, name, sector, industry, market cap, average daily dollar volume, size bucket (mega, large, mid).

### fetch\_prices.py

- Daily OHLCV history (at least 3 years for the backtest) and the latest intraday price for each ticker in the universe, via yfinance in batches.
- Also fetch the S&P 500 index, the sector ETFs (XLK, XLV, XLF and so on) and VIX.
- Handle rate limits with retries and back-off; never crash the whole run on one bad ticker.

### indicators.py

For each ticker, compute:

- percent below the 52-week closing high, and today's percent change;
- RSI(14) and volume relative to the 20-day average;
- 50-day and 200-day moving averages;
- move relative to its sector ETF and to the S&P 500 today (peer comparison);
- recovery history: for past drops of similar size, median days to recover 5%, 10%, 15% and to the prior high.

### quality.py

- Pull fundamentals (revenue TTM vs prior TTM, operating margin, debt-to-equity, interest coverage, current P/E and P/S, and their 5-year percentiles) from yfinance or SEC EDGAR company facts.
- Return pass, speculative or fail with the reasons, using thresholds from `rules.yaml`.
- Cache fundamentals for a day; they do not change hourly.

### scan.py

The hourly entry point. Steps:

1. Load cached universe, refresh prices and indicators.
2. Detect the market backdrop: S&P 500 change today, VIX level and change.
3. Apply Mode A and Mode B triggers.
4. Drop tickers that fail quality, are not on the Revolut list, or are in the earnings blackout.
5. Skip tickers already alerted at the same stage in the last 24 hours (no duplicate alerts).
6. Run `positions.py` checks for sell alerts.
7. Write a compact `work/context.json`: market backdrop, flagged tickers with all indicators and fundamentals, and any sell or stop alerts. If nothing is flagged, write `{"flagged": []}` and exit with code 0.

### positions.py

- Read `data/positions.csv` (columns: id, ticker, mode, date, action, shares, price, stage, target, stop).
- Compute average entry price per open position and current gain or loss.
- Raise sell alerts at +15%, +20%, +30% for Mode A; target, stop and 7-day review alerts for Mode B.
- Provide a small CLI to add a buy or sell: `python positions.py add --ticker GOOGL --mode A --shares 5 --price 289.74 --stage 1`.

### backtest.py

- Replay the Mode A and Mode B price rules over at least 3 years of daily history for the universe.
- For each historic signal, record the return after 5, 10, 20 and 60 trading days, the maximum drawdown before recovery, and whether the target or stop was hit first.
- Output summary tables by mode, size bucket and sector: hit rate, median return, worst case, average days to target.
- Clearly state the limit: it tests price rules only, not Claude's news judgement, and uses today's universe, so it has survivorship bias.

### report.py

- Turn Claude's decisions plus `context.json` into a markdown report saved to `reports/dip-watch/YYYY-MM-DD-HH.md` and a short Slack message.

## 5. Routine prompt (routine/PROMPT.md)

Paste this as the routine prompt, replacing `OWNER/REPO`:

```markdown
You are Dip-Watch, a research assistant for a US stock dip-buying strategy.
You never place trades. You produce research alerts only.

Repository: OWNER/REPO. Work inside dip-watch/.

STEP 1 - Scan (no reasoning needed)
Run: python dip-watch/scripts/scan.py
Read work/context.json.
If "flagged" is empty and there are no sell or stop alerts: stop. Post nothing. Commit nothing.

STEP 2 - Research each flagged ticker (only these)
For each flagged ticker, use Bigdata.com to get:
- latest company news and sentiment from the last 5 days
- next earnings date (double-check the blackout)
- any analyst rating or price-target changes in the last 30 days
- insider buying or selling in the last 90 days
Keep Bigdata.com calls to the flagged tickers. Do not research the whole universe.

STEP 3 - Classify the cause of each dip
Use the price data in context.json (move vs S&P 500 and vs sector ETF) plus the news:
- MARKET: the whole market fell and the stock fell with it, no company news
- SECTOR: its sector fell, the company itself is fine
- COMPANY: company-specific bad news (guidance cut, scandal, lawsuit, CEO exit, fraud)
- RESULTS: reaction to quarterly results
Decide:
- CANDIDATE: MARKET or SECTOR with quality pass; RESULTS only if the numbers were decent and the drop looks like an overreaction
- WATCH: quality is speculative, or the picture is mixed
- AVOID: COMPANY bad news, or quality fail
State your confidence (low, medium, high) and the single main reason.

STEP 4 - Report
For each CANDIDATE and WATCH ticker give, in at most 6 lines:
- ticker, name, mode (A long-term / B short-term), bucket, size bucket
- % below 52-week high and today's % change
- cause, decision, confidence, one-line reason
- stage (1, 2 or 3) and suggested limit price from context.json
- for mode B: target and stop prices
- RSI, valuation vs history, recovery history, next earnings date
Then list any sell, target, stop or review alerts on open positions.
End with one line on the market backdrop (S&P 500 move, VIX).

Run: python dip-watch/scripts/report.py to save the full report.
Post the short version to Slack channel #dip-watch.
Commit the new signals and report files to main.

RULES
- Facts only from context.json and Bigdata.com results. Never invent a number.
- If data is missing, say "data missing" rather than guessing.
- No duplicate alerts: context.json already removes repeats.
- Do not add investment-advice disclaimers; the user knows this is research.
- Keep the Slack message short; details go in the saved report.
```

## 6. Setup steps

1. **Build:** in Claude Code, open the market-brief repo and give it this brief. Ask it to build the module, write tests, run them, and run the backtest once.
2. **Config:** fill `revolut_available.yaml` with the tickers you've confirmed on Revolut, and check the thresholds in `rules.yaml`.
3. **Slack:** create a `#dip-watch` channel; the Slack connector is already connected.
4. **Environment:** reuse the existing market-brief cloud environment (allowlist already in place). Add any new domains the scripts need.
5. **Routine:** create a new routine at claude.ai/code/routines with `routine/PROMPT.md` as the prompt, this repo, that environment, the Bigdata.com and Slack connectors, and an hourly schedule on US trading days during market hours (15:30-22:00 Amsterdam time; adjust when daylight saving changes).
6. **First runs:** trigger it by hand a few times and check the output before relying on the schedule. Keep the old market-brief routines paused.

## 7. Tests and acceptance

- Unit tests with fixed sample data, no network: dip detection at each stage, Mode B trigger, earnings blackout, duplicate suppression, positions gain and sell alerts, and the stage logic when a stock is already past 25%.
- `scan.py` finishes in under 5 minutes for the full universe and writes `{"flagged": []}` on a quiet day.
- A quiet run posts nothing to Slack and commits nothing.
- The backtest prints its summary tables and its stated limits.
- Every number in a Slack alert traces back to `context.json` or a Bigdata.com result.

## 8. Trial phase

- Run 4-6 weeks without real money. Every signal is logged automatically.
- Score signals after 1 week and 1 month, and compare with the backtest.
- Track cost: Bigdata.com credit balance and tokens per run.
- Only then decide whether to act on signals with real money.

## 9. Known limits

- Nothing here predicts prices reliably; it collects data and applies rules for your own decision.
- A dip can deepen; staged buying and stops manage that, they don't prevent it.
- yfinance is unofficial and can break or lag; the routine minimum interval is 1 hour, so Revolut price alerts are the instant backup.
- The routine cannot post into the Claude chat. Results go to Slack and the repo, and Claude can read them from Slack when asked.

## 10. HTML report

The user wants every report as a rich, easy-to-read HTML page, not plain text.

- **Template:** reuse the existing `templates/` folder in market-brief if it holds a report template; otherwise create `dip-watch/templates/report.html.j2` (Jinja2). One self-contained file: inline CSS, no external scripts, works offline and on a phone.
- **Layout, top to bottom:**
  1. Header: run time (UTC and Amsterdam), market backdrop strip (S&P 500 move, Nasdaq, VIX, 10-year yield) with green/red colouring.
  2. Summary cards: number of candidates, watch, avoid, and open-position alerts.
  3. Candidates table: ticker, name, mode, cause, decision badge (colour-coded CANDIDATE / WATCH / AVOID), confidence, % below high, today's %, stage, limit price, target and stop, next earnings.
  4. One card per ticker: the one-line reason, key fundamentals, RSI, valuation vs history, recovery history, insider and analyst changes, and a small inline SVG sparkline of the last 60 days with the 52-week high marked.
  5. Open positions: entry price, current gain or loss, and any sell, target, stop or review alerts highlighted.
  6. Footer: data sources and the backtest hit rate for context.
- **Output:** `report.py` renders `reports/dip-watch/YYYY-MM-DD-HH.html` alongside the markdown file.
- **Delivery:** Slack can't render HTML, so the Slack message stays short and links to the HTML file. Either upload the HTML as a file to `#dip-watch`, or publish `reports/` with GitHub Pages and post the page link.
- **Tests:** render the template with fixed sample data and check it produces valid HTML with every section present, including the quiet-day case.
- Add to the routine prompt, STEP 4: after `report.py`, attach or link the HTML report in the Slack post.
