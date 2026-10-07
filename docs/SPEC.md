# market-brief: product specification and parallel roadmap

Status: draft for the owner's approval (2026-10-07). It records every decision the owner made in the
question rounds of 2026-10-07 and turns them into features, data, API, pages, integrations and a
roadmap of stages that can be built in parallel cloud sessions. It builds on what is already merged
(docs/DESIGN.md, docs/ARCHITECTURE.md, api/openapi.yaml, docs/ws/) and changes none of its rules unless
a section says so explicitly ("Rule change").

Research only. The system never places, routes or simulates a broker order and never connects to a
broker. Paper trades are records. Real-money decisions are the owner's, made by hand, and only after
the go-live bar (F7) is met.

## 0. Goal in one paragraph

A personal research cockpit that predicts the next-day (and, for research, next-week) price of the
companies the owner follows as accurately as possible. Rule-based strategies do the calculation;
AI traders decide on their own; both paper-trade the same companies with the same amounts under one
protocol, are monitored during the day, settled after the close and compared. AI explains why a
strategy or prediction did well or badly. Everything is visible on a database-backed dashboard, and
the owner can steer the system (add, deactivate, reactivate, delete companies, change amounts, ask
questions) from the dashboard, Slack, Claude Code and the Claude app.

## 1. Decisions (owner, 2026-10-07)

| # | Topic | Decision |
|---|---|---|
| 1 | Trade timing | Buy at the OPEN of D (the first session after the prediction is made), sell at the CLOSE of D+1. Prediction locked before D's open. No intraday trading. |
| 2 | 5-day horizon | Kept as a research horizon (buy at the open of D, sell at the close of D+4), scored and shown separately. |
| 3 | Down signals | Buy-only in both markets: a "down" prediction creates no trade (it is still scored as a prediction). |
| 4 | India share price above the amount | Skip the trade unless the company's amount is raised. Whole shares only in India. |
| 5 | US shares | Fractional shares: exactly the amount is invested. |
| 6 | Costs | India: Axis Direct. US: BUX (ABN AMRO), owner trades from the Netherlands. Charges in F1.6 (provisional until confirmed). |
| 7 | Trades per day | Both views: accuracy view (every signal trades its amount, no limit) and money view (a budget per strategy, at most 5 trades a day, strongest first). |
| 8 | Who is better | Headline = profit after costs on the same trades and amounts; beside it win rate, price-prediction error, worst losing streak, drawdown and a luck test. |
| 9 | AI traders | 3 on Sonnet (news & results; price pattern & market mood; combined) + 1 on Opus (combined), from day one. |
| 10 | AI sees the rule-based score | Mixed: the news and pattern traders are blind; both combined traders see the model score. |
| 11 | Currency (US) | Strategies are compared in USD ($1,000 per trade). The owner's own paper portfolio also shows EUR, including BUX's conversion fee and the rate change. |
| 12 | Delete company | Hide everywhere (tombstone): no display, no use, no collection, purged from derived stores; old records stay in git history, never shown. |
| 13 | Deactivated company | Shown in an Inactive section on the Companies page (news, price, Reactivate); out of picks, strategies and the watchlist; collection continues. |
| 14 | Allowed companies | Common stocks listed on NSE (India) or NYSE/Nasdaq (US). No BSE-only stocks, no ETFs. |
| 15 | Slack commands | Any member of the #market-brief channel may give commands (each command logged with its Slack user). Delete is never available in Slack. |
| 16 | Dashboard users | Owner only, Vercel Authentication. |
| 17 | Pages | All 10 (section 6). |
| 18 | Screens | Phone (390 px) and laptop (1280 px) equally. |
| 19 | Charts | Our own charts from stored data (vendored Lightweight Charts); no TradingView widgets. |
| 20 | Dashboard actions | All: add, deactivate, reactivate, change amount, delete (delete dashboard-only, with confirmation). |
| 21 | Slack posts | Morning picks, close results, alerts, weekly report; one thread per market per day plus the weekly post. |
| 22 | Claude app login | GitHub OAuth, the owner's account only. |
| 23 | Go-live review | First formal review 2 months after the new paper trading starts; go-live only if the bar (F7) is met, else monthly reviews. |
| 24 | Neo4j | Kept, off the critical path (nothing the dashboard needs depends on it). |
| 25 | Old static pages | Retired 2 weeks after the new app is live; Slack then links to the new app. |
| 26 | Amounts | Default ₹1,00,000 per trade (India) and $1,000 (US); override per company, either market. |
| 27 | Growth | At most 50 companies within a year. Git + MotherDuck suffice; no bulk-storage move planned. |
| 28 | Dashboard chat | Claude API, hard cap $20 per month. |
| 29 | Intraday checks | Monitoring only (no trades): open paper positions are checked a few times per session. |

