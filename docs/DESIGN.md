# market-brief design (v2)

Agreed design for extending market-brief with the core ideas of PASDS
(github.com/exepex/ai-stock-prediction), run entirely by Claude Code cloud routines.
Research only: no trading, no broker connections, not investment advice.

## 1. Goal
Before each market opens, publish for every watched company:
- a **predicted price range** for the next trading day (T+1) and 5 trading days ahead (T+5),
- a **direction and confidence**,
- **yesterday's range scored** as hit or miss,

plus one chart per company and one Slack message per market. The aim is a *correct range*
(right width, honestly calibrated), not an exact price.

## 2. Markets and schedule
Two routines, scheduled in the exchange's own timezone so daylight saving never shifts them.

| Routine | Cron (exchange time) | Brief ready | Benchmark / regime |
|---|---|---|---|
| India (NSE) | `CRON_TZ=Asia/Kolkata 10 8 * * 1-5` (08:10 IST) | ~08:40 IST, before the 08:45 block window and 09:00 pre-open | NIFTY 50 (`^NSEI`), India VIX (`^INDIAVIX`) |
| US (NYSE/Nasdaq) | `CRON_TZ=America/New_York 15 8 * * 1-5` (08:15 ET) | ~08:45 ET (~14:45 Amsterdam) | SPY, VIX (`^VIX`) |

