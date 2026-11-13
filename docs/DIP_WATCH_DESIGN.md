# Dip-Watch design

- **Version:** 1 (draft for ChatGPT's review)
- **Date:** 2026-11-13
- **Status:** not approved, and nothing is built. Building starts only after ChatGPT's review is settled and the
  owner approves (`CLAUDE.md`, "How to work with the owner and with ChatGPT").
- **Source:** the owner's brief, kept unchanged in [DIP_WATCH_BRIEF_ORIGINAL.md](DIP_WATCH_BRIEF_ORIGINAL.md). This
  design replaces it. The owner made 24 decisions in a question-by-question session with Claude on 2026-11-13.
  Appendix A lists each one with the options offered.

## 1. What it is

Dip-Watch is a separate research module in this repository. It finds US stocks that have fallen sharply and judges
the cause of each fall. It sends the owner a buy, watch or avoid suggestion, with a chart, by Telegram. It tracks the
trades the owner reports and alerts when to take profit or review a position.

Hard lines, unchanged from the rest of the project:
- research only;
- it never places orders and never connects to a broker;
- the owner decides every trade and every amount.

It does not set budgets, position sizes or a cash reserve (decision 2).

It is independent of the market-brief daily routines. Those are paused and stay paused. It reuses market-brief code
where that code fits:
- the paced Yahoo client `marketbrief/sources/yahoo_pacing.py`;
- the XNYS calendar `core/calendar.py`;
- the `#market-brief` conventions for gates and commits.

It does not touch `web/`, `api/` or `design/`, which are frozen.

## 2. One run, end to end

1. **Telegram commands.** Read any `/buy`, `/sell`, `/positions` and `/undo` messages to the bot, record the valid
   ones and reply to each (section 8).
2. **Market check.** If the XNYS calendar says the market is closed (holiday or weekend), stop here.
3. **Reference file.** On the first run of the day, build the daily reference file (section 3).
4. **Prices.** Fetch today's prices for the universe, plus the benchmarks: S&P 500, Nasdaq, VIX, the 10-year yield
   and the sector ETFs.
5. **Triggers.** Apply the Mode A and Mode B triggers (section 4) and drop repeats (section 4.4).
6. **Results window, ranking and quality.**
   - Look up the next results date for the flagged stocks only.
   - Rank the flagged stocks (section 6.3) and keep at most 10.
   - Run the quality check (section 5) on those stocks only.
7. **Position checks.** Check open positions for sell, target, stop and review alerts (section 8).
8. **Output.** Write a compact `work/context.json`. If nothing is flagged and no position has an alert, stop. Nothing
   is posted or committed, apart from Telegram entries and the reference file.
9. **Claude's part** (Sonnet 5.5):
   - researches the flagged stocks on Bigdata.com;
   - classifies each dip's cause and decides (section 6);
   - writes the decisions file.
10. **Report.** `report.py` builds the HTML and markdown reports and the chart images (section 9).
11. **Gate.** `validate.py` checks the output (section 10). There is one retry.
12. **Send and commit.** Send by Telegram, then commit and push to main.

## 3. Universe

- **Members** (decision 13):
  - US-listed stocks with a market cap of at least $1B and an average daily dollar volume of at least $20M (20-day);
  - plus the S&P 500;
  - plus `config/universe.yaml` (SPCX).
- **Foreign companies** listed in the US (ADRs) are included and labelled `foreign`.
- **Sources** (free):
  - the Nasdaq stock screener (one call, all US-listed stocks with market cap);
  - the S&P 500 list from Wikipedia.
- **Size on 2026-11-13** (measured, before the liquidity floor): 7,251 listed stocks; 2,679 at $1B or more; 967 at
  $10B or more.
- **Size buckets:**
  - mega: $200B or more;
  - large: $10B to $200B;
  - mid: $1B to $10B.
  - Under $10B carries the label `smaller company`. It is a label only, with no sizing (decision 2).
- **Weekly ticker list:** rebuilt every Monday's first run and committed. Columns: ticker, name, sector, industry,
  market cap, size bucket, foreign flag, sector ETF.
- **Daily reference file:** built on the first run of each trading day and committed (decision 13).
  - Columns: ticker, the 52-week closing high and its date, the average daily dollar volume, the liquidity pass, and
    the 50- and 200-day moving averages.
  - It holds no price history. Later runs that day fetch only today's prices.
- **Speed** (measured 2026-11-13): one year of daily bars for 100 tickers took 15.2 s in one batched Yahoo download.
  A linear estimate for 2,000+ tickers is about 5-7 minutes. That is why the daily reference file exists. The
  estimate and Yahoo's rate limits at full size are not yet tested.
- **Recent IPOs** (decision 6):
  - fewer than 252 sessions of history: the "high" is the highest close since listing;
  - label `recent IPO, < 1 year of history`;
  - missing data shows "data missing" and never fails the stock.
  - SPCX (Space Exploration Technologies Corp., Nasdaq) first traded about 2026-06-12. Yahoo showed a market cap of
    about $1.90T on 2026-11-12.

## 4. Signals

### 4.1 Mode A: long-term dip

- **Trigger:** the price is at least 15% below the 52-week closing high (decision 6 for IPOs).
- **Stages** (one third each, as a suggestion only; the owner decides amounts):

| Stage | Normal ladder | Already more than 25% down when first flagged (`deep dip`, decision 4) |
|---|---|---|
| 1 | 15% below the high | today's price |
| 2 | 20% below the high | a further 5% below the stage-1 price |
| 3 | 25% or more below the high | a further 10% below the stage-1 price |

### 4.2 Mode B: quick dip (decision 15)

- **Trigger:**
  - the S&P 500 is down at least 2% today at the run time, checked live each hour;
  - the stock is down at least 5% today;
  - its quality check is `pass`;
  - Claude classifies the cause as MARKET or SECTOR, not company news.
- **Exit,** measured from the owner's actual buy price:
  - target +7%;
  - stop −7%;
  - review after 7 trading days if neither is hit.
- Logged separately from Mode A. One stock can trigger both modes; both are shown.

### 4.3 Indicators shown

- % below the high and today's %;
- RSI(14);
- volume against its 20-day average;
- the 50- and 200-day moving averages;
- today's move against its sector ETF and the S&P 500.

Recovery history and 5-year valuation percentiles are dropped (decision 8).

### 4.4 No repeats (decision 5)

- Each stage alerts once per dip.
- A dip ends when the stock recovers to within 10% of its high. A later fall to 15% is a new dip.
- There are no automatic re-checks of stocks already flagged. Every report lists the open dips with their stage and
  the time since the alert.

## 5. Quality check (decision 12)

- **When it runs:** only for stocks that triggered. It uses Yahoo figures. Going-concern and negative-filing news
  comes from the Bigdata.com research.
- **Limits** (all in `rules.yaml`):

| Check | Pass | Speculative (label) | Fail (dropped) |
|---|---|---|---|
| Revenue, last 4 quarters vs the 4 before | growing | flat to −5% | below −5% |
| Operating margin | > 0% | ≤ 0% | — |
| Debt-to-equity | < 2.0 | ≥ 2.0 | — |
| Interest coverage (operating profit ÷ interest) | > 3× | 1.5-3× | < 1.5× |
| Going-concern warning | none | — | any |

- **Financials** (banks, insurers): the two debt checks show `n/a (financial)`.
- **Missing data** shows `data missing`. It does not fail the stock.
- **Evidence for these limits:** reasoning only. They are common rules of thumb, and the backtest cannot test them.

## 6. Research and judgement (Claude, flagged stocks only)

### 6.1 Bigdata.com calls per stock

- news and sentiment of the last 5 days;
- next results date;
- analyst rating and price-target changes of the last 30 days;
- insider buying and selling of the last 90 days;
- valuation (current multiples, and history where the company tearsheet gives it).

The credit cost per call is not yet measured. The trial measures it.

### 6.2 Cause and decision

- **Cause:**
  - MARKET: the market fell and the stock fell with it;
  - SECTOR: its sector fell;
  - COMPANY: company-specific bad news;
  - RESULTS: a reaction to quarterly results.
- **Decision:**
  - CANDIDATE: MARKET or SECTOR with quality `pass`, or RESULTS with decent numbers and an apparent overreaction;
  - WATCH: speculative quality, or a mixed picture;
  - AVOID: COMPANY bad news, or quality fail;
  - WAIT: results are due within 3 trading days (decision 9). Never a candidate.
- Each decision has a confidence (low, medium or high) and one main reason.
- **Facts rule:** every fact comes from `context.json` or a Bigdata.com result. Missing data is written as
  `data missing`.

### 6.3 Crash-day cap (decision 18)

- At most 10 stocks are researched per run.
- Python ranks the flagged stocks first, in this order:
  1. on the owner's Revolut list;
  2. quality `pass` before `speculative`;
  3. a larger fall relative to its sector ETF and the S&P 500;
  4. larger market cap.
- The rest are listed as `flagged, not researched (cap)` with their numbers.
- On a crash day the message starts with a headline, for example "Market down 3.4%; 143 stocks flagged; top 10
  researched."

### 6.4 Results window (decision 9)

- **Date source:** Yahoo, for flagged stocks only, checked by Bigdata.com. If the two differ, the earlier date
  counts.
- **Pre-results view:** within 3 trading days before results, Claude adds a lean (results likely good or weak), a
  confidence and a reason.
- The view is logged and scored after the results. After the trial, the data decides whether pre-results suggestions
  are allowed.

### 6.5 Labels on every alert

`speculative`, `smaller company`, `deep dip`, `recent IPO, < 1 year of history`, `foreign`, and
`on Revolut: confirmed` or `on Revolut: not confirmed, check the app`.

The Revolut list is a label, never a filter (decision 7). The owner confirms tickers and Claude adds them to
`config/revolut_available.yaml`.

## 7. Buy suggestion

- **Suggested limit price** (decision 16):
  - Mode A: 3% below the last price, standing until the next stage triggers;
  - Mode B: 1% below the last price, for the same day only.
- **Shown with each suggestion:** the stage, the limit price, the Mode B target and stop (from the limit price until
  the owner reports a buy), and the next results date.

## 8. Positions and Telegram commands

### 8.1 Commands (decision 14)

| Command | Meaning |
|---|---|
| `/buy TICKER SHARES PRICE [A\|B]` | a buy; the mode defaults to A; the stage is taken from the last alert, else `manual` |
| `/sell TICKER SHARES PRICE` | a sell |
| `/positions` | open positions with gain or loss before and after fees |
| `/undo` | cancels the owner's last entry (appends a cancelling row; nothing is deleted) |

- **Parsing:** Python parses the commands, never Claude. The format is strict, so nothing is guessed. A message in
  the wrong format gets a reply with the right format.
- **Who is accepted:** only messages from the owner's chat ID in the config. Messages from any other chat are
  ignored and logged.
- **Confirmation:** every entry gets a reply, for example "Recorded: bought 5 GOOGL at $289.74; average entry
  $289.74".
- **Storage:** `dip-watch/data/positions.csv` is append-only. Columns: id, recorded_at, ticker, mode, action, shares,
  price, stage, telegram_message_id, supersedes.
- **The 24-hour limit:** Telegram's `getUpdates` keeps messages for 24 hours. The trading runs (holidays included)
  and the weekend runs (section 11) cover every gap.

### 8.2 Alerts on open positions

- **Average entry:** gains are measured from the average entry price. A buy after a partial sell recomputes it, and
  the sell levels restart.
- **Mode A sells** (decision 3): suggest selling one third at +15%, one third at +20% and the rest at +30% or more.
- **Mode A review alerts** (decision 20). There is no automatic stop. A review alert is raised:
  - at −15% and −25% from the average entry;
  - immediately on company-specific bad news for a held stock, from a light Bigdata.com check once per trading day
    on held stocks only;
  - when a held stock's quality turns `fail`.
- **Mode B** (decision 15): target +7%, stop −7%, review after 7 trading days.

### 8.3 Costs (decision 17)

- The account is in USD, on the Revolut Metal plan.
- Each trade costs €1, converted at the stored `EURUSD=X` close. There is no currency conversion fee.
- Gains are shown before and after fees.
- The owner did not mention a free monthly allowance, so every trade is charged.

## 9. Delivery (decisions 10 and 24)

- **Channel:** Telegram, through the owner's bot to the owner's private chat. The bot token comes only from the
  environment variable `TELEGRAM_BOT_TOKEN` and is never printed. The chat ID is in the config.
  - Delivery was verified on 2026-11-13 with a test message.
  - The host `api.telegram.org` is reachable.
- **Slack:** not used, because the Slack connector posts as the owner, who gets no notification for their own
  messages.
- **Per run with findings:**
  1. A short message: one line per candidate (ticker, dip %, cause, decision, stage, limit price), any position
     alerts, and one line on the market.
  2. One chart image per candidate: 60 days of closes, the 52-week high, the 15/20/25% stage lines and the limit
     price.
  3. The HTML report as a file.
- **HTML report:** `reports/dip-watch/YYYY-MM-DD-HH.html`, beside a markdown copy. It is one self-contained file
  (inline CSS, no scripts, works offline and on a phone, light and dark). Sections, top to bottom:
  1. run time (UTC and Amsterdam) and a market strip (S&P 500, Nasdaq, VIX, 10-year yield);
  2. summary cards (candidates, watch, avoid, wait, not researched, position alerts);
  3. the candidates table;
  4. one card per researched stock (reason, quality, RSI, valuation, sentiment, analyst and insider changes,
     pre-results view, chart);
  5. positions;
  6. footer: sources, the backtest headline and the latest scorecard line.
- **Template:** `dip-watch/templates/report.html.j2` (Jinja2). The repository's `templates/` holds only `report.md`.

## 10. Storage and commits (decisions 8 and 23)

- **Stored** (all append-only, UTC):
  - positions;
  - the results: every signal and decision, `dip-watch/data/signals/YYYY/MM/YYYY-MM-DD.jsonl`, plus the reports;
  - the weekly ticker list and the daily reference file;
  - the weekly scorecard;
  - the backtest summary.
- **Not stored:** price history, fundamentals and Bigdata.com raw results. They are fetched fresh each run. The
  decisions file keeps only the facts the report cites, each with its Bigdata.com document id or URL for tracing.
- **Gate:** `dip-watch/scripts/validate.py` runs before every commit. It checks:
  - every number in the report and the Telegram message appears in `context.json` or the recorded research facts;
  - decisions and causes are from the allowed lists, each with a confidence and a reason;
  - files are appended, never rewritten;
  - timestamps are UTC.
- **On failure:**
  - one retry;
  - if it fails again, a short Telegram notice, the output under `dip-watch/rejected/`, and nothing sent as an
    alert.
- **Commits:** straight to main, pushed at once, like the market-brief daily runs. A quiet run commits only Telegram
  entries and the reference files.

## 11. Schedule, model and cost (decisions 19 and 21)

- **Trading runs:** Monday-Friday at 9:35, 10:35, ..., 15:35 New York time, 7 runs, using
  `CRON_TZ=America/New_York`, so daylight saving is automatic. On US holidays the runs only read Telegram.
- **Weekend runs:** Saturday and Sunday at 12:35 New York time, for Telegram commands only. Saturday's run also
  sends the weekly scorecard.
- **Model:** Sonnet 5.5, with Opus 5.5 as the fallback if the trial shows weak classifications.
- **Cost:** every routine run starts a Claude session, so even a quiet run costs a few tokens. The trial measures
  tokens and Bigdata.com credits per run. If the weekend runs prove costly, they could move to a free GitHub Actions
  job, which needs the token as a repository secret.

## 12. Backtest (decision 11)

- **How it runs:** a manual tool, never in the routine. It runs once before the trial, on the S&P 500 first.
- **What it does:** replays the Mode A and Mode B price rules over 3 years of daily Yahoo history. The history is
  fetched, not stored.
- **For each past signal it records:**
  - the return after 5, 10, 20 and 60 sessions;
  - the maximum drawdown;
  - whether the target or the stop came first.
- **Output:** summary tables by mode, size bucket and sector (hit rate, median, worst case, days to target). Only the
  summary is saved.
- **Stated limits:**
  - price rules only, not Claude's judgement;
  - today's universe, so survivorship bias overstates results;
  - no quality filter in the past.

## 13. Trial and the bar for real money (decision 22)

- **Length:** 4-6 weeks with no real money. The owner may still report trades for tracking.
- **Weekly scorecard** (Saturday; computed by Python, with no Bigdata.com cost):
  1. CANDIDATE returns after 5 and 20 sessions from the suggested limit price (or the last price if the limit never
     filled), against the S&P 500;
  2. the same for WATCH and AVOID, to check whether avoided stocks did worse;
  3. Mode B: target first or stop first;
  4. pre-results views: right or wrong;
  5. tokens and credits per run.
- **Bar for real money, fixed now:** both conditions must hold. Otherwise, extend the trial or change the rules.
  1. at least 30 scored candidates;
  2. the CANDIDATEs' 20-session median return beats both the S&P 500 and the backtest's plain price-rule result over
     the same windows.

## 14. Configuration (`dip-watch/config/rules.yaml`; no threshold in code)

| Key | Value |
|---|---|
| `universe.min_market_cap_usd` | 1e9 |
| `universe.min_avg_dollar_volume_usd` | 20e6 (20-day) |
| `mode_a.stages_pct_below_high` | [15, 20, 25] |
| `mode_a.deep_dip_further_drops_pct` | [5, 10] |
| `mode_a.reset_within_pct_of_high` | 10 |
| `mode_a.sell_levels_pct` | [15, 20, 30], one third each |
| `mode_a.review_loss_pct` | [15, 25] |
| `mode_b.spx_drop_pct` | 2 |
| `mode_b.stock_drop_pct` | 5 |
| `mode_b.target_pct` / `stop_pct` / `review_sessions` | 7 / 7 / 7 |
| `limit_below_last_pct` | A: 3, B: 1 |
| `results_window_sessions` | 3 |
| `research_cap_per_run` | 10 |
| `quality.*` | the table in section 5 |
| `costs.fee_per_trade_eur` | 1 |
| `delivery.telegram_chat_id` | the owner's chat |

`config/universe.yaml` holds extra tickers (SPCX). `config/revolut_available.yaml` holds the confirmed tickers.

## 15. Layout

```
dip-watch/
  config/      rules.yaml, universe.yaml, revolut_available.yaml
  data/        positions.csv, signals/YYYY/MM/*.jsonl, universe/, reference/, scorecards/, backtest/
  scripts/     build_universe.py, fetch_prices.py, indicators.py, quality.py, scan.py, positions.py,
               telegram_io.py, backtest.py, report.py, scorecard.py, validate.py
  templates/   report.html.j2
  routine/     PROMPT.md
  tests/
  README.md
reports/dip-watch/   YYYY-MM-DD-HH.html|md
```

## 16. Tests and acceptance

- **Offline unit tests** on fixed data:
  - each stage, the deep-dip ladder, the dip reset and no repeats;
  - the Mode B trigger;
  - the results window;
  - the crash-day ranking and cap;
  - the quality limits, including financials and missing data;
  - average entry, sell levels, review alerts and fees;
  - Telegram parsing (valid, invalid, other chat, `/undo`);
  - every gate check;
  - the HTML report with every section, including the quiet case.
- **Speed:** a full-universe scan within 5 minutes on a normal run, measured. The first run of the day, which builds
  the reference file, is measured separately.
- **Quiet run:** sends nothing and commits only Telegram entries and the reference files.
- **Backtest:** prints its tables and limits.
- **Traceability:** every number in a Telegram message traces to `context.json` or a recorded Bigdata.com fact.
- **Judge:** the judge reviews the build before it reaches main (`CLAUDE.md`).

## 17. Evidence and risks

- **Mode A goes against a documented effect** (strong evidence). George and Hwang (2004, *Journal of Finance*, "The
  52-Week High and Momentum Investing") found that stocks near their 52-week high beat those far below it. Momentum
  (Jegadeesh and Titman 1993) points the same way. Mode A must show its worth in the backtest and the trial.
- **Mode B is close to short-term reversal** (strong evidence that the effect existed; some evidence that it
  survives costs in large caps today). Sources: Lehmann 1990, *QJE*; Jegadeesh 1990, *Journal of Finance*.
- **Buying after results beats guessing results** (strong evidence for the drift; weaker in large caps lately).
  Post-earnings drift: Ball and Brown 1968; Bernard and Thomas 1989. Hence the WAIT rule and the scored pre-results
  view.
- **This repository's own record:** market-brief's signal model showed no tradable skill in a 15-year test
  (`docs/DESIGN.md` section 15.1).
- **Other risks:**
  - Yahoo is unofficial and can break or rate-limit.
  - Hourly runs catch a dip within about an hour; Revolut's own price alerts are the instant backup.
  - 30 candidates is a rough minimum, not proof.
  - The quality limits are untested rules of thumb.

## 18. Open points

1. **Paper versus real entries during the trial.** The trial is "no real money", but the owner may report trades.
   Should `/buy` entries carry a `paper` or `real` mark, so the trial's tracked positions stay apart from real ones
   later? This is raised with the owner. It is not decided here.
2. **Bigdata.com credits per call and per run:** unknown until measured.
3. **Full-universe Yahoo speed and rate limits** at 2,000+ tickers: not yet measured.

## Appendix A: Decision register (owner, 2026-11-13)

Option A was Claude's recommendation for every question. The owner chose it each time, sometimes after changing the
question.

| # | Question | Options offered | Chosen |
|---|---|---|---|
| 1 | Process | A brief approved, judge-reviewed; B ChatGPT first; C no judge | Close all questions, write the final design, ChatGPT review, owner approval, then build; judge applies |
| 2 | Money and sizing | caps, reserve, budget per mode | No budgets, caps or reserve; suggestions only; the owner decides amounts; speculative and size are labels |
| 3 | Sell alerts | A one third at +15/+20/+30; B level only; C single exit | A, from the average entry |
| 4 | Ladder when already more than 25% down | A further 5% and 10%; B 10% and 20%; C no ladder | A, plus a `deep dip` label |
| 5 | Repeats | A once per stage per dip; B weekly reminder; C every 24 h | A; reset within 10% of the high; no automatic re-checks |
| 6 | Recent IPOs | A high since listing; B after 3 months; C exclude | A |
| 7 | Revolut list | A label; B hard filter; C filter with a seed list | A |
| 8 | Valuation history and storage | A flagged only; B weekly full; C drop | Store only positions, results and ticker lists; prices fetched fresh; Bigdata.com for flagged stocks; recovery history and 5-year percentiles dropped; no Google Drive (market-brief does not use it) |
| 9 | Results blackout | A WAIT label; B hide; C warning only | A, plus a scored pre-results view (owner's idea) |
| 10 | Delivery | Slack options | Telegram bot to the owner's private chat; Slack dropped |
| 11 | Backtest | A manual tool; B drop; C monthly | A |
| 12 | Quality check | A flagged stocks only, with these limits; B other limits; C label only | A |
| 13 | Universe | A $1B and $20M with ADRs; B US only; C higher floor | A, plus the daily reference file |
| 14 | Recording trades | A Telegram commands with weekend runs; B trading hours only; C chat or GitHub | A |
| 15 | Mode B numbers | A +7/−7/7 sessions, live trigger; B two-step exit; C close-only trigger | A |
| 16 | Limit price | A 3% for A, 1% for B; B 3% for both; C none | A |
| 17 | Fees | A fees in config; B gross only; C later | A: USD account, Metal, €1 per trade, no FX fee |
| 18 | Crash-day cap | A 10 per run, ranked; B 5 or 20; C no cap | A |
| 19 | Schedule | A New York time, 7 runs plus weekends; B 4 runs; C Amsterdam by hand | A |
| 20 | Mode A downside | A review alerts; B hard stop; C none | A |
| 21 | Model | A Sonnet 5.5; B Opus 5.5; C mixed | A |
| 22 | Trial bar | A scorecard plus a fixed bar; B no bar; C stricter | A |
| 23 | Commits | A gate, then main; B data branch; C no gate | A |
| 24 | HTML report | A adjusted layout; B changes; C no HTML | A |