## 2. Words used in this document

- **Strategy**: a frozen rule set or AI trader that turns stored data into predictions. Each has an
  `strategy_id` (e.g. `rule.model_news_1x.v1`, `ai.news_results.sonnet.v1`). Changing a strategy makes
  a new id; an id's behaviour never changes after its first live day.
- **Prediction**: per strategy, company, horizon and day: direction (up/down), probability, target
  price (expected close), a price range, and the evidence. Made before the open of D.
- **Paper trade**: what a prediction turns into under the protocol (F1): only "up" predictions above
  the strategy's threshold trade.
- **Account**: one strategy's trades under one view (accuracy or money).
- **Settlement**: the deterministic computation of a trade's outcome from stored bars after the exit
  close.
- **Lifecycle of a prediction**: made (pre-open) -> monitored (intraday checks) -> settled (after the
  close) -> explained (end-of-day analysis) -> aggregated (scoreboard, weekly review).

## 3. Features

Each feature lists what it does, the rules it must keep, and when it counts as done. Where an existing
part already does it, the feature says "exists" and what changes.

### F1 Paper-trading protocol (one engine for every strategy)

1. **Timing.** A prediction made at `made_at` before the open of D enters at D's official open and
   exits at the official close of D+1 (1d) or D+4 (5d, research). `made_at` must be before D's open
   (checked against the market calendar); a later prediction is refused. No open price on D (halt,
   missing bar): no trade, recorded as `no_entry`. No exit close: settled on the next stored close and
   flagged `exit_delayed`. Sessions come from the market calendar (special sessions count).
2. **Buy-only.** Only `direction = up` with probability >= the strategy's threshold creates a trade.
   Down predictions are scored as predictions only.
3. **Amount.** Per company: the override if one is active at `made_at`, else the market default
   (₹1,00,000 India, $1,000 US). Overrides are watchlist events (F8).
4. **Quantity.** India: `floor(amount / open)` whole shares; 0 shares (one share costs more than the
   amount) = trade skipped, recorded `skipped_price_above_amount`. US: `amount / open` fractional, 6
   decimals.
5. **Prices.** Entry and exit use the split-adjusted official bars as stored (`ohlc`), so a split or
   bonus between entry and exit does not distort the result.
6. **Costs** (applied to entry and exit value; the table lives in `config/costs.yaml`, each value
   marked verify with its source):

   | Market | Charge | Provisional value | Status |
   |---|---|---|---|
   | India (Axis Direct) | Brokerage, delivery | 0.50% each side ("Investment Plus") or 0.25% ("Now or Never"): owner to confirm the plan | SECONDARY SOURCE, not verified |
   | India | DP charge per scrip sold | ₹30 or 0.04% (higher), source quoted it for NRI accounts | SECONDARY SOURCE, not verified |
   | India | STT, exchange, SEBI, stamp duty, GST | as already in `config/costs.yaml` | as documented there |
   | US (BUX) | Order fee, US stocks | €0.99 per market order | SECONDARY SOURCE (2024-era), not verified |
   | US | FX conversion | 0.25% EUR->USD (USD->EUR not found) | SECONDARY SOURCE, not verified |
   | US | SEC fee, FINRA TAF | as already in `config/costs.yaml` | official, as documented there |

   The official broker pages could not be opened from the cloud environment. The owner confirms the
   real charges from a contract note (India) and the BUX fee page (US); until then strategies are still
   comparable because every account pays the same costs. The USD comparison (decision 11) applies the
   order fee converted at the day's EUR/USD rate and leaves the FX conversion to the owner's EUR view.