- Exchange holidays: post a one-line "market closed" message and skip predictions.
- Late runs (`market_status.py` `late_run`: started after the session's close): no calls;
  `ranges.py` skips ranges whose target session has closed, labels the others late (never
  scored) and ignores cues quoted after that session's open.
- Mid-session runs (`in_session`: started after the session's open, before its close): no calls
  and no 1-day ranges; 5-day ranges are published for the record, noted late, never scored (the
  day is partly known, and every horizon covers it). Any range or call made at or after the open
  of the first session it covers is never scored, and cues and option snapshots quoted after
  that open are ignored for every horizon (an intraday quote is not an overnight cue).
- US macro data at 08:30 ET (CPI, jobs): on those days the brief states "call made before release".
- Priority: India (where capital is) first, US as a small trial. Paper only for weeks 1-6.

## 3. Inputs (all free)
**Per company:** daily OHLCV (yfinance), news (RSS), earnings and ex-dividend dates.
**US filings:** SEC EDGAR (already built). India filings: from news at first.
A ticker's SEC filings are read from the CIK in SEC's ticker map plus any earlier or related
registrant still filing for it (`fundamentals.predecessor_ciks`; XOM maps to ExxonMobil Holdings
2115436 since 2026-07-01, while Exxon Mobil Corp 34088 still lists filings: an 8-K on 2026-07-01, the
Q2 10-Q jointly, Form 4s, a 13G, and the item 2.02 results releases up to May 2026), merged and
de-duplicated by accession number in `sec.ticker_submissions` (issue #23).

| Signal | US | India |
|---|---|---|
| Overnight / pre-open cue | Index futures `ES=F`, `NQ=F`; per-stock pre-market gap | Previous US close, Nikkei `^N225`, Hang Seng `^HSI`, US ADRs (`INFY`, `HDB`, `IBN`, `WIT`) |
| Implied volatility | Option chains (yfinance): ATM IV, implied earnings move | India VIX (index level only) |
| Global factors | US 10Y `^TNX`, dollar `DX-Y.NYB`, crude `CL=F`, gold `GC=F` | Same, plus USD/INR `INR=X` |
| Flows | FINRA short-sale volume and short interest; Cboe put/call ratios | NSE FII/DII provisional flows; NSDL FPI investment (equity, debt) |
| Macro | Treasury par yield curve (10y-2y, 10y-3m), FRED high-yield and IG credit spreads, 10y breakeven | NSE index closes with P/E, P/B, dividend yield; Nifty 10y G-Sec index |
| Sectors | One ETF per watchlist sector (10): eight SPDR sector ETFs, JETS (airlines), IAK (insurance) | Nifty Bank, IT and Pharma indices (none for the other seven sectors; see `config/markets/india.yaml`) |
| News sources | Google News (US), CNBC, BBC; PR Newswire, Business Wire earnings and GlobeNewswire releases (watchlist names only) | Google News (IN), Economic Times, Moneycontrol, Livemint, Business Standard, BusinessLine |

**News ticker tags** (`scripts/news_tags.py`, issues #28/#29): headline first. A ticker is
tagged when one of its `news_names` (default `name` + `aliases`; full names or unambiguous
aliases such as "M&M", "L&T", "NVDA") occurs as a whole word, case-insensitively, in the TITLE,
after the ticker's `news_exclude` phrases are removed ("Kotak Mahindra", "Tech Mahindra" for M&M;
"ITC Hotels"; "Chevron deference"). Only when the title names no watchlist company is the
plain-text summary used (HTML, URLs/domains and the outlet name removed: every Google News
summary is a `news.google.com` link, which used to tag nearly everything GOOGL). Roles:
`primary_tickers` = companies named in the title (all of them when several), except in a
comparison ("X vs Y") or a list ("TCS, Infosys and Wipro ...", "Stocks to watch: A, B, C";
commas or slashes, not ";"), where they are `mentioned_tickers`, as is a company found only in
the summary, and a company acting on or holding another one (`Tagger.is_actor`): analyst
actions ("JPMorgan cuts target for Aon", "target raised by JPMorgan", "Bank of America upgrades
DraftKings"), holdings ("shares of X bought by Bank of America Corp", "takes stake in"), venues
("present at Bank of America 2026 conference", "Bank of America Plaza"); tickers with
`broker: true` (JPM, BAC) also as research arms, commentators ("JPMorgan sees", "says
JPMorgan") and in their own picks or views ("JPMorgan's October stock picks"). Names also match
as `(TICKER)`, `(TICKER:EXCH)` or `(EXCH: TICKER)`, case-sensitive.
`tag_confidence` is high only for a title naming exactly one company as primary, low for every
other tagged item: the hook for a later LLM aboutness check by the news-analyst (not built);
`news_ticker_day` carries `role` and `tag_confidence`, and the context pack's news table counts
`primary_7d` and `low_conf_7d`. A Google News query for a company only finds candidates: its
results include market wraps and politics that never name the company, so the hit alone does
not tag. Press-release wires match `wire_names` the same way. Identity: normalized title +
the RSS `<source url>` domain, so "Business Today" and "businesstoday.in" copies of one article
are one item (ids stored before that are still recognised as seen). Rows carry `tag_version`;
because `tickers` is derived and `data/` is append-only, older rows are re-tagged on read: the
stored rows are the DuckDB view `news_stored`, and `news` (used by `news_ticker_day`, the context
pack, graph hits, view_data and the Neo4j copy) applies `news_retag` (registered in
`common.connect`): stored title with the current rules (old wire rows whose title names no
company keep their stored tags as mentioned, low). Old outlet rows lose tags found only in their
summary (not stored). The Neo4j copy needs `neo4j_sync.py --full` once
to drop mention edges synced before the fix.

**Event calendar:** earnings, ex-dividend, F&O expiry, Fed/FOMC, RBI policy, CPI/jobs releases,
index rebalances (S&P 500 quarterly, Nifty 50 semi-annual; listed, not major).

**PASDS indicators (Python):** returns 1/3/5/20d, EMA(9)/EMA(21) ratio, RSI(14), ROC(10),
price vs 20-day high, ATR(14), 10-day realized vol, Bollinger width, OBV trend, volume ratio.
**Regime:** Calm / Trending / Event-heavy / Unstable from VIX, index 5-day return and volatility,
and the event calendar.

## 4. How a range is built (deterministic Python)
1. **Width:** current volatility estimate = blend of exponentially weighted realized vol and,
   where available, implied vol. Range = quantiles of recent standardized returns scaled by that
   volatility, for T+1 and T+5. Two bands: 50% and 80%.
2. **Market + stock split:** predict the index range first; stock = beta x index move + its own
   residual (beta from the last year of daily returns).
3. **Centre:** last close adjusted by the overnight cue (futures, ADRs, pre-market gap), minus any
   dividend going ex, plus a small capped drift from the signal score and the AI's direction.
4. **Events:** on earnings days use the options-implied move (US) or the stock's past earnings-day
   moves; widen on F&O expiry and central-bank days.
5. **Self-calibration:** track live coverage over the last ~60 scored ranges per market and band.
   If the 80% band hits less than 80%, widen it; if it hits clearly more, narrow it.

## 5. Role of the AI agents
- **news-analyst:** classifies news with the PASDS scheme: sentiment, relevance, novelty, event
  type (earnings, macro, product, legal, sector, analyst, M&A), urgency, geopolitical risk,
  priced-in flag.
- **bull-researcher / bear-researcher:** thesis and anti-thesis per company.
- **forecaster:** direction and confidence (0.50-0.90), or abstain. It may shift the centre
  within a capped amount and may **widen** a range for an event it read about, but may never
  **narrow** a range below the formula. All numbers come from scripts, never from memory.

## 6. Scoring (the judge)
| What | Metric | Must beat |
|---|---|---|
| Range | Coverage (hit rate vs 50%/80% target) and average width (interval score) | Naive range: last close +/- recent typical move |
| Direction | Hit rate | "No change" and "always up" |
| Confidence | Calibration by band (70% calls should hit ~70%) | Coin flip |

Reported per market, per horizon, per regime, and over rolling 30-day and since-start windows.

## 7. Testing approach
| Part | How it is tested |
|---|---|
| Range formulas (no AI) | Walk-forward backtest on the **last 1-2 years only**, recent days weighted more; each step sees only data up to that date. Sets starting parameters. An input is kept only if it improves range accuracy. |
| AI judgement | **Live forward testing only.** Never backtested, because the model may have seen past outcomes during training. |
| Verdict | Live results after 4-6 weeks (several hundred scored ranges). Weekly review (`review.py`) proposes parameter changes; a human applies them. |

**Historical replay** (`scripts/replay.py --market india|us [--start --end]`): before going live,
everything rule-based is replayed walk-forward over all stored bars, one as-of day d at a time,
with only what `ranges.py` would know pre-open the next session (bars up to d's close; earnings
versions by the 10-Q/10-K reports accepted by that session date; dividends; major events).
- Ranges: 1d and 5d 50%/80% bands built as `ranges.py` builds them (calibrate.py's pool quantiles
  at d, EWMA sigma, earnings/regime/major-event widening, the inputs `config/ranges.yaml` switches
  on, centre cap, ex-dividend shift), reusing `rangelib`, `range_inputs` and `backtest` helpers.
  Scored on the close h bars later: coverage overall and by regime, sector, ticker, month, year,
  earnings and major event in horizon; interval score and width vs the naive range; calibration
  (stated vs actual coverage, the two published bands plus other levels of the same pool).
- Regime per day (`regime.classify` on the vol index and benchmark closes, as `features.py`).
- Direction baselines, labelled as such (the forecaster must beat them live): always-up, 1d and
  5d momentum sign, RSI(14) mean reversion (below 30 up, above 70 down; `indicators.py` has no
  signal of its own). Hit rate, 95% interval clustered by date blocks, exact binomial test vs 50%,
  difference vs always-up on the same rows.
- Not replayable, so left out and listed in the report: AI drift and widening, own-stock overnight
  cues (no pre-market/ADR history; the next open would be look-ahead), the US futures index cue,
  implied vol, live ranges in the calibration pool, pre-open vol quotes. India's index cue (S&P 500
  previous close x fitted beta) is replayed. Past event dates count as known in advance.
- Output: a self-contained, novice-first HTML page (three plain sentences answering "do the ranges
  keep their promise?", "where are they too wide or too narrow?" and "do simple up/down rules
  work?", four big numbers, three captioned charts; every table, the full findings and the method
  in collapsed sections) and the full results as JSON in `reports/<market>/replay-<end>.*`, plus
  one append-only row in `data/<market>/replays/` (schema `replays`). Tests
  (`tests/test_replay.py`): equal to `ranges.py` on a sample day (with and without India's
  fitted index-cue beta split), unchanged when data after d is perturbed, baseline statistics on
  synthetic series. About 22 s per market for five years of bars.

**AI replay harness** (`scripts/ai_replay.py`): the table above keeps AI judgement out of backtests
because the model may have seen past outcomes. Days after its training data (as-of dates after
2026-06-30) are a fair test, so the agents can be replayed there, strictly as of the day. The
script is deterministic and never runs an LLM; the orchestrating session runs the agents.
- `dates --market M`: the sample, every 5th exchange trading day from 2026-07-01 to 2026-09-25
  (13 per market), each with its next session and cutoff.
- `backfill --market M --source S --since 2026-06-01`: S is a scratch source root (the repo, its
  `data/`, anything inside or above them, or another checkout's `data/` are refused). It copies
  `data/<M>/` and `config/` to S, lengthens the lookbacks in S's config only (US:
  `filing_lookback_days`, `relationships.insiders|stakes.lookback_days`), and runs the existing
  collectors into S one after another (SEC: one throttled client per collector, `SEC_USER_AGENT`;
  NSE: one paced session per collector): US `collect_filings`, `collect_insiders`, `collect_stakes`,
  `collect_events`; India `collect_nse_india --only announcements --only financials --since`,
  `collect_relations_india --only insiders --only deals --since`, `collect_events`. The NSE
  collectors' `--since` (new; default behaviour unchanged) asks the announcement and PIT indexes one
  week at a time, polls every ticker's results filings broadcast since then, and sets the per-ticker
  deals backfill. Rows keep their real publication/acceptance times (`first_seen_at` = the
  backfill time), which is what `prepare` filters on. Summary in `S/backfill-<M>.json`.
- `prepare --market M --date D --root R [--source S]`: cutoff = the routine's start on the session after D
  (08:15 ET, 08:10 IST; section 2). R gets copies of `config/`, `sql/`, `templates/` and
  `data/<M>/` with only rows public by the cutoff: bars dated <= D; SEC rows by acceptance time
  (else the end of the filing date, as the `fundamentals_*_asof` macros), NSE rows by publication
  time; events first seen by the cutoff plus backfilled past events dated <= D; predictions,
  ranges, outcomes and snapshots by their own made/scored/computed time; bulk/block deals by trade
  date <= D (assumed: NSE publishes them after the close; listed under `assumptions`); kinds with
  only an observation date (macro, shorts, FPI, indices, flows, delivery) only if first seen by the
  cutoff. Upcoming earnings: only rows first seen by the cutoff count. `--assume-earnings-known DAYS`
  (off by default) adds the actual earnings dates within DAYS after D as events labelled "ASSUMED
  known in advance", as `replay.py` treats past event dates; stored rows never say when a date was
  announced. News is dropped (stored news starts with live collection), and so are `summaries/` and
  `reports/`. Then `features`, `calibrate`, `context` (`R/work/context.md`, plus a list of the
  citable filing/announcement ids) and `ranges` run with `MB_ROOT=R` and `MB_NOW` = the cutoff:
  `common.clock()` freezes every "now"/"today" and `connect()` rewrites DuckDB's `current_date`.
  A JSON summary lists every kind kept or dropped and the context pack's size.
- `record`: validates forecaster records (schema `predictions`, id format, as_of_date = D,
  horizon 1/5, confidence 0.50-0.90, `range_widen` <= 0.5, rationale <= 40 words, evidence ids
  present in R's news/filings/announcements, no BLOCKED ticker, no `days_to_earnings` <= 1 in R)
  and appends the valid ones to `<results>/<M>/calls.jsonl` (`replay: true`, `made_at` = cutoff),
  never to `data/`; each day once.
- `score`: on the real stored closes (hit as `score_predictions.py`): hit rate by horizon and
  confidence band with Wilson 95% intervals and an exact binomial test, stated vs actual
  confidence, always-up and `replay.py`'s rule baselines on the same ticker-days, abstention rate;
  a novice-first HTML page (three sentences, four numbers, two charts, details collapsed) and JSON.
- Tests (`tests/test_ai_replay.py`): perturbing every row after the cutoff leaves the context pack,
  ranges, indicators, regime and calibration byte-identical (changing D's close does not);
  record's rejections; scoring on synthetic series; the date list; `prepare --source`; the
  earnings assumption is opt-in and labelled; `backfill` refuses the repo and any real `data/`
  and changes only the scratch config; the NSE collectors' `--since` (weekly windows, deals
  backfill) and their unchanged default (one call over the configured lookback).
- Evidence: the repo's own data has zero citable ids on every sample day (stored SEC filings start
  2026-09-28, news 2026-10-02/04, no NSE announcements), so replays read a `backfill` source. With
  `--since 2026-06-01` (run 2026-10-05) every sample day has 36-94 citable SEC filing ids (US, mostly
  Form 4) and 89-186 NSE announcement ids (India) public in the 14 days before the cutoff.
- Upcoming earnings, honestly as of D: none of the stored sources says when a date was announced.
  yfinance (upcoming and past dates), SEC 8-K item 2.02 and NSE results filings give the actual
  release dates, known only once they happen; NSE board-meeting intimations are a separate NSE feed
  that is not collected, and only a few announcements (earnings-call intimations) mention a coming
  results date in their text. In strict mode `days_to_earnings` is therefore empty on every sample
  day; `--assume-earnings-known 14` fills it from the actual dates, labelled as an assumption. There
  is also no stored history of overnight quotes.

## 8. Output
Processing data and presentation are separate. Processing data is what the next run reads:
append-only JSONL under `data/`, the context pack and the summaries; presentation never writes
to it. Presentation is for a novice reader: clean, single-purpose, not verbose. `view_data.py`
reads the stored data once into a "view" that both the HTML and the chart images use, so they
always show the same numbers.
- `reports/<market>/YYYY-MM-DD.md`: the agent-editable source (`report.py` skeleton, agents fill
  the `AGENT` markers): yesterday (market and each stock, calls scored), top 3, today (table:
  ticker, T+1 and T+5 ranges, direction, confidence), tomorrow/week (events and risks), sector
  notes with bull and bear, track record tables, data quality.
- `reports/<market>/YYYY-MM-DD.html` (`html_report.py`, after the judge passes the md): one
  self-contained file (inline CSS/JS, data embedded as JSON, light and dark, phone-friendly).
  A short summary (market mood in plain words, top 3, number of calls, data-quality warnings and
  a "How to read this" glossary collapsed); one filter row (all companies, a sector, or one
  company by search/select); then per company: price range and time period ("by Fri 9 Oct"),
  "80% chance between X and Y" and the 50% band, the call or "no call", its track record ("not
  enough history yet" below 10 checked cases) and the reasons (cited evidence and recent news
  as headline links, upcoming earnings/ex-dividend/market events, the sector's bull and bear
  points). Late ranges are labelled "late, not a forecast" and never phrased as a chance.
  Charts, each single-purpose and drawn as inline SVG: a price-and-fan chart per company (one
  % scale shared by every company), a range-per-company chart, a sector-move bar chart and a
  promised-vs-actual track-record chart once something was scored. `index.html` lists all days.
- **Chart images** (`charts.py`, PNG): `ranges.png`, `sectors.png` and `track_record.png` (when
  scored data exists), the same views as the HTML charts, embedded in the md and posted to Slack.
  The old per-company PNGs and the overview collage are no longer drawn.
- **Slack:** one thread per market per day: a short summary (mood, top 3, number of calls,
  yesterday's score, link to the HTML), then the chart images as one reply and the HTML file as
  another (bot token, `files.getUploadURLExternal` / `files.completeUploadExternal`). Without a
  bot token the summary is posted alone through the webhook. Nothing else is posted.

## 9. Repo changes needed
- `config/markets.yaml` (exchange, timezone, benchmark, regime index, holidays) and per-market
  watchlists.
- Data partitioned by market: `data/<market>/<kind>/YYYY/MM/...`.
- New scripts: indicators, regime, events calendar, ranges, calibration, charts, backtest.
- Routine prompt takes a `MARKET` parameter; two routines share the same code.
- Cloud environment: allow the extra news, Yahoo and calendar domains.

## 10. Build phases
1. Markets config, extra inputs, PASDS indicators, regime, event calendar. **(built)**
2. Range engine, self-calibration, scoring against baselines; backtest of range formulas. **(built)**
3. Charts, new report layout, Slack message, two routines. **(built; routines to be created once the
   environment's network access is set)**
4. Weekly review: what improved coverage, what to drop. **(built: `scripts/review.py`, run by the
   routine on the first trading day of each ISO week)** Coverage, interval score and width vs
   naive by window (week, 30 days, since start), horizon, regime, sector and widening note;
   call hit rate vs always-up and by confidence band; ablation of each range input by replaying
   the stored live ranges (cue, AI drift and widening, earnings/event/regime widening, centre
   cap) and walk-forward on stored prices (width parameters, regime and event widening).
   Below the minimum n in `config/review.yaml` it flags and proposes nothing. Proposed
   `config/ranges.yaml` changes go in `reports/<market>/review-YYYY-Www.md`; a human applies them.
5. Relationships (knowledge graph, public data only): insider trades (US Form 4, India SEBI
   disclosures), big-investor stakes (US 13D/13G, India bulk and block deals), holdings (US
   13F, India shareholding incl. promoter pledges), and a per-company connection map (board,
   group companies, suppliers, customers, competitors) refreshed monthly. Used for
   second-order news, smart-money signals and range-widening risk flags.
   - **India (built; live since 2026-10-05):** `collect_relations_india.py` reads NSE's
     public JSON (SEBI PIT disclosures, bulk/block deals with snapshot and archive-CSV fallbacks,
     shareholding master and pledge data) into `data/india/insiders|deals|holdings/`. Needs
     `www.nseindia.com` and `nsearchives.nseindia.com` allowed in the cloud environment.
     `relations.py` turns them into context-pack risk flags (deal >= INR 250 cr or 0.5x 20-day
     volume, promoter pledge +1 pp q/q, new or invoked pledges, insider sales >= INR 10 cr);
     the range widening from these flags is in `config/ranges.yaml` and off until the weekly
     review shows flagged tickers miss more often.
   - **India primary sources (built 2026-10-05):** `collect_nse_india.py` stores NSE
     announcements (scored by the news-analyst as primary sources), Integrated Filing results
     (quarter, half year, nine months, year; standalone and consolidated; Ind AS, banking and
     life-insurance taxonomies), FII/DII provisional flows and delivery % into
     `data/india/announcements|financials|flows|delivery/`; `nse_context.py` adds them to the
     context pack. The news-analyst's scores for announcements (news_enriched rows with
     `nse-ann-` ids) feed its brief and the `announcements_enriched` view, which the context
     pack's announcement section shows (sentiment, materiality). Delivery % is context only,
     not yet an indicator column.
   - **Connection map, both markets (built):** edges in `data/<market>/graph/` written monthly by
     the graph-builder agent through `graph.py add` (validated, each citing a source URL;
     each monthly attempt recorded in `graph_runs/` so an empty run is not repeated daily;
     retractions are new rows). `graph.py hits` finds second-order news for the context pack
     and the news-analyst.
   **US relationships built:** Form 4 insider trades, 13D/13G stakes and 13F holdings of 23
   tracked filers (`collect_insiders|stakes|holdings.py`), smart-money views and context
   section, and a fresh-13D note on ranges (widen gated in `config/ranges.yaml`, off).
6. Fundamentals (US built; India from NSE results, separate collector): quarterly, half-yearly
   (H1 year to date) and annual 10-Q/10-K values from SEC's free XBRL company facts API
   (`collect_fundamentals.py`, daily; downloads only when a new 10-Q/10-K is listed). Standard
   concepts are read from a short priority list of us-gaap/dei tags per concept; a value is stored
   once per filing that first reports it or changes it, so restatements and split adjustments
   are new rows and the views take the newest filing. Fiscal Q4 (rarely tagged) is derived as
   FY - 9M and quarterly cash flows from year-to-date totals, marked derived (a derived EPS is
   approximate: AAPL Q4 FY2025 derives to 1.84 vs 1.85 reported). The context pack shows the last
   reported quarter (YoY growth, margins, FCF, filed date, `new` if filed in the last 5 days) and
   the latest balance sheet. No consensus estimates are available for free, so there is no
   earnings "surprise". Gaps, counted on the live data of 2026-10-05 (all quarters since late 2023
   in `fundamentals_metrics`, 10-12 per ticker):
   - Banks and insurers (ALL, BAC, JPM, PGR) tag no gross or operating profit: both margins blank.
   - Operating margin is also blank for CVX, DE, LLY, MRK and XOM (no `OperatingIncomeLoss`).
   - Gross margin is also blank for DAL, DE, GM, UAL and XOM (no gross profit and no cost of revenue
     among the collected tags).
   - FCF is blank for BAC and JPM (no capex tagged). DAL tags capex only in parts in its Q2 2026
     10-Q, so its latest quarter has no capex or FCF (9 of 10 quarters have them). ALL, NVDA and WMT
     lack capex only in their first quarter in the window (no earlier year-to-date total to subtract).
   - Total debt on the latest balance sheet is blank for CAT, DE and GM (debt tagged only in parts
     or custom tags).
   - META has no company-total shares-outstanding fact in company facts (likely because it reports
     class A and B shares separately), so its `shares_out` is blank.
   - Where no gross profit is tagged but a cost of revenue is (CAT, COST, CVX, GOOGL, LLY, META, MRK,
     WMT), gross margin is computed as (revenue - cost of revenue) / revenue and marked `c`: a
     uniform formula, not the company's own measure. It misleads for some: CVX's "cost" is purchased
     crude and products (47.8% for Q2 2026, not an oil major's margin), CAT's revenue includes
     financial-services revenue, and WMT's and COST's includes membership fees.

   **Not point in time:** the plain views (`fundamentals_latest`, `_quarterly`, `_metrics`) use every
   stored filing, so a restated or split-adjusted value replaces the original. A backtest or any
   as-of question must use the macros `fundamentals_latest_asof(ts)`, `fundamentals_quarterly_asof(ts)`
   and `fundamentals_metrics_asof(ts)`, which see only filings known by `ts` (`known_at` =
   acceptance time, or the end of the filing date in UTC when SEC's list no longer holds it).

Later (parked): options for India and US, paper first, only once stock ranges are proven calibrated.

## 11. Open items
- Watchlists: decided (20 per market, 10 sectors x 2), see `config/markets/`.
- India outlet RSS checked 2026-10-05 (Moneycontrol's feeds are frozen, now read via Google News).
  2027 calendars: NSE has not published its 2027 holiday list yet (expected mid-December 2026);
  `holidays:` in `config/markets/india.yaml` holds the fixed-date ones until then. Add the BLS 2027
  CPI dates and the RBI FY2027-28 MPC dates to `config/events.yaml` when they are published,
  and confirm the provisional 2027 FOMC dates (a six-meeting schedule has been proposed).
  exchange_calendars covers XNYS only to one year after the run date (2027-10-05 when checked
  on 2026-10-05); `holidays:` in `config/markets/us.yaml` adds the two later 2027 closures.
- Yahoo hosts, checked 2026-10-05 (~19:00-19:16 UTC) through a Claude Code session's egress
  proxy (US and India `collect_prices|quotes|events|options` into a scratch root, every HTTP
  request counted by host). Only `finance.yahoo.com` was refused then (403 to CONNECT, also with
  curl); it serves only yfinance's earnings-calendar page, which `collect_events.py` tries first:
  all 20 tickers per market fell back to the screener on `query1.finance.yahoo.com` and got their
  earnings dates (`earnings_history_sources`). `finance.yahoo.com` was allowlisted later that day:
  on the rerun of `collect_events.py` (20:06 UTC, both markets) it answered HTTP 200 20 times per
  market, the earnings page served all 20 tickers (`earnings_history_sources:
  {get_earnings_dates: 20}`) and `failed` stayed empty. No Yahoo host the routine uses is refused
  now. Prices, quotes and options used only `query1`/`query2`
  plus `fc.yahoo.com` for the cookie (fresh cache). `consent.yahoo.com` and `guce.yahoo.com` were
  not refused (HTTP 404 at the root) and not contacted. All data came back, but one run silently
  lost BAC's dividend history (yfinance printed "possibly delisted; no price data found"; a rerun
  returned 162 dividends): yfinance hides request errors behind empty frames, tuples and dicts.
  The Yahoo collectors therefore list in `failed` an empty or stale price frame (stale: older
  than the market's previous session, or 7 days for cues and factors), a stale or unpriced quote,
  a ticker with no option snapshot, an empty calendar, missing dividends where some are expected,
  and earnings dates when every method raised.
- Issue #9, done 2026-10-05 (no new network access needed):
  - Index rebalances are rules in `config/events.yaml`: the S&P 500 quarterly rebalance at the
    close of the third Friday of March, June, September and December (the triple-witching day),
    and the Nifty 50 semi-annual rebalance at the close of the session before the last trading
    session of March and September (new rule `month_end` with `session_offset: -1`). Both are
    listed with `major: false`: they are announced weeks ahead and their volume sits in the
    closing auction of the changed names, so they do not raise EVENT_HEAVY or widen ranges on
    their own (the S&P day is EVENT_HEAVY anyway through triple witching). The sources are cited
    in the file; the S&P date when the third Friday is a holiday (Juneteenth 2026 and 2027) is provisional.
  - US sector ETFs: one per watchlist sector (10): the eight SPDR funds plus JETS (Airlines) and
    IAK (Insurance). Each sector ETF lists the watchlist sectors it stands for (`sectors:` in
    `config/markets/<market>.yaml`); the context pack shows the mapping in the sector ETF table
    and a `sector_etf` column in the indicators, and names the sectors that have none (India:
    seven of ten; only Nifty Bank, IT and Pharma are configured, see `config/markets/india.yaml`).
    JETS and IAK returned two years of daily bars through yfinance on 2026-10-05.
- Issue #9, remaining free sources: **built 2026-10-05** after the hosts were allowlisted (checked
  ~21:45-22:15 UTC through the session's egress proxy). Collectors (HTTP client in `sources.py`:
  identifying User-Agent, 0.5-1 s between requests, up to 3 attempts on a dropped connection, none
  on an HTTP error; every unread source or session file is listed in `failed`):
  - `collect_macro.py` (US): Treasury par yield curve CSV (`home.treasury.gov`, HTTP 200);
    FRED `fredgraph.csv` (no key) for `BAMLH0A0HYM2`, `BAMLC0A0CM`, `T10YIE`. FRED answered
    HTTP 200 to Python's urllib (the live collector runs), but curl got an empty reply or an
    HTTP/2 stream reset on every try, and one single-attempt urllib request was dropped without
    an answer between successful ones: hence the retries. DGS2/DGS10/T10Y2Y are not fetched (Treasury's own par yields are the same H.15
    data; the view `macro_series` derives 10y-2y and 10y-3m), nor VIXCLS and DTWEXBGS (Yahoo
    `^VIX`, `DX-Y.NYB` already). Cboe daily options statistics JSON
    (`cdn.cboe.com/data/us/options/market_statistics/daily/<date>_daily_options`, HTTP 200; a day
    without a file answers 403) gives the put/call ratios. Cboe's VIX/VIX3M/VIX9D history CSVs
    (`cdn.cboe.com/api/global/us_indices/daily_prices/*_History.csv`) redirect (307) to
    `cdn-api.cboe.com`, which the egress proxy refuses (CONNECT 403), so there is no VIX term
    structure; `www.cboe.com` answers 302 to its pages.
  - `collect_shorts.py` (US): FINRA Reg SHO consolidated daily short-sale volume
    (`cdn.finra.org/equity/regsho/daily/CNMSshvol<YYYYMMDD>.txt`, HTTP 200; a day without a file
    answers 403; the trailer line's row count is checked) and consolidated short interest
    (`api.finra.org` POST with symbol and settlement-date filters, HTTP 200, no key). The daily
    file covers FINRA-reported (off-exchange) volume only, so the context pack compares each
    ticker with its own average.
  - `collect_flows_india.py` (India): NSDL "Daily Trends in FPI Investments"
    (`fpi.nsdl.co.in/web/Reports/Latest.aspx`, HTTP 200; `www.fpi.nsdl.co.in` is refused by the
    proxy) and NSE's daily index close file (`nsearchives.nseindia.com/content/indices/
    ind_close_all_<DDMMYYYY>.csv`, HTTP 200; 404 on a holiday) for 14 configured indices, one per
    watchlist sector, so the seven sectors without a Yahoo index get level, 1- and 5-session
    change and valuation in the context pack (not in the indicators: the stored history starts
    with the first run's 10-day lookback). `www.niftyindices.com` answers HTTP 200, but its data endpoints
    (`Backpage.aspx/getHistoricaldatatabletoString`, `.../getpepbHistoricaldataDBtoString`)
    return the home page and `Daily_Snapshot/ind_close_all_*.csv` its 404 page, so NSE's
    archive is used instead.
  - Not built: AMFI (`portal.amfiindia.com/spages/NAVAll.txt` answers HTTP 200, but scheme NAVs
    say nothing about 1- or 5-day stock moves, and AMFI's monthly net-flow figures come as monthly
    PDF/Excel reports about ten days after month end); BSE announcements: `www.bseindia.com`
    answers HTTP 200, but `api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w` and
    `.../AnnGetData/w` answer HTTP 403 "Access Denied" (Akamai) with Referer/Origin
    `https://www.bseindia.com` and a browser User-Agent, to Python (with and without the BSE
    home-page cookies) and to curl, so India announcements stay NSE-only.
  - News feeds added to `config/markets/*.yaml` (each answered HTTP 200 with fresh items):
    Business Standard markets and companies, BusinessLine markets and companies (India); PR
    Newswire all releases, Business Wire earnings (`feed.businesswire.com`, feed id
    `G1QFDERJXkJeEF9YXA==`; the home feed `G1QFDERJXkJeEFpRWQ==` says "deactivated by the
    administrator") and GlobeNewswire's public-companies RSS (`RssFeed/orgclass/1`) for the US,
    each with `watchlist_only: true`: only releases naming a watchlist company are stored
    (case-insensitive whole words on each ticker's `wire_names`, full company names, after
    removing the `news.wire_exclude` phrases such as "Apple Hospitality", "Merck KGaA",
    "meta-analysis"). GlobeNewswire is erratic by client: feedparser (the collector's path) got
    HTTP 200 with 20 items, and so did urllib with an RSS Accept header, but curl (HTTP/2 reset
    or empty reply) and several earlier urllib requests got the connection closed without an
    answer. `www.businesswire.com` and `www.spglobal.com` refuse cloud traffic (site-side 403).
- Issue #9, history: before 2026-10-05 ~21:30 UTC the cloud environment's egress proxy refused a
  connection (CONNECT answered 403) to each domain in backticks below, except the ones marked
  reachable:
  - BSE announcements and results: `www.bseindia.com`, `api.bseindia.com`
  - Business Standard: `www.business-standard.com`; BusinessLine: `www.thehindubusinessline.com`
  - US press-release wires: `www.prnewswire.com`, `www.businesswire.com`, `www.globenewswire.com`
  - Treasury yields: `home.treasury.gov`; FRED: `fred.stlouisfed.org`, `api.stlouisfed.org`
  - FINRA short volume: `www.finra.org`, `cdn.finra.org`, `api.finra.org`
  - CBOE put/call ratios: `www.cboe.com`, `cdn.cboe.com`
  - AMFI mutual-fund flows: `www.amfiindia.com`, `portal.amfiindia.com`; NSDL FPI flows: `www.fpi.nsdl.co.in`
  - Yahoo web pages: `finance.yahoo.com`. yfinance worked without it on 2026-10-05 (daily bars,
    fund holdings and an option chain were fetched); its API hosts query1.finance.yahoo.com and
    query2.finance.yahoo.com, and consent.yahoo.com and fc.yahoo.com, all accepted a connection,
    so only `finance.yahoo.com` needs adding. (Allowlisted later on 2026-10-05: see the Yahoo
    hosts note above.)
  - Index providers, to read rebalance notices directly: `www.spglobal.com` (S&P methodology and
    announcements), `www.niftyindices.com`. NSE's own nsearchives.nseindia.com (reachable) holds
    the Nifty methodology.
- Done 2026-10-05: NSE field mappings checked against live responses. PIT moved to the
  `corporates-pit-gg` filing index plus per-filing XBRL (the old feed dwindled in April 2026;
  last rows 2 May 2026);
  the pledge dataset's promoter % is depository-flagged data (`sdd_promoter_pct`), not the
  shareholding pattern; market-wide historical deals are capped at 70 rows, so the snapshot is
  used daily and per-ticker backfill on demand. Earlier note, kept for history:
- On the first India run with NSE allowed, check `collect_relations_india.py` field mappings
  against live responses (NSE changes field names; built from public scrapers, not yet seen live).
- Section 4 range inputs: **built** (`scripts/range_inputs.py`, switches in `config/ranges.yaml`):
  past earnings-day moves (dates and before-open/after-close timing from yfinance and, US, SEC
  8-K item 2.02, India, NSE results filings; backfilled by `collect_events.py`), ex-dividend
  shift (dividend amounts now collected), index-then-stock beta split of the overnight cue (US: `ES`; India: previous `SPX`
  session with a fitted beta), and US option-implied vol (`collect_options.py`) in the width
  blend and as the implied earnings move. The range notes and the `inputs` column say which
  applied, so the weekly review can score each one live.
  US earnings dates from SEC (2026-10-05): item 2.02 is not only the results release. Tesla files
  its quarterly deliveries under it (about the 2nd of Jan/Apr/Jul/Oct), Allstate its catastrophe-loss
  pre-announcements (to April 2024); Chevron an impairment (2024-01-02) and quarter guidance
  (2026-04-09), Lilly a guidance update (2025-01-14), United a debt redemption (2025-07-09),
  Caterpillar a director appointment (2024-10-11). A fresh backfill held 23 pairs of US earnings
  dates under 45 days apart among 283. `collect_events.py` now also stores each 10-Q/10-K
  acceptance (`periodic_report` rows with `period_end`), and
  `range_inputs.results_filter` keeps, per report, the latest 2.02 after its period end and up to a
  day after its acceptance; other 2.02s are not earnings. A 2.02 whose 10-Q is not filed yet still
  counts, unless a year of releases is confirmed and it comes before the next period end or sooner
  after it than 0.75 x the shortest confirmed lag (a delivery report two days after the quarter end
  vs results 18+ days after). Only reports accepted by the as-of date are used: `ranges.py` uses
  those accepted by made_at's date, `backtest.py` the ones accepted by each day d
  (`earnings_versions`). Stored rows are never removed; the filter applies when the dates are read.
  Where yfinance and SEC disagree, SEC wins: of the 210 past yfinance report dates between each
  ticker's first and last confirmed SEC release, 208 are within 3 days of one; the two others are PGR 2023-10-31 (the 10-Q day;
  +1.9% that day vs +8.1% on the 2023-10-13 release) and COST 2024-06-06 (the day after the 10-Q;
  the press release is dated 2024-05-30), so a past yfinance date within 45 days of a confirmed
  release is dropped. Result: 260 dates, no pair under 45 days. Backtest to 2026-10-02 (250
  sessions), past moves vs the fixed x3: 1d 20.73 -> 20.20 (n 85) before, 20.90 -> 20.53 (n 80)
  after, still improves (on); 5d 23.85 -> 24.03 (n 424) before, 23.90 -> 24.17 (n 400) after,
  still worse (off).
- Backtest of the inputs. **Rule** (section 7, one window): an input is on for a market and
  horizon only if `backtest.py` over the stated 250 sessions (to 2026-10-02 US, 2026-10-01
  India) lowers the 80% interval score (in % of price, scored only where the input applies) by
  more than `backtest_min_gain` = 0.5% relative; a smaller change either way is noise and stays
  off. Switches are per market and horizon in `config/ranges.yaml`. Off -> on, verdict:

  | Input | US 1d | US 5d | India 1d | India 5d |
  |---|---|---|---|---|
  | Past earnings moves (vs the fixed multiple: US x3, India x2) | 21.11 -> 20.72, n 82, improves: **on** | 24.23 -> 24.53, n 409, worse: off | 9.74 -> 9.97, n 78, worse: off | 14.97 -> 15.15, n 391, worse: off |
  | India fixed earnings multiple x3 -> x2 | not tested: x3 | not tested: x3 | 11.54 -> 9.74, n 78, improves: **x2** | 15.445 -> 14.97, n 391, improves: **x2** |
  | Ex-dividend shift | 7.45 -> 6.55, n 72, improves: **on** | 13.60 -> 13.08, n 359, improves: **on** | 4.93 -> 4.22, n 27, improves: **on** | 12.79 -> 12.10, n 138, improves: **on** |
  | Beta split (vs direct cue) | same, n 5000: off | same, n 5000: off | 5.497 -> 5.454, n 5000, improves: **on** | 11.924 -> 11.916, n 5000, noise: off |
  | Implied vol | no history: off | no history: off | no chains | no chains |

  Checks outside the rule (440 sessions): US earnings moves 1d 22.77 -> 22.33, 5d 26.53 -> 26.48
  (noise); India beta split 1d 5.373 -> 5.345, 5d 12.059 -> 12.061 (slightly worse, so 5d stays
  off). India earnings dates (2026-10-05): yfinance's stop at 2025-05-22, so `collect_events.py`
  takes them from NSE results filings (Integrated Filing from the March 2025 quarter, the older
  financial-results list before it; the earliest filing per quarter, moved to the results
  announcement up to 36 hours earlier, timed in IST; quarters first filed after the SEBI deadline
  are dropped): 228 reports from 2023-10-11 to 2026-08-07, 12 per ticker except the insurers
  HDFCLIFE and SBILIFE (6 each from April 2025; NSE's older list gave no rows for them in the
  window, so yfinance supplies their 6 earlier ones), timed 29 before the open, 74 during, 125
  after the close. With
  these dates the fixed x3 was too wide (1d earnings ranges covered 91.0% of 78, 5d 85.4% of 391).
  Past moves at x3 passed the rule (1d 11.54 -> 10.57, 5d 15.445 -> 15.10), but a lower fixed
  multiple beat both: the fixed arm scored 1d 10.48 / 9.74 / 9.73 and 5d 15.01 / 14.97 / 15.36 at
  x2.5 / x2 / x1.5 (x3: 11.54, 15.445). x2 is the only value best or within noise of best at both
  horizons, so India uses `earnings_vol_multiple_by_market: {india: 2.0}`, and against x2 past
  moves are worse at both horizons (off). The value was picked from these four on the same window;
  the 440-session check agrees (fixed 1d x3 11.42, x2.5 10.45, x2 9.95, x1.5 10.09; 5d 15.61,
  15.11, 15.04, 15.37; past moves vs x2 1d 9.95 -> 10.07, 5d 15.04 -> 15.12, worse). At x2 the 5d
  earnings ranges cover 73.4% (1d 83.3%): the interval score is lower, but the weekly review
  should watch 5d earnings coverage. Before the NSE dates the India backtest had no earnings
  rows at 250 sessions and 38 at 440 (1d covered 97.4%). In the US every stock has its own pre-market cue, so with equal weights the beta
  split equals the direct cue; US cue history is a proxy (next open gap, which flatters cues in
  absolute terms). Implied vol cannot be backtested: it is off, `collect_options.py` keeps
  collecting, and each range row stores the sigma the IV blend would have given (`iv_sigma_h`,
  same centre) so the weekly review can score it against `sigma_h` before switching it on.
  With every input off, `ranges.py` output equals the code before these inputs except the new
  `inputs` and `iv_sigma_h` fields (checked on the stored data of both markets).

## 12. Neo4j projection (graph copy for analysis)
All data and results are also loaded into a Neo4j database for graph questions (who is connected to
whom, who traded before what, which evidence led to good calls). **The repo stays the source of
truth**: `data/` is append-only and `scripts/neo4j_sync.py` only reads it (through the DuckDB views
of `common.connect`). Neo4j is a derived copy; `--full` deletes one market's nodes and rebuilds them
from the repo, so emptying or losing the database loses nothing.

**Connection.** Environment variables `NEO4J_URI` (`neo4j+s://<id>.databases.neo4j.io`; only the
host is used), `NEO4J_USER`, `NEO4J_PASSWORD`, optional `NEO4J_DATABASE`. Bolt is not reachable
through the cloud session's HTTPS proxy, so statements go to the HTTPS Query API v2: `POST
https://<host>/db/<database>/query/v2` with basic auth and `{statement, parameters}`. On Aura the
database is named after the instance id, not `neo4j` (`/db/neo4j/...` answers 404
`DatabaseNotFound`), so the default database is the first label of the host
(`<id>.databases.neo4j.io` -> `<id>`); `NEO4J_DATABASE` overrides it, and a localhost or IP host
defaults to `neo4j`. The host must be allowed in the environment's network settings. The password
and URI are never printed; the summary shows the host only.

**Model.** Every node id is prefixed with the market (`us:AAPL`, `india:<news id>`), so the two
markets never share a node and `--full` for one market cannot touch the other.

| Node | Key (`id`) | From |
|---|---|---|
| `Market` | `<market>` | config |
| `Sector` | `<market>:<sector>` | config (`sector_etf` property) |
| `Company` | `<market>:<ticker>` | config (`watchlist: true`); tickers seen only in data or as a graph target get `watchlist: false` |
| `Holder` (+ `Person` when known) | `<market>:cik:<cik>` (SEC filers and insiders), else `<market>:name:<slug>`; `<market>:promoters:<ticker>` for an India promoter group | insiders, deal clients, 13D/13G and 13F filers, graph targets that are not tickers |
| `Source` + `NewsItem` / `Filing` / `Announcement` | `<market>:<record id>` | news (+ latest `news_enriched`), SEC filings, NSE announcements (+ latest enrichment). A `Source` with `placeholder: true` is evidence a prediction cites that is not (yet) in the data |
| `Event` | `<market>:<event id>` | events, first copy per id (as `event_history`); `current` = the latest known date per (ticker, type) (as `company_events`); market-wide events are always current |
| `Prediction` | `<market>:<prediction id>` | predictions (first copy per id) |
| `Range` | `<market>:<range id>` | `ranges_latest` |
| `Outcome` | `<market>:call:<prediction id>` / `<market>:range:<range id>` (`kind` call or range) | outcomes / range_outcomes, first score per id (as `range_record`) |
| `RegimeDay` | `<market>:<as_of_date>` | `regime_latest` |
| `FeatureDay` | `<market>:<ticker>:<as_of_date>` | `features_latest` (close and every indicator) |
| `Judgment` | `<market>:<judgment id>` | daily-run judge verdicts |
| `FinancialPeriod` | `<market>:<ticker>:sec:<period_end>` (US) / `<market>:<ticker>:<basis>:<start>:<end>` (India) | `fundamentals_metrics` / `financials_latest` |
| `FlowDay` | `<market>:<date>:<category>` | `flows_daily` (FII/DII) |
| `SyncState` | `<market>:<kind>` | written by the sync: the incremental watermark per kind |

| Relationship | Meaning and main properties |
|---|---|
| `(Company)-[:LISTED_ON]->(Market)`, `(Company)-[:IN_SECTOR]->(Sector)-[:IN_MARKET]->(Market)` | config |
| `(NewsItem)-[:MENTIONS]->(Company)` | one per ticker tag: `day`, `sentiment`, `relevance`, `materiality`, `event_type`, `novelty`, `analyzed_at`, `prompt_version` (latest analysis wins) |
| `(Company)-[:FILED]->(Filing or Announcement)` | SEC filings, NSE announcements |
| `(Company or Market)-[:HAS_EVENT]->(Event)` | earnings, ex-dividend (`amount`), index and macro events |
| `(Holder)-[:TRADED {id}]->(Company)` | `via` insider / bulk / block; `side` buy or sell (Form 4 code P/S, SEBI PIT transaction, deal side), `trade_date`, `shares`, `price`, `value`, `role`, `code`, `plan_10b5_1`, `disclosed_at` |
| `(Holder)-[:HOLDS {id}]->(Company)` | `via` 13F (`period`, `shares`, `value_usd`, `action`, `change_shares`, `complete`, from `holdings_change`), 13D / 13G (`percent`, `shares`, `filing_date`, `purpose`), shareholding (India promoter group: `period`, `promoter_pct`, `pledged_pct_of_promoter`, q/q changes, from `pledge_changes`) |
| `(Company)-[:CONNECTED_TO {id}]->(Company or Holder)` | graph edges: `relation`, `detail`, `weight`, `as_of`, `source_url`, `aliases`, `prompt_version`; a retracted edge (`status: removed`) is deleted |
| `(Prediction)-[:PREDICTS]->(Company)` | `direction`, `confidence`, `horizon_days`, `as_of_date` |
| `(Prediction)-[:CITES]->(Source)` | one per `evidence_ids` entry |
| `(Prediction)-[:HAS_RANGE]->(Range)`, `(Range)-[:RANGE_FOR]->(Company)` | the published range for the call (same id) |
| `(Prediction or Range)-[:SCORED_AS]->(Outcome)` | `hit`, or `hit50` / `hit80` |
| `(Market)-[:HAS_REGIME]->(RegimeDay)`, `(Company)-[:HAS_FEATURES]->(FeatureDay)`, `(Company)-[:REPORTED]->(FinancialPeriod)`, `(Market)-[:HAS_JUDGMENT]->(Judgment)`, `(Market)-[:HAS_FLOW]->(FlowDay)` | time-indexed results |

**Provenance.** Every node and relationship carries `market`, `source_kind` (the data kind, e.g.
`news`, `insiders`, `holdings_13f`), `source_id` (the `id` in the JSONL line; for the derived US
fundamentals metrics the view key, and for an India shareholding quarter the ids of the rows it
combines), `recorded_at` (the record's own timestamp: `first_seen_at`, `analyzed_at`, `made_at`,
`scored_at`, `computed_at`, `added_at` or `recorded_at`) and `synced_at`. Record nodes also keep
`record_id` and all fields of the record. Dates and timestamps are Neo4j `DATE` / `DATETIME`
values. Not projected (time series or bookkeeping that stay in DuckDB): prices and quotes (each
`FeatureDay` carries the close), options, calibration, delivery, reviews (nested JSON; the review
report is in `reports/`) and graph_runs.

**Writes.** Statements are static Cypher; all values are parameters (`UNWIND $rows AS row`),
batched 500 rows per request. Every write is a `MERGE` on an id (nodes) or on the two end nodes
plus an id (`TRADED`, `HOLDS`, `CONNECTED_TO`), followed by `SET`, so re-running the same rows
changes nothing. Uniqueness constraints on `id` for every label and indexes (ticker, market, event
date, relationship ids) are created with `IF NOT EXISTS` on the first sync and skipped afterwards
(a `SyncState {id: '_schema'}` node holds the schema version).

**Corrections** follow the DuckDB views: a newer `news_enriched` row for the same id overwrites the
sentiment on the `NewsItem` and its `MENTIONS`; a recomputed regime or feature row replaces the
day's values; a retracted graph edge deletes the relationship; a moved earnings date makes the old
`Event` `current: false`; a newer 13F filing for the same period or a revised India result updates
the relationship or node in place.

**Incremental mode** (default). Each kind reads the rows whose `recorded_at` is at or after its
watermark minus 3 days (re-upserting the overlap is harmless) and, only after every batch of that
kind succeeded, stores the newest `recorded_at` as the watermark in Neo4j (`SyncState`), so it
survives the routine's fresh container. Kinds derived from history (13F changes, India
shareholding changes, US fundamentals metrics, the events `current` flag) are re-sent in full each
run. A failed kind keeps its old watermark, so the next run re-sends it. Rows appended later with a
`recorded_at` more than 3 days before the watermark (e.g. a manual backfill) need `--full`.
`--since <ISO time>` overrides every watermark; `--kinds a,b` limits the run.

**Output.** One JSON summary: per kind `rows_read`, `upserted`, `failed` (and `since`,
`watermark`, `error`), plus Neo4j's counters. Exit 0 = all synced, 1 = any failure, 2 =
`NEO4J_URI` not set. `--dry-run` sends nothing: it writes every statement with its parameters to
`work/neo4j_dryrun/<market>/NNNN-<kind>-....json`. `--probe` runs `RETURN 1`. In the routine the
sync is optional and never blocks the brief (`routine/PROMPT.md` steps 10b and 15).

**Status (2026-10-05).** Built and tested offline (`tests/test_neo4j_sync.py`: a fake Query API
server; an optional test runs the same data through a real Neo4j 5 server when
`NEO4J_TEST_QUERY_URL` points to a disposable one). A read-only probe (`--probe`, `RETURN 1`)
against the user's Aura instance returned `[[1]]`. No live sync has been run yet: the first one,
`python scripts/neo4j_sync.py --market <m> --full`, waits for the judge's PASS on this code.

**Example queries** (Neo4j Browser or the Query API; replace the market and dates):

1. Watchlist companies connected to a stock that had negative news on a day (second-order exposure):
   ```cypher
   MATCH (n:NewsItem)-[m:MENTIONS]->(hit:Company)
   WHERE n.market = 'us' AND m.day = date('2026-10-05') AND m.sentiment <= -0.3
   MATCH (hit)-[e:CONNECTED_TO]-(other:Company)
   WHERE other.watchlist AND NOT (n)-[:MENTIONS]->(other)
   RETURN other.ticker AS exposed, hit.ticker AS via, e.relation AS relation, e.source_url AS edge_source,
          n.title AS headline, m.sentiment AS sentiment
   ORDER BY sentiment, exposed
   ```
2. Insider sales in the 30 days before an earnings date (current dates and past earnings days):
   ```cypher
   MATCH (h:Holder)-[t:TRADED {via: 'insider', side: 'sell'}]->(c:Company)-[:HAS_EVENT]->(e:Event {type: 'earnings'})
   WHERE c.market = 'us' AND (e.current OR e.source ENDS WITH '_history')
     AND t.trade_date < e.date AND t.trade_date >= e.date - duration({days: 30})
   RETURN c.ticker AS ticker, h.name AS insider, t.role AS role, t.trade_date AS sold_on, t.value AS value,
          e.date AS earnings_date, duration.inDays(t.trade_date, e.date).days AS days_before
   ORDER BY days_before
   ```
3. Call accuracy by the type of evidence cited:
   ```cypher
   MATCH (p:Prediction)-[:SCORED_AS]->(o:Outcome {kind: 'call'}) WHERE p.market = 'us'
   MATCH (p)-[:CITES]->(s:Source)
   WITH DISTINCT p, o, CASE WHEN s:NewsItem THEN 'news: ' + coalesce(s.event_type, 'not analysed')
                            WHEN s:Filing THEN 'filing: ' + coalesce(s.form, '?')
                            WHEN s:Announcement THEN 'announcement' ELSE 'not synced' END AS evidence
   RETURN evidence, count(p) AS calls, round(avg(CASE WHEN o.hit THEN 1.0 ELSE 0.0 END), 3) AS hit_rate,
          round(avg(p.confidence), 3) AS avg_confidence
   ORDER BY calls DESC, evidence
   ```
4. Range coverage by regime and horizon:
   ```cypher
   MATCH (r:Range)-[:SCORED_AS]->(o:Outcome {kind: 'range'}) WHERE r.market = 'india'
   RETURN r.regime AS regime, r.horizon_days AS horizon, count(*) AS n,
          round(avg(CASE WHEN o.hit50 THEN 1.0 ELSE 0.0 END), 3) AS cover50,
          round(avg(CASE WHEN o.hit80 THEN 1.0 ELSE 0.0 END), 3) AS cover80
   ORDER BY regime, horizon
   ```
5. Who holds or traded each company, traced back to the JSONL record:
   ```cypher
   MATCH (h:Holder)-[x:HOLDS|TRADED]->(c:Company) WHERE c.market = 'us'
   RETURN c.ticker AS ticker, type(x) AS link, x.via AS via, h.name AS holder,
          x.source_kind AS kind, x.source_id AS record_id, x.recorded_at AS recorded_at
   ORDER BY ticker, link, holder
   ```
   `kind` names the data kind (`holdings_13f` and `shareholding` read `data/<market>/holdings/`) and
   `record_id` the line's `id`.