7. **Two views.** Accuracy view: every qualifying prediction trades its amount, no limit. Money view:
   per strategy a budget of ₹5,00,000 (India) / $5,000 (US) of capital; at most 5 new trades a day,
   ranked by probability (ties: ticker order); no new trade while capital is tied up in open trades
   beyond the budget. Both views come from the same predictions.
8. **Locked before the open.** Predictions are appended to `data/` and pushed before D's open; the
   settlement refuses any prediction whose `made_at` is after the entry open or whose record was
   first committed after it (checked from git when available).
9. **Settlement** is deterministic and re-runnable: same stored bars give the same result. Each trade
   records entry, exit, quantity, gross and net P&L (₹ or $), return %, costs, target error (exit close
   vs predicted target, %), range hit (exit close inside the predicted range), and status.
10. **Owner's own paper portfolio** (exists, WS4: `scripts/portfolio.py`) keeps manual trades; it gains
    the EUR view for US trades (rate change + FX fee) and reads amounts and costs from the same place.

Done when: a fixture week of predictions settles to hand-checked numbers for both markets, both views,
both horizons, including skip, no-entry, delayed exit, split and holiday cases; the engine is the only
place P&L is computed.

### F2 Strategy lab (rule-based strategies)

1. A registry `config/strategies.yaml`: each rule strategy has an id, a description in plain words,
   parameters, a probability threshold, horizons, and `live_from` (the first session it trades).
   Parameters are combinations of: the signal model (as is), news weight by news type, verification
   status and materiality (0, 0.5, 1, 2), cross-market groups on or off, a regime filter (no trades in
   `UNSTABLE` or `EVENT_HEAVY`), and a minimum probability.
2. **Baselines** are accounts too: always-up (buy every company every day), momentum (buy if the last
   session rose), model-only (the signal model with no news).
3. **Back-test** on the 15-year history cache for strategies that need no news (news history exists
   only from collection start); clearly labelled back-test, never pooled with forward results.
4. **Forward**: every rule strategy predicts daily for every active company in the pre-open run;
   the predictions go through F1.
5. Initial set: about 8 rule strategies + 3 baselines, chosen so each differs from the others in one
   parameter (so a difference in results points to that parameter).

Done when: the registry validates; the pre-open run writes one prediction per strategy x company x
horizon; back-test and forward results are stored separately; adding a strategy is a config change only.

### F3 News-impact study

For every news category (event type), verification status and materiality level: the average move of
the stock over the next 1 and 5 sessions relative to its benchmark and sector (abnormal return), with
a confidence interval and the number of events. Refreshed weekly from stored data only, as of the
review date (no look-ahead). It answers "which news moves prices, and how much" and is the evidence
behind any change of news weights. Small samples are shown as "not enough events yet".

Done when: the weekly review shows the table per market with counts and intervals; a fixture with a
planted effect is recovered.

### F4 AI traders

1. Four AI strategies per market, each a Claude Code subagent with its own definition file
   (`.claude/agents/trader-*.md`): model, allowed tools, inputs, budget, kill switch.

   | Trader | Model | Sees | Focus |
   |---|---|---|---|
   | `ai.news_results.sonnet` | Sonnet | news (with verification status), results digests, filings, events | what happened to the company |
   | `ai.pattern_mood.sonnet` | Sonnet | prices, indicators, regime, global cues, sector moves | how the stock and market behave |
   | `ai.combined.sonnet` | Sonnet | everything above + the signal model's score and explanation | combine rules and judgment |
   | `ai.combined.opus` | Opus | the same as combined Sonnet | the existing forecaster, extended to the protocol; tests whether the stronger model helps |

2. Each runs in the pre-open run (as subagents of the existing daily session, not separate sessions)
   and writes per active company and horizon: direction, probability, target price, range, up to 3
   evidence ids, and a reason of at most 60 words. A deterministic gate (shared with the existing
   prediction rules) checks: ids exist and are verified enough (DESIGN.md 3b), no call with earnings
   within 1 day, `BLOCKED` quality refused, ranges no narrower than `ranges.py`'s, numbers match stored
   data. One retry, then the trader abstains for that run (recorded).
3. Abstaining is allowed and recorded; an abstention is not a trade and not a loss.
4. Every AI prediction then goes through F1 exactly like a rule prediction.

Done when: one dry-run day per market produces gated predictions from all four traders; a failed gate
leaves an abstention record, not a missing row.

### F5 Intraday monitoring (exists: WS5; scope changes to monitoring of open paper trades)

Two checks per session per market (India 05:43 and 08:43 UTC; US 12:27 and 14:57 New York time) for
every open paper trade of every strategy: price vs entry, vs target and vs range; flags (outside the
range, far from target in volatility units, against the prediction). The deviation explainer (exists)
writes at most 60 words per flagged company citing only stored candidates (market, sector, news,
events). Nothing is traded. The dashboard shows the day's path per prediction.

Done when: the two schedules run, each check writes rows for all open trades, and the Company page
shows the path.

### F6 End-of-day analysis and weekly research review

1. **Post-close run** per market (new; India 16:15 IST, US 16:45 New York time): collect the day's
   close, settle every trade whose exit was today (F1), then the **EOD analyst** (Sonnet) writes per
   market: today's result per strategy family (rule vs AI), the 3 biggest misses and 3 best calls with
   their cause, grounded in the deterministic attribution (market, sector, news, events, residual) and
   citing ids; a gate checks ids and numbers (like `lessons.py`).
2. **Weekly research director** (Opus, weekend): reads the scoreboard (F7), the news-impact study
   (F3), the week's EOD analyses and lessons; writes the weekly report: who is ahead and why, which
   information helped, and proposals (new strategy versions, weights, thresholds) as config diffs for
   the owner to approve. It changes nothing by itself.
3. The existing reflector lessons continue for settled calls.

Done when: a settled day produces an EOD analysis that passes its gate; the weekly report lists every
proposal as an approvable diff.

### F7 Scoreboard and the go-live bar

1. Per strategy, per market, per horizon, per company and overall, for both views: trades, profit
   after costs (headline), return %, win rate, average target error %, range-hit rate, worst losing
   streak, maximum drawdown, and a luck test (bootstrap interval of the mean net return; multiple-
   testing correction across all strategies compared). Rule vs AI head-to-head on identical
   company-days. Baselines on the same table.
2. **Go-live bar** (owner-approved): at least 2 months of forward paper trading and about 300 trades
   per strategy (accuracy view); beats the best baseline after costs with the corrected luck test
   excluding zero; maximum drawdown within the owner's limit (to be set at the first review; proposal
   10% of the money-view budget); holds in calm and volatile regimes. First formal review 2 months after
   F1 goes live; then monthly. A strategy that meets the bar is "proven"; only proven strategies may show
   Strong Buy (the existing WS4 rule generalised to strategies).

Done when: the scoreboard read model exists for both markets and both views and the review report
states each strategy's position against the bar.

### F8 Company lifecycle (watchlist as data)

1. **Rule change** (owner-approved by decisions 12-15 and 20): the list of companies moves from
   `config/markets/<market>.yaml` `tickers:` into append-only records `data/<market>/watchlist_events/`
   (`add`, `deactivate`, `reactivate`, `delete`, `set_amount`), gated by a deterministic validator
   instead of a judge review. Market-level config (calendar, benchmark, sectors, feeds) stays in config
   and keeps its judge review. The current 40 companies are seeded as `add` events dated from their
   original addition, so history stays continuous.
2. **States**: `active` (collected, predicted, traded), `inactive` (collected, not predicted or traded),
   `deleted` (not collected, not shown, excluded on read everywhere; derived stores purge it). One
   accessor (`watchlist(market, as_of, state)`) replaces every direct read of `tickers:`.
3. **Add** takes: market, exchange symbol, optional name, optional amount. The onboarding pipeline
   (deterministic, no AI needed): resolve and check identifiers (NSE symbol and Yahoo symbol; or
   NYSE/Nasdaq ticker, Yahoo symbol and SEC CIK), refuse ETFs, BSE-only and unknown symbols, set the
   sector, backfill daily price history (15 years where available) and recent news, filings and
   announcements, run the collect gate, then append the `add` event. The company is predicted and
   traded from the next pre-open run.
4. **Deactivate / reactivate / set amount** take effect at the next pre-open run; open paper trades of
   a deactivated company still settle normally.
5. **Delete** (dashboard only, with a typed confirmation) appends a `delete` tombstone; reads exclude
   the company everywhere; the warehouse and Neo4j drop it at the next sync. Raw records stay in git
   history (decision 12).
6. Every event records who asked, through which channel, and the idempotency key.

Done when: add, deactivate, reactivate, set amount and delete work end to end from the CLI on a
fixture company; the seeded watchlist reproduces today's outputs byte for byte (golden harness).

### F9 Notifications (Slack)

One thread per market per day in `#market-brief`: (1) morning picks before the open (top 3-5 per
market across strategies, each with strategy family, probability, target, amount, Paper label);
(2) intraday alerts in the same thread (a flagged open trade, material news on a company with an open
trade); (3) close results (each settled trade, rule vs AI today); plus (4) the weekly report as its own
post, and onboarding confirmations as replies to the command that asked. Quiet hours: none outside
these runs.

### F10 Channels and governed tools

One set of tools, defined once (`mcp/tools.yaml`), used by every channel:

| Tool | Kind | Dashboard | Slack | Claude Code | Claude app |
|---|---|---|---|---|---|
| `get_overview`, `get_company`, `get_scoreboard`, `compare_rule_vs_ai`, `get_news`, `get_trades` | read | yes | yes (`/ask`) | yes | yes |
| `explain` (why did X deviate / why did strategy Y win) | read + AI | chat | `/ask` | yes | yes |
| `add_company` | write | yes | `/company` form | yes | yes |
| `deactivate_company`, `reactivate_company`, `set_paper_amount` | write | yes | `/company` | yes | yes |
| `delete_company` | write | yes (typed confirmation) | no | no | no |
| `add_paper_trade` (owner's own) | write | yes | `/trade` | yes | yes |

Rules (the agentic-commerce pattern, ARCHITECTURE.md section 10): identity from the channel's auth
(Vercel Authentication, Slack user id from a signed request, GitHub OAuth), never from arguments;
an idempotency key on every write; a per-day action budget and a kill switch per agent; every write
validated by the same Python validators as the CLIs; refusals and anything ambiguous go to Slack for
the owner; an injection test suite (instructions hidden in news titles, filings and Slack text) must
pass before release.

**Write path from the web tier.** The API appends the request to the MotherDuck `inbox` (as decided in
ARCHITECTURE.md section 9) and then dispatches the GitHub Actions workflow `onboard.yml`
(`workflow_dispatch`, fine-grained token limited to Actions on this repo). The workflow imports the
inbox (same validators), runs the deterministic onboarding for adds, commits to `data/`, and replies in
Slack. If the dispatch fails, the next scheduled run imports the inbox. The UI shows the request as
"pending" until the import is in `data/`.

### F11 Assistant chat (dashboard and Slack `/ask`)

A chat panel on every page and the Slack `/ask` command, served by a Vercel route calling the Claude
API (Sonnet) with the read tools of F10 only (writes stay buttons and forms). Answers cite ids and
"as of" times, never advise real trades, and say "not in the data" when it is not. Budget: a hard cap
of $20 per month set in the Anthropic console plus a code-side daily budget (about $0.65 per day);
over budget the panel says so. Conversations are kept 90 days in MotherDuck schema `app` (operational
log, not a fact store).

### F12 Dashboard: 10 pages (section 6)

## 4. Data: new kinds and read models

New append-only kinds (schemas in `scripts/marketbrief/core/schema_*.py`, `data/<market>/<kind>/`):

| Kind | One row per | Written by |
|---|---|---|
| `watchlist_events` | lifecycle event | F8 validator (CLI, inbox import) |
| `strategy_predictions` | strategy x company x horizon x day | pre-open run (rules, AI traders) |
| `strategy_abstentions` | AI trader x company x day it abstained or failed its gate | pre-open run |
| `paper_trades_settled` | settled trade x view | post-close run (F1 engine) |
| `trade_checks` | open trade x intraday check | intraday run (extends WS5 `intraday_checks`) |
| `eod_analyses` | market x day | post-close run, gated |
| `research_reviews` | market x week | weekly run |
| `news_impact` | market x week x category x status x materiality x horizon | weekly run |
| `command_log` | command from any channel (who, channel, tool, key, result) | MCP / CLI |

Existing kinds stay. `predictions` (the forecaster's calls) continue; the Opus combined trader's
predictions are written as `strategy_predictions` with `strategy_id = ai.combined.opus.v1`, and the
old kind keeps its scoring until the first review.

New read models (schema `rm`, same columns as ARCHITECTURE.md 4.1): `rm.home`, `rm.strategies`
(scoreboard), `rm.compare` (rule vs AI per market and per company), `rm.trades` (open and recent trades
per market and per ticker), `rm.lifecycle` (one prediction's path: made, checks, settled, explained),
`rm.companies` (active, inactive, pending requests), `rm.portfolio` (owner's, with EUR view),
`rm.review` (latest weekly report). Each is built by its feature's payload function and written by
the warehouse sync.

## 5. API (`/api/v1`, Next.js route handlers on Vercel)

Existing contract (api/openapi.yaml 1.0): markets, status, overview, watchlist, stock, bars, track
record, news, runs, portfolio, company requests, inbox, internal revalidate. Version 1.1 adds:

| Method and path | Returns / does |
|---|---|
| `GET /markets/{m}/home` | Home payload: top picks per family, today's rule vs AI, alerts, freshness |
| `GET /markets/{m}/strategies` | scoreboard: all strategies, both views, both horizons |
| `GET /markets/{m}/strategies/{id}` | one strategy: description, parameters, results, trades |
| `GET /markets/{m}/compare[?ticker=]` | rule vs AI head-to-head, per market or company |
| `GET /markets/{m}/trades[?ticker=&status=]` | open and settled paper trades |
| `GET /markets/{m}/stocks/{t}/lifecycle?date=` | one day's predictions with intraday path, settlement, explanation |
| `GET /markets/{m}/companies` | active, inactive, pending requests, amounts |
| `GET /markets/{m}/review` | latest weekly report and news-impact table |
| `POST /markets/{m}/companies` | add (Idempotency-Key) -> 202 pending |
| `POST /markets/{m}/companies/{t}/deactivate`, `/reactivate`, `/amount` | lifecycle actions -> 202 pending |
| `DELETE /markets/{m}/companies/{t}` | delete; requires body `{"confirm": "<ticker>"}` -> 202 pending |
| `POST /markets/{m}/paper-trades` | the owner's own paper trade -> 202 pending |
| `POST /chat` | assistant (streaming), read tools only, budget-checked |
| `POST /slack/commands`, `POST /slack/interactions` | Slack slash commands and the `/company` form (signature-verified) |
| `/mcp` | remote MCP endpoint for the Claude app (GitHub OAuth, owner only) |

Reads stay one keyed `SELECT` per request with tag-based caching (ARCHITECTURE.md sections 6-7).
Writes never touch `base` or `rm`; they go to `inbox` and dispatch the import (F10).

## 6. Pages (phone and laptop, Material 3 design system from design/)

Every page shows "as of" and freshness, the Paper label on any signal, degraded mode when the data
service is down, and works with keyboard and without colour alone.

| # | Page | Shows | Actions | Read model |
|---|---|---|---|---|
| 1 | Home | per market: top 3-5 picks across strategies (or "No proven strong signals today"), rule vs AI today and to date, open trades, alerts, last runs | switch market, open a company | `rm.home` |
| 2 | Watchlist | active companies: price, move, each family's prediction, open trades | open company, filter by sector | `rm.watchlist` |
| 3 | Company | decision card; predictions of every strategy with targets and ranges on the chart; today's path (intraday checks); settled results; why it moved; news with status; results digest; events | change amount, deactivate, ask | `rm.stock`, `rm.bars`, `rm.lifecycle`, `rm.trades` |
| 4 | Strategy lab | all strategies and baselines, both views and horizons; per strategy detail with parameters in plain words; back-test vs forward apart | open strategy | `rm.strategies` |
| 5 | Rule vs AI | head-to-head per market and per company: profit, win rate, error; the "why" from EOD analyses and the weekly report | open company | `rm.compare`, `rm.review` |
| 6 | Paper portfolios | per strategy (money view) and the owner's own (with EUR view) | add own paper trade | `rm.portfolio`, `rm.trades` |
| 7 | Track record | prediction accuracy over time, calibration, scoring bases apart | - | `rm.track_record` |
| 8 | News | news by company with verification status and impact category; news-impact table | open company | `rm.news`, `rm.review` |
| 9 | Companies | active, inactive (news, price, Reactivate), pending requests; amounts | add, deactivate, reactivate, amount, delete (typed confirmation) | `rm.companies` |
| 10 | Assistant | chat with sources and as-of times; also a side panel on every page | ask | `POST /chat` |

## 7. Integrations

| System | Role | Owner action needed |
|---|---|---|
| Claude Code routines | all computation and agents (schedules below); builds in cloud sessions | none |
| GitHub | source of truth (`data/`), CI, Actions workflow `onboard.yml` for writes from the web tier | create a fine-grained token (Actions: read and write, this repo only) for Vercel |
| MotherDuck | `market_brief`: `base`, `rm`, `inbox`, `app` | create a read-only token and an inbox-write token for Vercel |
| Vercel | new project for the Next.js app (directory `web/`), plus the existing `reports/` site until retired | create the project; add environment variables |
| Slack | existing app gains `/company`, `/trade`, `/ask` and interactivity pointing at the API | add the commands and the request URL in the Slack app settings (exact steps provided) |
| Claude app | custom connector to `/mcp` with GitHub sign-in | add the connector once `/mcp` is live |
| Anthropic API | dashboard chat and `/ask` | create a key with a $20 monthly limit |
| Neo4j | relationship graph, optional | none |

Routine schedule per market (sessions per market per day: 1 pre-open + 2 intraday + 1 post-close +
5 news = 9; plus 1 weekly and 1 monthly):

| Run | India | US | Contents |
|---|---|---|---|
| Pre-open (exists) | 08:10 IST | 08:15 New York | collect, features, model, rule strategies, 4 AI traders, gates, picks, sync, Slack morning picks |
| Intraday x2 (WS5) | 11:13, 14:13 IST | 12:27, 14:57 New York | trade checks, deviation explainer, alerts, sync |
| Post-close (new) | 16:15 IST | 16:45 New York | close bars, settlement, EOD analyst, sync, Slack close results |
| News (exists) | every 4 hours | every 4 hours | news, articles, clusters, sync |
| Weekly (exists, extended) | weekend | weekend | review, news-impact study, research director, weekly post |

## 8. How the UI connects to the backend

1. Pages are server-rendered by Next.js from `/api/v1` read endpoints (never MotherDuck directly from
   the browser); each payload carries `as_of`, `cutoff`, `built_at`.
2. Caching by tag per read model; the sync revalidates only changed pages, so opening the dashboard
   many times a day costs no database compute.
3. Actions post to the write endpoints with an idempotency key, show "pending", and turn into facts
   after the import commits and the next sync revalidates the page (minutes when the workflow dispatch
   works, else at the next run).
4. The chat panel streams from `/chat`; tool calls are shown as "looked at: ..." with links.
5. Charts: the vendored Lightweight Charts with our bars, targets and ranges.
6. Design: the Material 3 system and page designs from the design sessions are implemented as React
   components; the design builders' JSON shapes are aligned to the read-model payloads.

## 9. Non-functional rules

- All existing data, prediction, judging and safety rules hold. Free sources only, HTTPS allowlist,
  nothing run from fetched content, secrets only in environment variables, no email in requests.
- Cost guards: MotherDuck Lite (10 CU hours a month, ARCHITECTURE.md section 5 kill switch), Claude
  subscription use (AI traders as subagents of the existing pre-open session; Sonnet except one Opus
  trader), GitHub Actions minutes (onboarding only), Anthropic API $20 a month.
- Every number shown comes from stored data or deterministic computation; AI text cites ids and is
  gated.

## 10. Roadmap: stages for parallel cloud sessions

Principle: contracts first, then independent builds that each own their files, then consolidation.
Each stage runs in its own cloud session on its own branch, is judged before merge, and writes its
proposed shared-doc edits into `docs/ws/<stage>.md` as in waves 0-1.

**Stage A: contracts (one session, first; short).**
`api/openapi.yaml` 1.1 (section 5 endpoints and payload schemas), schemas of the new kinds (section 4),
`config/strategies.yaml` schema and the initial strategy set, `mcp/tools.yaml` (tool names, inputs,
outputs, permissions per channel), the F1 protocol module interface (function signatures and record
formats). Owns: `api/`, `mcp/tools.yaml`, `core/schema_lab.py`, `core/schema_lifecycle.py`,
`config/strategies.yaml`, `docs/ws/stageA.md`.

**Stage B: parallel builds (after A merges; one session each).**

| Stage | Builds | Owns | Needs |
|---|---|---|---|
| B1 Lifecycle | F8: watchlist as data, accessor, seed, onboarding pipeline, lifecycle CLI, inbox import, `onboard.yml` | `marketbrief/lifecycle/`, `scripts/company.py`, `.github/workflows/onboard.yml`, the accessor swap in readers of `tickers:` | A |
| B2 Lab | F1 engine, F2 strategies and baselines, F3 news-impact study, F7 scoreboard and luck test | `marketbrief/lab/`, `scripts/lab.py`, tests | A |
| B3 AI traders | F4 traders and gate, F6 EOD analyst and research director, post-close routine prompt | `.claude/agents/trader-*.md`, `eod-analyst.md`, `research-director.md`, `marketbrief/traders/`, `routine/POSTCLOSE_PROMPT.md` | A (writes predictions; B2 settles them) |
| B4 API | read models for section 4 (payload functions provided by B1-B3 via A's interfaces, stubbed until merged), `web/app/api/v1/*`, caching, revalidate | `web/app/api/`, `marketbrief/warehouse/rm_*` additions | A |
| B5 Tools and channels | `mcp` server (remote `/mcp`, GitHub OAuth), Slack commands and form, write endpoints, inbox, dispatch | `web/app/mcp/`, `web/app/slack/`, `web/lib/tools/`, `mcp/` | A |
| B6 Notifications | F9 Slack threads (morning, alerts, close, weekly) | `marketbrief/alerts/`, `scripts/alerts.py` | A |
| B7 Frontend | the 10 pages from the owner's design sessions, against A's contract with fixture payloads | `web/` except `app/api`, `app/mcp`, `app/slack`, `lib/tools` | A + page designs |
| B8 Assistant | F11 chat and `/ask` with budget | `web/app/api/chat/`, `web/lib/assistant/` | A |

B1 is the only stage that touches existing collectors (the accessor swap); every other stage reads
the watchlist through the accessor's interface from A, so they never edit the same files. B7 starts
with the shell, design system and Home and Company pages as the designs land.

**Stage C: consolidation (one session, last).** Wire the new runs into the routine prompts, create the
schedules (post-close, intraday, weekly), apply all proposed shared-doc edits, end-to-end run of both
markets, then switch on the new paper trading. The 2-month review clock starts that day.

**Stage D: after go-live of the app.** Retire the static pages after 2 weeks (decision 25); first
formal review at 2 months (decision 23).

## 11. Owner actions (when each stage needs them)

| When | Action |
|---|---|
| Before B2 merges | Confirm broker charges: Axis Direct plan (brokerage % per side, DP charge per sale) from a contract note; BUX order fee and FX fee from the BUX app or site |
| Before B4/B5 go live | Create the Vercel project; MotherDuck read and inbox tokens; GitHub fine-grained token |
| Before B5 Slack | Add `/company`, `/trade`, `/ask` and the interactivity URL to the Slack app |
| Before B8 | Anthropic API key with a $20 monthly limit |
| After B5 | Add the Claude app connector |
| At the first review | Set the maximum drawdown limit |
