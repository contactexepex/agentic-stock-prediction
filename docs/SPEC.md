# market-brief: product specification and parallel roadmap

Status: approved by the owner (decisions 1-52, 2026-10-07). It records every decision the owner made in the
question rounds of 2026-10-07 and turns them into features, data, API, pages, integrations and a
roadmap of waves that can be built in parallel cloud sessions. It builds on what is already merged
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
| 1 | Trade timing | Buy at the OPEN of D (the first session after the prediction is made); sell at the CLOSE of the horizon's exit session (decision 37). Prediction locked before D's open. No intraday trading. |
| 2 | 5-day horizon | Originally: kept as a research horizon (buy at the open of D, sell at the close of D+4). Superseded by decision 37: horizons N+1 to N+5, all first-class. |
| 3 | Down signals | Buy-only in both markets: a "down" prediction creates no trade (it is still scored as a prediction). |
| 4 | India share price above the amount | Skip the trade unless the company's amount is raised. Whole shares only in India. |
| 5 | US shares | Fractional shares: exactly the amount is invested. |
| 6 | Costs | India: Axis Direct. US: BUX (ABN AMRO), owner trades from the Netherlands. Charges in F1.6 (provisional until confirmed). Refined by decisions 49 and 52: the plans and charges the owner provided. |
| 7 | Trades per day | No limit on trades: every qualifying forecast is its own paper trade (accuracy view). The per-strategy money-view budget is superseded by decision 40. |
| 8 | Who is better | Headline = profit after costs on the same trades and amounts; beside it win rate, price-prediction error, worst losing streak, drawdown and a luck test. |
| 9 | AI traders | 3 on Sonnet (news & results; price pattern & market mood; combined) + 1 on Opus (combined), from day one. |
| 10 | AI sees the rule-based score | Mixed: the news and pattern traders are blind; both combined traders see the model score. |
| 11 | Currency (US) | Strategies are compared in USD ($1,000 per trade). The owner's own paper portfolio also shows EUR, including BUX's conversion fee and the rate change. Refined by decision 50: the USD comparison uses the market cost (the order fee, no FX); the FX markup and the portfolio fee are part of the owner's "your cost". |
| 12 | Delete company | Hide everywhere (tombstone): no display, no use, no collection, purged from derived stores; old records stay in git history, never shown. |
| 13 | Deactivated company | Shown in an Inactive section on the Companies page (news, price, Reactivate); out of picks, strategies and the watchlist; collection continues. |
| 14 | Allowed companies | Common stocks listed on NSE (India) or NYSE/Nasdaq (US). No BSE-only stocks, no ETFs. |
| 15 | Slack commands | Any member of the #market-brief channel may give commands. Delete is never available in Slack. |
| 16 | Dashboard users | Owner only, Vercel Authentication. |
| 17 | Pages | All 10 proposed pages (section 6; with decisions 30 and 35 the cockpit has 12). |
| 18 | Screens | Phone and laptop equally. |
| 19 | Charts | Our own charts from stored data (vendored Lightweight Charts); no TradingView widgets. |
| 20 | Dashboard actions | All: add, deactivate, reactivate, change amount, delete (delete dashboard-only, with confirmation). |
| 21 | Slack posts | Morning picks, close results, alerts, weekly report. |
| 22 | Claude app login | GitHub OAuth, the owner's account only. |
| 23 | Go-live review | First formal review 2 months after the new paper trading starts; go-live only if the bar (F7) is met, then monthly reviews. |
| 24 | Neo4j | Kept, off the critical path (nothing the dashboard needs depends on it). |
| 25 | Old static pages | Retired 2 weeks after the new app is live; Slack then links to the new app. |
| 26 | Amounts | Default ₹1,00,000 per trade (India) and $1,000 (US); override per company, either market. |
| 27 | Growth | At most 50 companies within a year. |
| 28 | Dashboard chat | Claude API, hard cap $20 per month. |
| 29 | Intraday checks | Monitoring only (no trades). |
| 30 | Home picks | Agreement ranking: companies ranked by how many strategies would buy them, then by average probability. Clicking a company opens a stock strategy page with the agreement ranking, the best strategy, and all strategies ranked by profit after costs. |
| 31 | Pre-open run | Starts 30 minutes earlier: India 07:40 IST, US 07:45 New York time (schedules changed 2026-10-07). |
| 32 | Frontend order | This spec is merged first; the owner's design sessions then update the page designs from it; the frontend stage builds from those designs. Refined by decision 48: the design track designs the pages from W1's data catalogue, and the API follows the approved mockups (section 10). |
| 33 | Rule changes | Both approved: companies as validated data records (F8.1), and the prediction-rule changes for strategies (F2.6). |
| 34 | Orchestrator defaults | Accepted: money-view budget ₹5,00,000 / $5,000 per strategy, at most 5 trades a day (this item superseded by decision 40); weekly research run Saturday 10:00 local; chat history kept 90 days; the Slack add form asks market, symbol and optional amount only. |
| 35 | Help page | Kept as page 12. |
| 36 | Old commit 85416b0 | Kept with a git tag (the owner creates it on GitHub; this session may push branches but not tags). |
| 37 | Horizon N+k | Buy at the open of D on any weekday; N+k = sell at the close of the k-th market session after D, skipping weekends and the market's holidays (example: bought Friday, N+1 = Monday's close). Horizons N+1 to N+5 now; the horizon list is a setting so N+10 (two weeks) and about N+21 (a month) can be added later without redesign. The old "5-day" records (sold at D+4) keep their definition and label and are never pooled with N+5. |
| 38 | Who forecasts which horizons | Rule strategies and baselines: N+1 to N+5. AI traders: N+1, N+3 and N+5. |
| 39 | Horizon on screens | A horizon selector (N+1 to N+5) on Home and the stock strategy page, opening on N+1; Slack morning picks show N+1 plus each pick's strongest other horizon (the other horizon with the highest agreement count; ties: the shorter). |
| 40 | Trade size and count | No budget per strategy. Maximum per trade ₹1,00,000 / $1,000 (the owner's words), refined by decision 44: each paper trade uses the company's amount, ₹1,00,000 / $1,000 unless overridden; one stock may have several open trades at once (one per strategy and horizon). The goal is statistics on prediction accuracy (reaching the predicted price within the predicted window) and profit. |
| 41 | Strongest strategy | For a stock on a day: in each family (rule-based, AI), the strategy with the highest profit after costs on that stock so far, once it has at least 20 settled trades on it; before that, the family's best by profit after costs across all stocks. |
| 42 | Head-to-head picks | Both pick rules compete: "best expected gain" (the horizon with the highest probability-weighted profit after costs) and "highest probability" (the horizon the strategy is most sure of). Each day, per company, the strongest rule strategy and the strongest AI trader each get one trade of the company's amount (₹1,00,000 / $1,000 unless overridden, decision 44) per pick rule (up to 4 head-to-head trades per company per day). Comparisons run across families (rule vs AI) and within each (rule vs rule, AI vs AI, gain-pick vs probability-pick), with heatmaps and charts over time. |
| 43 | Reasons for every trade | Every settled trade gets an automatic reason (computed, no AI: the move split into market, sector, news and company-specific parts; target and range hit or missed). AI writes plain-language reasons for the head-to-head trades and the day's biggest wins and misses. |
| 37a | Ready before accurate | The horizon functionality is built and running from the start even though early predictions will be inaccurate; accuracy is expected to improve as data accumulates. |
| 44 | Amount cap vs overrides | ₹1,00,000 / $1,000 is the default amount of every trade; a per-company override may raise or lower it (e.g. a stock whose single share costs more than ₹1,00,000). Comparisons therefore report % returns beside money. |
| 45 | News: edited headline | The same article at the same link is one item; a later headline change is kept as a headline-update note on it (latest headline as of a time is shown). |
| 46 | News: two markets | An article may be stored once per market (India, US), never twice within a market. |
| 47 | News de-duplication timing | Fixed now as a small batch, before the waves (Wave 0). |
| 48 | Waves | The wave plan of section 10: each session in its own cloud session, built, judged and merged to main in parallel; sessions merge to main themselves after a PASS (no pull requests); the orchestrator watches and resolves clashes. More automation and autonomy, less owner attention. |
| 49 | India broker plan | Axis Direct NRI, 0.75% plan, Normal tier, Non-PIS (charges in F1.6; owner-provided from the published schedule, marked verify in `config/costs.yaml` `broker:` until a contract note confirms them). |
| 50 | Two cost views on every trade | "Market cost" = brokerage + statutory taxes + exchange/regulatory fees (US: the order fee, SEC fee and FINRA TAF, no FX); strategies are ranked on it. "Your cost" = market cost + the owner-specific items: India the ₹200 NRI reporting charge on the buy date and on the sell date and the DP charge; US BUX's FX markup of 0.75% each way and the 0.20% a year portfolio fee pro-rated over the calendar days held. The go-live bar and the owner's money decisions use your cost. |
| 51 | Cost-viable flag | A prediction or pick is `cost_viable` when its expected gain after your cost is positive: P(up) × move − (1 − P(up)) × loss − your cost > 0, with move and loss the conditional expected rise/shortfall of the pick (lab/gain.py); null without a probability or 80% range. It is still made, traded and scored either way; picks and Slack show the flag. (Owner decision in the B6 session, 2026-10-07, replacing the first wording "predicted move exceeds your cost".) |
| 52 | US broker plan | BUX Basic: €0.99 per order, FX markup 0.75% on each EUR↔USD conversion, 0.20% a year portfolio fee (charges in F1.6; owner-provided, marked verify in `config/costs.yaml` `broker:`). |

Proposals made by the orchestrator that are still open (decision 34 accepted the weekly
research time, the chat-log retention and the Slack form; the owner may change any of these): every
command logged with who sent it; one Slack thread per market per day plus a weekly post; design widths
390 px and 1280 px; the post-close times of section 7 (the intraday times are WS5's existing
schedules); the Opus trader being the extended forecaster; the AI reasons for the day's 5 biggest wins
and 5 biggest misses (F6); top 5 picks on Home and in Slack; baselines excluded from the head-to-head
(F1.7); the drawdown proposal (F7.2); no bulk-storage move within a year (git +
MotherDuck handle 50 companies).

## 2. Words used in this document

- **Strategy**: a frozen rule set or AI trader that turns stored data into predictions. Each has an
  `strategy_id` (e.g. `rule.model_news_1x.v1`, `ai.news_results.sonnet.v1`). Changing a strategy makes
  a new id; an id's behaviour never changes after its first live day.
- **Prediction**: per strategy, company, horizon and day: direction (up/down), probability, target
  price (expected close), a price range, and the evidence. Made before the open of D.
- **Paper trade**: what a prediction turns into under the protocol (F1): only "up" predictions above
  the strategy's threshold trade.
- **Account**: one strategy's trades under one view (accuracy or head-to-head).
- **Settlement**: the deterministic computation of a trade's outcome from stored bars after the exit
  close.
- **Lifecycle of a prediction**: made (pre-open) -> monitored (intraday checks) -> settled (after the
  close) -> explained (end-of-day analysis) -> aggregated (scoreboard, weekly review).

## 3. Features

Each feature lists what it does, the rules it must keep, and when it counts as done. Where an existing
part already does it, the feature says "exists" and what changes.

### F1 Paper-trading protocol (one engine for every strategy)

1. **Timing.** A prediction made at `made_at` before the open of D enters at D's official open and
   exits at the official close of the k-th session after D for horizon N+k (k = 1..5, decision 37;
   sessions from the market calendar, so weekends and holidays are skipped). `made_at` must be before D's open
   (checked against the market calendar); a later prediction is refused. No open price on D (halt,
   missing bar): no trade, recorded as `no_entry`. No exit close: settled on the next stored close and
   flagged `exit_delayed`. Sessions come from the market calendar (special sessions count).
2. **Buy-only.** Only `direction = up` with probability >= the strategy's threshold creates a trade.
   Down predictions are scored as predictions only.
3. **Amount.** Per company: the override if one is active at `made_at`, else the market default
   (₹1,00,000 India, $1,000 US). Overrides are watchlist events (F8) and may be higher or lower than
   the default (decisions 4, 26 and 44: e.g. raised for a stock whose single share costs more than
   the default). Every trade uses exactly the company's amount.
4. **Quantity.** From D's raw (unadjusted, `ohlc_raw`) open, as an investor would buy: India
   `floor(amount / open)` whole shares; 0 shares (one share costs more than the amount) = trade
   skipped, recorded `skipped_price_above_amount`. US: `amount / open` fractional, 6 decimals. The
   quantity is stored with the trade and never recomputed.
5. **Prices.** A split or bonus recorded in `adjustments` with an ex-date inside the holding period
   multiplies the stored quantity by its ratio for the exit (as a brokerage account would show it);
   entry and exit prices are the raw official open and close. A later correction of an adjustment
   (`supersedes`) re-settles the trade as a new settlement row (append-only), never an edit.
6. **Costs** (applied to entry and exit value; the table lives in `config/costs.yaml`, each value
   marked verify with its source; engine code `marketbrief/lab/costs.py`). Owner decisions 49-52 (2026-10-07):
   the broker values below are **owner-provided from the brokers' published schedules and marked verify** in
   `config/costs.yaml` `broker:`; no contract note (India) or BUX fee page (US) has confirmed them yet. Each charge
   belongs to one of the two cost views of decision 50: **market** (brokerage, statutory taxes and
   exchange/regulatory fees; strategies are ranked on it) or **your** (the owner-specific items added to the market
   cost; the go-live bar and the owner's money decisions use it).

   | Market | Charge | Value | View | Source |
   |---|---|---|---|---|
   | India (Axis Direct NRI, 0.75% plan, Normal tier, Non-PIS; decision 49) | Brokerage, delivery | 0.75% of the order value each side, at least ₹50 per order | market | owner-provided; verify with a contract note |
   | India | GST | 18% on brokerage + exchange transaction charge + SEBI fee | market | owner-provided; verify |
   | India | STT | 0.1% each side | market | owner-provided (agrees with `config/costs.yaml`); verify |
   | India | Stamp duty | 0.015% on the buy side | market | owner-provided (agrees with `config/costs.yaml`); verify |
   | India | NSE transaction charge, SEBI fee | 0.00307% and 0.0001% each side, as already in `config/costs.yaml` | market | as documented there (search-only sources) |
   | India | NRO Non-PIS reporting charge | ₹200 per trade date: the full ₹200 on a paper trade's buy date and again on its sell date | your | owner-provided; verify with a contract note |
   | India | DP charge per scrip sold | provisional: ₹30 or 0.04% of the sale value, the higher | your | SECONDARY SOURCE, unchanged; verify with a contract note |
   | India | Demat AMC | about ₹885 a year: an account charge, in no trade's cost | none | owner-provided; verify |
   | US (BUX Basic; decision 52) | Order fee | €0.99 per order, converted at the EUR/USD close on or before that side's session | market | owner-provided; verify with BUX |
   | US | FX markup | 0.75% of the value on each EUR↔USD conversion (on the buy and on the sale) | your | owner-provided; verify with BUX |
   | US | Portfolio fee | 0.20% a year on the entry value, pro-rated over the calendar days from D to the exit session | your | owner-provided; verify with BUX |
   | US | SEC fee, FINRA TAF | as already in `config/costs.yaml` | market | official, as documented there |

   No GST is added to the reporting and DP charges (the owner's facts put GST on brokerage + exchange + SEBI only).
   Each cost line is rounded to cents and a view's total is the sum of its rounded lines.

   **Round trip at the default amount** (flat price, entry value = exit value; F1.7.3 and decision 51 use the same
   arithmetic at the latest close `C`), from `lab/costs.py`:
   - India, ₹1,00,000: brokerage 2 × ₹750 = ₹1,500.00; STT ₹200.00; exchange ₹6.14; SEBI ₹0.20; stamp duty ₹15.00;
     GST 18% × (1,500.00 + 6.14 + 0.20) = ₹271.14. **Market cost ₹1,992.48 = 1.99%.** Plus NRI reporting 2 × ₹200
     and the provisional DP charge ₹40.00 (0.04% of ₹1,00,000 > ₹30): **your cost ₹2,432.48 = 2.43%.**
   - US, $1,000 at an example EUR/USD of 1.17 (the stored close is used): order fee 2 × €0.99 × 1.17 = $2.32; SEC
     fee $20.60 per million on the sale = $0.02; FINRA TAF $0.00 until 2026-12-31. **Market cost $2.34 = 0.23%.**
     Plus the FX markup 0.75% on the buy and on the sale = $15.00 and the portfolio fee $0.01 for a one-day hold
     ($0.04 over 7 calendar days): **your cost $17.35 = 1.74%** for N+1 on consecutive weekdays. FX dominates.

   The USD comparison (decisions 11 and 50) applies the order fee converted at the stored EUR/USD close and leaves
   the FX markup to your cost. Session B2 adds `EURUSD=X` (Yahoo daily close) as a US cross-market symbol of role
   `fx` (collected as bars only, not a model feature); until a rate is stored, a US settlement waits
   (`waiting_for_eurusd`).
7. **Two views** (decisions 40-42), both from the same predictions:
   - **Accuracy view:** every qualifying prediction (each strategy, company and horizon) is its own
     trade of the company's amount (₹1,00,000 / $1,000 unless overridden, decision 44); no limit on the number of trades,
     and one stock can have several open trades at once.
   - **Head-to-head view:** each day, per company, up to four trades: {strongest rule strategy,
     strongest AI trader} x {best expected gain, highest probability}. Exact rules:
     1. Candidates. Rule family = the rule strategies of F2 (baselines excluded: they are the
        yardstick, not contenders; proposal). AI family = the four AI traders. A candidate horizon of a
        strategy for the company is one where its prediction is "up" with probability at or above the
        strategy's threshold.
     2. "Strongest" (decision 41): rank the family by profit after costs on this company in the
        accuracy view, all horizons pooled, counting only strategies with at least 20 settled trades on
        it; strategies below 20 are ranked after them by profit after costs across all companies (ties:
        more settled trades, then the lower strategy id). Strategies with no settled trade at all rank after
        every strategy with one (B2 correction); a re-settled trade counts once, at its newest settlement. Take the highest-ranked strategy that has at
        least one candidate horizon today. No such strategy: no head-to-head trade for that family and
        company today, recorded as `no_candidate`.
     3. Pick rules, applied to that strategy's candidate horizons, computed pre-open from the latest
        stored close `C` (the entry open is not known yet), all in percent of the trade amount:
        `move` = E[X / C − 1 | X > C] and `loss` = E[1 − X / C | X < C], in % of C, where the exit close X is
        read as normal with mean = the strategy's target and sigma = (hi80 − lo80) / (2 × 1.2816) of its 80%
        range for that horizon (`marketbrief/lab/gain.py`); `costs` = the market-cost round trip of the
        company's amount at `C` (F1.6; ranking uses the market cost, decision 50) as a percent of the amount;
        expected gain = `p x move - (1 - p) x loss - costs`; "best expected gain" = the horizon with the highest
        expected gain per session held (expected gain / k; ties: the shorter horizon; owner decision of
        2026-10-07) (B2 correction: the draft, `move = target / C - 1` and `loss = 1 - range_low / C`, compared
        the band's low edge with its centre and always picked N+1; ranking the gain per trade would always pick
        N+5 at equal p); "highest probability" = the horizon with the highest `p` (ties: the shorter horizon).
        A prediction whose amount buys no whole share at C is no candidate. The pick lists the strongest
        strategy's expected gain at every horizon it predicted for the company; only the qualifying ones
        (`eligible`) can be picked.
     4. Both picks are recorded even when they name the same horizon, so each pick rule's results stay
        complete; each pick stores the ranking it came from and its expected-gain number.
     5. **Cost-viable flag** (decision 51). At pick time, every qualifying prediction of D and every pick gets a
        `cost_views` row (and each pick candidate the same fields): `expected_move_pct` = (target / C − 1) × 100,
        the round trip at `C` in both views (`market_cost_pct`, `your_cost_pct`; the US portfolio fee over the
        calendar days from D to the planned exit), `expected_gain_your_pct` = `p x move - (1 - p) x loss -
        your_cost_pct` with the move and loss of item 3, and `cost_viable` = `expected_gain_your_pct > 0` (null
        without a probability or an 80% range, e.g. the always-up and momentum baselines, and when the amount
        buys no whole share at C). The flag never stops a prediction or a trade: it is made, traded under F1.2 and
        scored either way, and a non-viable candidate can still be picked (owner decision of 2026-10-07).
8. **Locked before the open.** Predictions are appended to `data/` and pushed before D's open; the
   settlement refuses any prediction whose `made_at` is after the entry open or whose record was
   first committed after it (checked from git when available).
9. **Settlement** is deterministic and re-runnable: same stored bars give the same result. Each trade
   records entry, exit, quantity, gross and net P&L (₹ or $), return %, costs under **both cost views** (decision
   50: `costs`, `cost_lines`, `net_pnl` and `return_pct` of `paper_trades_settled` are the market cost; the
   settlement's `cost_views` row holds `your_costs`, `your_cost_lines`, `net_pnl_your` and `return_pct_your`,
   joined on `record_id` = the settlement id), target error (exit close
   vs predicted target, %), range hit (exit close inside the predicted range), and status, plus the
   price-reached measures of decision 40:
   - `target_reached`: true when any session's high from D to the exit session (inclusive) is at or
     above the predicted target (adjusted bars, so a split inside the window does not distort it);
   - `target_reached_session`: the first such session (1 = D, ..., k+1 = the exit session);
   - `max_favourable_pct` and `max_adverse_pct`: the highest high and lowest low in the window
     relative to the entry price.
10. **Reasons** (decision 43): every settled trade stores an automatic reason: the entry-to-exit move
    split into market (benchmark), sector (sector index or peers), news (verified news on the company
    inside the window, with ids), and the company-specific rest; whether the target and the range were
    hit; plus a reason code (e.g. `market_down`, `sector_drag`, `news_positive`, `target_reached`). These
    feed the heatmaps. AI-written reasons are F6.
11. **Owner's own paper portfolio** (exists, WS4: `scripts/portfolio.py`) keeps manual trades; it gains
    the EUR view for US trades (rate change + FX fee) and reads amounts and costs from the same place.

Done when: a fixture week of predictions settles to hand-checked numbers for both markets, both views,
all five horizons, including a Friday buy with N+1 settling on Monday and the skip, no-entry, delayed
exit, split and holiday cases; the engine is the only place P&L is computed.

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
4. **Forward**: every rule strategy and baseline predicts daily for every active company and every
   horizon N+1 to N+5 in the pre-open run (decision 38); each prediction carries a target price and a
   range; the predictions go through F1.
5. Initial set: about 8 rule strategies + 3 baselines, chosen so each differs from the others in one
   parameter (so a difference in results points to that parameter).
6. **Rule change (prediction rules for strategies).** CLAUDE.md's prediction rules were written for the
   forecaster's calls. For `strategy_predictions` they apply as follows:
   - Every strategy (rule, baseline, AI): no prediction for a ticker with indicator quality `BLOCKED`
     or with earnings within 1 day (`days_to_earnings` <= 1); ranges come from `ranges.py` and may only
     be widened; id = `<strategy_id>:<as_of_date>-<ticker>-<horizon>d`, skipped if it exists;
     `as_of_date` = the latest price date for the ticker.
   - Rule strategies, baselines and the pattern trader cite no news, so `evidence_ids` holds the
     inputs instead: the feature snapshot and model score ids they used (no news id needed).
   - A strategy that uses news (rule strategies with a news weight, the news and combined traders)
     follows DESIGN.md 3b exactly: rumour and promotional items carry zero weight, the first cited news
     id must be `confirmed_primary` or `corroborated` as of `made_at`, single-source or unverified items
     lower the probability.
   - **Rule change**: `horizon_days` may be 1 to 5 (CLAUDE.md allows only 1 or 5); a horizon N+k means
     the close of the k-th session after D (decision 37), not the old D+(k-1) close.
   - The `confidence` 0.50-0.90 band applies to AI traders; rule strategies output the calibrated
     probability as is (the threshold decides whether it trades).
   - Regimes. AI traders lower their probability in `EVENT_HEAVY` and `UNSTABLE` regimes, as CLAUDE.md
     says. **Rule change** for rule strategies and baselines: they do not lower the probability by
     judgment; a strategy either has a regime filter (no trades in those regimes) or not, and the
     scoreboard reports every strategy per regime, so the effect is measured instead of assumed.
   - Model anchor. The combined traders (Sonnet and Opus) see the model score and are bound by the
     forecast-v11 anchor: `model_prob` = the score, `agent_adjustment` within +-0.10 with a reason,
     direction and probability from their sum. The blind traders (news, pattern) do not see the score
     and are not anchored (**Rule change**: the anchor binds only predictions made with the score in
     view).
   - Track-record calibration. AI traders see their own per-confidence-band track record in their
     input and must lower confidence or abstain where a band hits less often than stated, as
     CLAUDE.md says. Rule strategies built on the signal model start from its Platt-calibrated
     probability; news weights and other parameters shift it by fixed rules, and baselines (always-up,
     momentum) carry no probability. For all of them calibration is measured on the scoreboard, not
     adjusted during a run; thresholds and weights change only through new strategy versions approved
     by the owner (F6.2) (**Rule change** for rule strategies and baselines).

7. **Horizons as a setting.** The horizon list lives in `config/strategies.yaml` (`horizons: [1, 2, 3,
   4, 5]`), read by the signal model, `ranges.py`, the strategies and the scoreboard (B10 moves
   `config/ranges.yaml` `horizons:` to read it); adding 10 or 21 later is a config
   change plus a model refit, no code change. Today the signal model and `ranges.py` support only
   horizons 1 and 5 (`HORIZONS = (1, 5)` in `constants/model.py`, `constants/prediction_rules.py`,
   `constants/dashboard.py` and `portfolio/proof.py`; `horizons: [1, 5]` in `config/ranges.yaml`; a
   hard-coded 5 in `intraday/rows.py`). The old windows differ from decision 37:
   - published ranges, 1d: from the as-of close to D's close (`range_math.py` `close.shift(-horizon)`,
     `range_context.py`); 5d: to D+4's close;
   - direction calls scored close-to-close (before `call_scoring.from`, 2026-10-08): 1d ends at D's
     close, 5d at D+4's close;
   - open-to-close model labels and calls: 1d = open of D to close of D+1, which IS N+1; 5d = open of D
     to close of D+4, which is not N+5.
   Old records keep their definition and get a label: `legacy_cc` (close-to-close and the old ranges),
   `legacy_5d_d4` (open-to-close 5d). They are never pooled with the new horizons, except open-to-close
   1d, which equals N+1 and may be pooled with it. Session B10 extends the model, ranges, scoring and
   calibration to N+1..N+5 with the decision-37 definition (new labels, a refit per horizon, ranges
   per horizon).
8. **Visual statistics** (decision 42): heatmaps of win rate and profit after costs by strategy x
   horizon, strategy x company and strategy x reason code, each over time (weekly), plus cumulative
   profit lines per strategy and per pick rule; on the Strategy lab and Rule vs AI pages.

Done when: the registry validates; the pre-open run writes one prediction per strategy x company x
horizon; back-test and forward results are stored separately; adding a strategy is a config change only.

### F3 News-impact study

For every news category (event type), verification status and materiality level: the average move of
the stock over each horizon N+1..N+5 relative to its benchmark and sector (abnormal return), with
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
   | `ai.news_results.sonnet.v1` | Sonnet | news (with verification status), results digests, filings, events | what happened to the company |
   | `ai.pattern_mood.sonnet.v1` | Sonnet | prices, indicators, regime, global cues, sector moves | how the stock and market behave |
   | `ai.combined.sonnet.v1` | Sonnet | everything above + the signal model's score and explanation | combine rules and judgment |
   | `ai.combined.opus.v1` | Opus | the same as combined Sonnet | the existing forecaster, extended to the protocol; tests whether the stronger model helps |

2. Each runs in the pre-open run (as subagents of the existing daily session, not separate sessions)
   and writes per active company and for horizons N+1, N+3 and N+5 (decision 38): direction, probability, target price, range, up to 3
   evidence ids, and a reason of at most 60 words. Timing: with the pre-open run moved 30 minutes
   earlier (decision 31) the run has about 95 minutes (India) and 105 minutes (US) before the open; the traders run in parallel
   and a trader that has not passed its gate 15 minutes before the open abstains for that day
   (recorded). Wave 5 measures the run's duration on both markets before go-live. A deterministic gate (shared with the existing
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

1. **Post-close run** per market (new; India 17:45 IST, US 18:15 New York time, i.e. at least 120
   minutes after the close, because a session's bar counts as final only then: `BAR_SETTLE_MINUTES`
   in `constants/calendar.py`): collect the day's close, settle every trade whose exit was today (F1), then the **EOD analyst** (Sonnet) writes per
   market: today's result per strategy family (rule vs AI) and per pick rule; a reason of at most 60
   words for every head-to-head trade settled today and for the day's 5 biggest wins and 5 biggest
   misses across all trades (decision 43); each grounded in the trade's automatic reason (F1.10) and
   citing ids; a gate checks ids and numbers (like `lessons.py`).
2. **Weekly research director** (Opus, in a new weekend run on Saturday, separate from the existing
   weekly review, which stays step 10a of the first pre-open run of the ISO week): reads the scoreboard (F7), the news-impact study
   (F3), the week's EOD analyses and lessons; writes the weekly report: who is ahead and why, which
   information helped, and proposals (new strategy versions, weights, thresholds) as config diffs for
   the owner to approve. It changes nothing by itself.
3. The existing reflector lessons continue for settled calls.

Done when: a settled day produces an EOD analysis that passes its gate; the weekly report lists every
proposal as an approvable diff.

### F7 Scoreboard and the go-live bar

1. Per strategy, per market, per horizon, per company, per pick rule (head-to-head) and overall, for
   both views: trades, profit
   after costs (headline), return %, win rate, target-reached rate (share of trades with
   `target_reached`, F1.9) and the median session it was reached, average target error %, range-hit
   rate, worst losing
   streak, maximum drawdown, and a luck test (bootstrap interval of the mean net return; multiple-
   testing correction across all strategies compared). Rule vs AI head-to-head on identical
   company-days; rule vs rule and AI vs AI within each family; gain-pick vs probability-pick.
   Baselines on the same table. Money and return figures are shown under both cost views (decision 50):
   strategies are ranked on the market cost; the your-cost figures (net profit, mean return, win rate, worst
   losing streak, drawdown and the luck test) sit beside them.
2. **Go-live bar** (owner-approved; decision 50: measured on **your cost**): at least 2 months of forward paper
   trading and about 300 trades per strategy (accuracy view; proposal: counted per strategy and horizon once the
   owner agrees); beats the best baseline after your cost with the corrected luck test (on `return_pct_your`)
   excluding zero; maximum drawdown of the your-cost net P&L within the owner's limit (to be set at the first
   review; proposal: a cumulative loss of 10 times the default per-trade amount, i.e. ₹10,00,000 / $10,000, on the
   strategy's accuracy-view trades; costs alone take about ₹2,432 / $17.35 per trade at the default amount (F1.6),
   about ₹7,29,744 / $5,205 over 300 trades, so a strategy that only breaks even before costs uses about 73%
   (India) or 52% (US) of the limit in its first 300 trades); holds in calm and volatile regimes. The owner's own
   money decisions use your cost too. First formal review 2 months after
   F1 goes live; then monthly. A strategy that meets the bar is "proven"; only proven strategies may show
   Strong Buy (the existing WS4 rule generalised to strategies).

Done when: the scoreboard read model exists for both markets and both views and the review report
states each strategy's position against the bar.

### F8 Company lifecycle (watchlist as data)

1. **Rule change** (proposed by the orchestrator so that decisions 12-15 and 20 can work at runtime;
   approved by the owner, decision 33): the list of companies moves from
   `config/markets/<market>.yaml` `tickers:` into append-only records `data/<market>/watchlist_events/`
   (`add`, `deactivate`, `reactivate`, `delete`, `set_amount`), gated by a deterministic validator
   instead of a judge review. Market-level config (calendar, benchmark, sectors, feeds) stays in config
   and keeps its judge review. The current 40 companies are seeded as `add` events with
   `effective_from` = the start of stored history and `recorded_at` = the seeding time, so history
   stays continuous and the record is honest about when it was written.
2. **States**: `active` (collected, predicted, traded), `inactive` (collected, not predicted or traded),
   `deleted` (not collected, not shown, excluded on read everywhere; derived stores purge it).
   **The loader is the switch:** `load_market` in `core/market_config.py` builds the company lists from
   the watchlist events as of the run's clock (MB_NOW-aware) instead of the config file:
   `cfg["tickers"]` = every collected company (active and inactive, never deleted), the membership of
   `cfg["sectors"]` rebuilt the same way (each company's sector is set at onboarding and stored on its
   `add` event), and `cfg["active_tickers"]` = active companies only. Existing code that collects keeps
   reading `cfg["tickers"]` unchanged. Existing code that predicts, publishes ranges or picks, trades,
   or displays the watchlist (reports, dashboard, warehouse read models, Slack digest) must show active
   companies only (decision 13; inactive ones appear only in the Companies page's Inactive section), so
   those call sites switch to `active_tickers` and active sector membership. W1 lists every
   existing reader of `cfg` tickers and sector lists, classifies each as collect, predict or display,
   and assigns each predict or display call site to exactly one session: the session that owns the file
   (B2 `portfolio/`, B4 `warehouse/`, B9 `intraday/`), else B1. The accessor
   `watchlist(market, as_of, state)` serves replays and new code.
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
   history (decision 12). Because a deleted company is never used, every scoreboard and track record
   is computed without it from then on, so strategy results shown after a delete can differ from those
   shown before it.
6. Every event records who asked, through which channel, and the idempotency key.
7. **Confirmation in Slack**: `/company add` opens a form (market, symbol, optional amount); on submit
   the system resolves the identifiers and shows a summary (name, exchange, sector, Yahoo symbol, CIK,
   amount) with Confirm and Cancel buttons; only Confirm starts the onboarding. Deactivate and amount
   changes show the same confirm step.

Done when: add, deactivate, reactivate, set amount and delete work end to end from the CLI on a
fixture company; the seeded watchlist reproduces today's outputs byte for byte (golden harness).

### F9 Notifications (Slack)

One thread per market per day in `#market-brief`: (1) morning picks before the open (top 5 per
market by agreement at N+1, each also showing its strongest other horizon (decision 39), with family,
probability, target, amount, Paper label, whether it is viable at the owner's cost (expected gain after
your cost > 0), and today's head-to-head trades (up to four) per pick, each with its flag);
(2) intraday alerts in the same thread (a flagged open trade, material news on a company with an open
trade); (3) close results (each settled trade, rule vs AI today); plus (4) the weekly report as its own
post, and onboarding confirmations as replies to the command that asked. Nothing is posted outside
these runs and replies.

Built by B6 (`scripts/alerts.py`, docs/ws/b6.md). Owner decisions of 2026-10-07 refine it:
- **Viable at your costs.** Each morning pick and head-to-head trade with stored cost numbers says whether it is
  viable. Viable means the
  expected gain after your cost is above zero: P(up) × move − (1 − P(up)) × loss − your round-trip cost > 0, all
  in % of the amount (the F1.7.3 formula with the owner's cost). "No pick clears your costs today" when none does.
  Non-viable picks stay listed.
- **Close results.** Every head-to-head trade, then the 10 biggest wins and the 10 biggest losses of the rest,
  then the count of the others with a pointer to the dashboard. Each trade shows the net after market costs and,
  beside it, after your costs; a family total shows the after-your-costs figure only when every trade in it has
  one.
- **Corrections.** A trade re-settled after its day's close post gets one correction reply in that day's thread.
  This covers the last 30 days; the original post stays.
- **Intraday alerts.** They come from B9's alerts feed (`intraday_alerts`): new flagged open trades, and every
  material news item on a company with an open trade.
- **One thread.** From Wave 5 the morning picks open the day's thread, and the existing daily brief, its charts and
  report reply in it.
- **No bot token.** Without the token the posts go out unthreaded through the incoming webhook to #market-brief.

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

**Reaching the tools from outside Vercel Authentication.** The dashboard project stays behind Vercel
Authentication. Slack and the Claude app cannot sign in to it, so the same `web/` app is deployed as
a second Vercel project, the gateway (`MB_GATEWAY=1`), without Vercel Authentication; in gateway mode
its middleware serves only `/slack/*` (every request verified with Slack's
signing secret and refused when older than 5 minutes), `/mcp` (GitHub OAuth; only the owner's
GitHub account is accepted) and the OAuth routes the MCP sign-in needs (`/.well-known/oauth-*`,
authorize, token and callback). It exposes no pages and no `/api/v1` routes; it holds only what the tool
layer needs (the MotherDuck read token, the inbox token, the dispatch token, the Anthropic key for
`/ask`). No bypass secret is ever put in a URL.

**Write path from the web tier.** The API appends the request to an inbox (ARCHITECTURE.md section 9)
and then dispatches the GitHub Actions workflow `onboard.yml`
(`workflow_dispatch`, fine-grained token limited to Actions on this repo). The workflow imports the
inbox (same validators), runs the deterministic onboarding for adds, commits to `data/` (pull, rebase
and retry so it never races a routine's push), and replies in Slack. If the dispatch fails, or if a
source refuses GitHub's runners (to be verified in session B1 for NSE, Yahoo and SEC), the next
scheduled run imports the inbox. The inbox lives in its own MotherDuck database `market_brief_inbox`
written by a separate service account (the Lite plan has 2), because MotherDuck tokens are not
scoped per schema: a leaked inbox token cannot touch `market_brief`. This changes ARCHITECTURE.md
sections 1, 2, 3, 8 and 9 (schema `inbox` inside `market_brief`); session B4 proposes the edits in
`docs/ws/b4.md` and the orchestrator applies them. The importer
(`onboard.yml` and the routine runs) reads the inbox with that account's token
(`MOTHERDUCK_INBOX_TOKEN`, stored in the cloud environment and as a GitHub Actions secret). The UI shows the request as
"pending" until the import is in `data/`.

### F11 Assistant chat (dashboard and Slack `/ask`)

A chat panel on every page and the Slack `/ask` command, served by a Vercel route calling the Claude
API (Sonnet) with the read tools of F10 only (writes stay buttons and forms). Answers cite ids and
"as of" times, never advise real trades, and say "not in the data" when it is not. Budget: a hard cap
of $20 per month set in the Anthropic console (spend limits apply per workspace, so the key lives in
a dedicated workspace with that limit) plus a code-side daily budget (about $0.65 per day);
over budget the panel says so. Conversations are kept 90 days in MotherDuck schema `app` (operational
log, not a fact store).

### F12 Dashboard: 12 pages (section 6)

The 10 pages of decision 17, the stock strategy page of decision 30 and the Help page of decision 35.

## 4. Data: new kinds and read models

New append-only kinds (schemas in `scripts/marketbrief/core/schema_*.py`, `data/<market>/<kind>/`):

| Kind | One row per | Written by |
|---|---|---|
| `watchlist_events` | lifecycle event | F8 validator (CLI, inbox import) |
| `strategy_predictions` | strategy x company x horizon x day | pre-open run (rules, AI traders) |
| `strategy_abstentions` | AI trader x company x day it abstained or failed its gate | pre-open run |
| `paper_trades_settled` | settled trade x view (accuracy, head-to-head with its pick rule and family), with its automatic reason (F1.10) | post-close run (F1 engine) |
| `head_to_head_picks` | company x day x family x pick rule: the chosen strategy, horizon and why it was chosen (or "no qualifying prediction") | pre-open run |
| `cost_views` | prediction or pick that would trade, and settled trade: the two cost views (decision 50) and the cost-viable flag (decision 51) | pre-open and post-close runs (B2, `core/schema_b2.py`) |
| `trade_reasons_ai` | AI-written reason per head-to-head trade and per biggest win or miss | post-close run, gated |
| `trade_checks` | open trade x intraday check | intraday run (extends WS5 `intraday_checks`) |
| `eod_analyses` | market x day | post-close run, gated |
| `research_reviews` | market x week | weekly run |
| `news_impact` | market x week x category x status x materiality x horizon | weekly run |
| `command_log` | command from any channel (who, channel, tool, key, result) | MCP / CLI |

Existing kinds stay. `predictions` (the forecaster's calls) continue; the Opus combined trader's
predictions are written as `strategy_predictions` with `strategy_id = ai.combined.opus.v1`, and the
old kind keeps its scoring until the first review.

New read models (schema `rm`, same columns and one keyed `SELECT` per request as ARCHITECTURE.md 4.1;
every query parameter maps to a `page_key`, never to a filter at request time):

| Table | page_key | Serves |
|---|---|---|
| `rm.home` | `_` | Home: agreement per horizon N+1..N+5 (top 5 each), today's head-to-head trades, rule vs AI today and to date, open trades, alerts, freshness |
| `rm.stock_strategies` | ticker | the stock strategy page (decision 30) |
| `rm.strategies` | `_` (scoreboard) and `<strategy_id>` (detail) | Strategy lab |
| `rm.compare` | `_` and ticker | Rule vs AI |
| `rm.trades` | `_` (open trades and the last 5 sessions' settled trades) and ticker (open and the last 60 sessions) | trades lists |
| `rm.lifecycle` | `<ticker>:<session_date>` for the last 30 sessions | one day's path: made, checks, settled, explained |
| `rm.companies` | `_` | Companies |
| `rm.portfolio` | `_` | owner's portfolio with EUR view; head-to-head portfolios per family and pick rule |
| `rm.review` | `_` | latest weekly report and news-impact table |

Each is built by its feature's payload function and written by the warehouse sync.

## 5. API

Read and write endpoints under `/api/v1` (Next.js route handlers on Vercel). Existing contract
(api/openapi.yaml 1.0): markets, status, overview, watchlist, stock, bars, track record, news, runs,
portfolio, and the planned `company-requests`, `portfolio/paper-trades`, inbox and internal revalidate.
Status of this section: intended endpoints, adjusted to the approved mockups in Wave 3 (session B4,
section 10); the mockups' data files, not this list, are the final contract. Version 1.1 adds the
rows below; its write endpoints replace the two planned 1.0 write endpoints
(`company-requests`, `portfolio/paper-trades`), which were never built.

| Method and path | Returns / does |
|---|---|
| `GET /markets/{m}/home` | `rm.home` |
| `GET /markets/{m}/stocks/{t}/strategies` | `rm.stock_strategies`: agreement, best strategy, all strategies ranked |
| `GET /markets/{m}/strategies`, `GET /markets/{m}/strategies/{id}` | `rm.strategies` |
| `GET /markets/{m}/compare[?ticker=]` | `rm.compare` |
| `GET /markets/{m}/trades[?ticker=]` | `rm.trades` |
| `GET /markets/{m}/stocks/{t}/lifecycle/{date}` | `rm.lifecycle` (last 30 sessions; older: 404) |
| `GET /markets/{m}/companies` | `rm.companies` |
| `GET /markets/{m}/review` | `rm.review` |
| `POST /markets/{m}/companies` | add (Idempotency-Key) -> 202 pending |
| `POST /markets/{m}/companies/{t}/deactivate`, `/reactivate`, `/amount` | lifecycle actions -> 202 pending |
| `DELETE /markets/{m}/companies/{t}` | delete; body `{"confirm": "<ticker>"}` -> 202 pending |
| `POST /markets/{m}/paper-trades` | the owner's own paper trade -> 202 pending |

Outside `/api/v1`: `POST /api/assistant` (the chat, streaming, read tools only, budget-checked);
`/slack/commands`, `/slack/interactions` and `/mcp` served only by the gateway deployment (F10).

Reads stay one keyed `SELECT` per request with tag-based caching (ARCHITECTURE.md sections 6-7).
Writes never touch `base` or `rm`; they go to the inbox and dispatch the import (F10).

## 6. Pages (phone and laptop; Material 3 system from the owner's design sessions)

Every page shows "as of" and freshness, the Paper label on any signal, degraded mode when the data
service is down, and works with keyboard and without colour alone.

| # | Page | Shows | Actions | Read model |
|---|---|---|---|---|
| 1 | Home | per market, with a horizon selector N+1..N+5 opening on N+1 (decision 39): top 5 companies by agreement ("HDFC Bank: 9 of 15 strategies buy at N+1", average probability), today's head-to-head trades, or "No proven strong signals today" when nothing qualifies; rule vs AI today and to date; open trades; alerts; last runs | switch market, open a company's strategy page | `rm.home` |
| 2 | Watchlist | active companies: price, move, agreement, open trades | open company, filter by sector | `rm.watchlist` |
| 3 | Company | decision card; predictions with targets and ranges on the chart; today's path (intraday checks); settled results; why it moved; news with status; results digest; events | change amount, deactivate, ask, open strategy page | `rm.stock`, `rm.bars`, `rm.lifecycle`, `rm.trades` |
| 4 | Stock strategies (decision 30) | for one company, with the horizon selector: agreement (n of N buy, by family, per horizon); today's head-to-head picks (up to four) with their horizons and why each was chosen; the best strategy for this company by profit after costs; every strategy ranked by profit after costs on this company with its trades, win rate, average target error, today's prediction (target, range) and a sample-size badge; the best strategy overall shown beside the per-company best; baselines in the same list | open a strategy | `rm.stock_strategies` |
| 5 | Strategy lab | all strategies and baselines, both views, every horizon; heatmaps (strategy x horizon, x company, x reason code, over time) and cumulative profit lines (F2.8); per strategy detail in plain words; back-test vs forward apart | open strategy | `rm.strategies` |
| 6 | Rule vs AI | head-to-head per market and per company: profit, win rate, error; the "why" from EOD analyses and the weekly report | open company | `rm.compare`, `rm.review` |
| 7 | Paper portfolios | head-to-head portfolios per family and pick rule, all open trades by strategy, and the owner's own (with EUR view) | add own paper trade | `rm.portfolio`, `rm.trades` |
| 8 | Track record | prediction accuracy over time, calibration, scoring bases apart | - | `rm.track_record` |
| 9 | News | news by company with verification status and impact category; news-impact table | open company | `rm.news`, `rm.review` |
| 10 | Companies | active, inactive (news, price, Reactivate), pending requests; amounts | add, deactivate, reactivate, amount, delete (typed confirmation) | `rm.companies` |
| 11 | Assistant | chat with sources and as-of times; also a side panel on every page | ask | `POST /api/assistant` |
| 12 | Help | how to read the cockpit in plain words: signals, the Paper label, strategies, scores, the go-live bar; linked from every page | - | static content |

Stock strategies page, guard against luck: a per-company "best strategy" over a few weeks is mostly
noise (a handful of trades). The page therefore shows the trade count and the luck-test interval next
to every profit figure, greys out strategies with fewer than 20 trades on that company ("too few
trades to rank"), and keeps the best strategy overall beside the per-company best.

## 7. Integrations

| System | Role | Owner action needed |
|---|---|---|
| Claude Code routines | all computation and agents (schedules below); builds in cloud sessions | none |
| GitHub | source of truth (`data/`), CI, Actions workflow `onboard.yml` for writes from the web tier | a fine-grained token (Actions read and write, this repo only) for Vercel |
| MotherDuck | `market_brief` (`base`, `rm`, `meta`, `app`) and `market_brief_inbox` | a read-only token for the dashboard; a second service account with its token for the inbox |
| Vercel | the `web/` app as two projects: the dashboard (Vercel Authentication) and the gateway (`MB_GATEWAY=1`, no Vercel Authentication, only `/slack/*`, `/mcp` and its OAuth routes); the existing `reports/` site until retired | create the two projects; add environment variables |
| Slack | existing app gains `/company`, `/trade`, `/ask` and interactivity pointing at the gateway | add the commands and the request URL in the Slack app settings (exact steps provided) |
| Claude app | custom connector to the gateway's `/mcp` with GitHub sign-in | add the connector once `/mcp` is live |
| Anthropic API | dashboard chat and `/ask` | a dedicated workspace with a $20 monthly spend limit and a key in it |
| Neo4j | relationship graph, optional | none |

Routine schedule per market (per market per day: 1 pre-open + 2 intraday + 1 post-close + 5 news = 9
sessions; plus 1 weekly research run):

| Run | India | US | Contents |
|---|---|---|---|
| Pre-open (exists; moved 30 min earlier on 2026-10-07) | 07:40 IST | 07:45 New York | collect, features, model, rule strategies, 4 AI traders, gates, picks, sync, Slack morning picks; on the first trading day of the ISO week also the existing weekly review (step 10a); monthly the graph-builder |
| Intraday x2 (WS5, extended) | 11:13, 14:13 IST | 12:27, 14:57 New York | trade checks, deviation explainer, alerts, sync |
| Post-close (new) | 17:45 IST | 18:15 New York | close bars, settlement, EOD analyst, sync, Slack close results |
| News (exists) | every 4 hours | every 4 hours | news, articles, clusters, sync |
| Weekly research (new) | Saturday 10:00 IST | Saturday 10:00 New York | news-impact study, research director, weekly post |

## 8. How the UI connects to the backend

1. Pages are server-rendered by Next.js from `/api/v1` read endpoints (never MotherDuck directly from
   the browser); each payload carries `as_of`, `cutoff`, `built_at`.
2. Caching by tag per read model; the sync revalidates only changed pages, so opening the dashboard
   many times a day costs no database compute.
3. Actions post to the write endpoints with an idempotency key, show "pending", and turn into facts
   after the import commits and the next sync revalidates the page (minutes when the workflow dispatch
   works, else at the next run).
4. The chat panel streams from `/api/assistant`; tool calls are shown as "looked at: ..." with links.
5. Charts: the vendored Lightweight Charts with our bars, targets and ranges.
6. Design: the owner's design track designs the pages in `design/` from W1's data catalogue and
   example data files (section 10); the API payloads (read models) are then built to match the approved
   mockups' data files, and the frontend implements the mockups as React components on the Material 3
   system.

## 9. Non-functional rules

- All existing data, prediction, judging and safety rules hold, except the rule changes marked in
  F2.6, F8.1 and section 10 (the wave merge protocol). Free sources only, HTTPS allowlist, nothing run from fetched content, secrets only in
  environment variables, no email in requests.
- Cost guards: MotherDuck Lite (10 CU hours a month, ARCHITECTURE.md section 5 kill switch), Claude
  subscription use (AI traders as subagents of the existing pre-open session; Sonnet except one Opus
  trader), GitHub Actions minutes (CI and onboarding), Anthropic API $20 a month.
- Every number shown comes from stored data or deterministic computation; AI text cites ids and is
  gated.

## 10. Roadmap: waves of parallel cloud sessions (owner-approved 2026-10-07)

Two tracks meet at the end: a **backend and AI track** that does not depend on what the pages look
like, and a **UI track** where the owner designs the pages first and the API is then built to match
the approved mockups (the mockups decide the API contract, not the other way round). Every session
below runs in **its own cloud session** on its own branch, owns its own files (the file assignment
list of W1), and works autonomously:

1. builds and tests (fast tier while iterating, full suite at the end), live checks only where a
   collector or fetcher changed;
2. runs the `judge` subagent on its own work and fixes blockers until PASS (CLAUDE.md "Judging every
   change");
3. merges the latest `origin/main` into its branch and reruns the full suite; if the merge needed a
   conflict resolution in anything but `judgments/log.jsonl`, the judge re-checks that resolution (its
   diff only) before the push (CLAUDE.md: merge-conflict resolutions are judged); appends its verdicts
   to `judgments/log.jsonl` (on a conflict in that file: keep main's lines exactly as they are and
   append the branch's own lines after them, never re-sorting); and pushes to `main` itself (no pull
   request; on a push race: fetch, merge, retest, and repeat this step);
4. deletes its branch on GitHub after the push;
5. writes the shared-doc edits it needs (CLAUDE.md, DESIGN.md, ARCHITECTURE.md, and existing routine
   prompts it does not own) as proposals in `docs/ws/<session>.md`; the orchestrator applies them in one
   judged batch per wave (the last batch in Wave 5), so parallel sessions never edit those files. A
   routine prompt a session owns (e.g. B9's `routine/INTRADAY_PROMPT.md`, B3's new prompts) it edits
   itself.

**Rule change** (owner decision 48): until now the orchestrator merged build work to main and copied
the sessions' `docs/ws/*-judgments.jsonl` lines into the log (docs/ws/README.md); from the waves on,
each session appends its own verdicts and runs the post-merge full suite before pushing to main
itself, as above. Everything else in CLAUDE.md "Judging every change" holds.

The orchestrating session watches the waves on a timer (no owner attention needed), launches the next
wave when its inputs have merged, resolves any merge clash a session cannot (with a judge re-check of
the resolution before pushing), and reports only finished waves, blockers
and decisions that are the owner's.

The session ids below (B1-B10) are the ones used throughout this spec.

**Wave 0:** the news de-duplication fix built in the orchestrating session (owner requirement of
2026-10-07: never store the same news from the same source twice; decisions 45-47: same link = one
item plus headline history, once per market, fix now). Recognising one outlet under several labels or
hosts is the orchestrator's implementation of the owner's "same source" rule.

**Wave 1: foundation (1 session; everything else starts from it).** "Catalogue and record formats":
- the **data catalogue** (`docs/DATA_CATALOGUE.md`): every piece of information the system will hold,
  per entity (company, prediction, paper trade, head-to-head pick, strategy, scoreboard row, automatic
  and AI reason, news item with status and headline history, results digest, intraday check,
  lifecycle event, market status), each field with a plain-language description, its source (stored
  kind or computation in this spec) and realistic example values; plus example data files per entity
  (`design/catalogue/*.json`, realistic and internally consistent, clearly marked as examples) for
  the owner's design sessions;
- the storage formats of the new kinds (section 4) in `core/schema_lab.py` and
  `core/schema_lifecycle.py`, `config/strategies.yaml` (schema, horizon list and the initial strategy
  set), `mcp/tools.yaml` (tools, inputs, outputs, permissions per channel), and the interfaces later
  sessions code against: the F1 protocol (function signatures, record formats), the watchlist
  accessor, the per-horizon model-score and range record formats (so B2, B3 and B9 build against them
  with fixtures before B10's real data exists);
- one **file assignment list**: every existing file that needs a change for the company lists (each
  reader of `cfg` tickers and sector lists, classified collect, predict or display, F8.2) or for
  horizons (every file that handles `HORIZONS`, `horizon_days` or a fixed horizon), each assigned to
  exactly one session, which then makes both kinds of change in it. Rule: files under a session's own
  directories go to that session (B2 `portfolio/` and `lab/`, B9 `intraday/`, B4 `warehouse/`);
  `model/`, the `analytics/` range, scoring, calibration and prediction-rule modules, `pipeline/`,
  `presentation/` and `replay/` horizon changes go to B10; the remaining company-list changes go to B1.
Owns: `docs/DATA_CATALOGUE.md`, `design/catalogue/`, `mcp/tools.yaml`, `core/schema_lab.py`,
`core/schema_lifecycle.py`, `config/strategies.yaml`, interface stubs in `marketbrief/contracts/`,
`docs/ws/w1.md`. No API contract and no page shapes (those come from the approved mockups, Wave 3).

**Wave 2: parallel builds (7 sessions, launched together when W1 has merged) + the owner's design
track.**

| Session | Builds | Owns | Needs |
|---|---|---|---|
| B10 Horizons | F2.7: the signal model, its labels and backtest, `ranges.py`/`range_math`, scoring and calibration for N+1..N+5 with the decision-37 definition, the horizon list read from `config/strategies.yaml`, legacy labels for old records; refit and walk-forward test per horizon | `marketbrief/model/`, `config/model.yaml`, `config/ranges.yaml`, the `HORIZONS` constants in `constants/model.py`, `constants/prediction_rules.py`, `constants/dashboard.py`, and the files W1's list assigns to B10 | W1 |
| B2 Engine and lab | F1 engine (incl. F1.9-F1.11, the EUR view in `marketbrief/portfolio/`, and the `EURUSD=X` symbol in `config/markets/us.yaml`), F2 strategies, baselines and the head-to-head picks, F2.8 heatmap data, F3 news-impact study, F7 scoreboard and luck test | `marketbrief/lab/`, `scripts/lab.py`, `marketbrief/portfolio/` (incl. its `HORIZONS`), `config/costs.yaml`, that line of `config/markets/us.yaml`, its files on W1's list | W1 (B10's per-horizon scores for live data) |
| B3 AI traders | F4 traders and gate, F6 EOD analyst, AI reasons and research director, post-close and weekly routine prompts | `.claude/agents/trader-*.md`, `.claude/agents/forecaster.md`, `eod-analyst.md`, `research-director.md`, `marketbrief/traders/`, `routine/POSTCLOSE_PROMPT.md`, `routine/WEEKLY_PROMPT.md` | W1 (B2 settles; B10's ranges for live data) |
| B1 Lifecycle | F8: watchlist events, the loader change and accessor, the switch of the predict and display call sites W1 assigns to B1, seed, onboarding pipeline, lifecycle CLI, inbox import, `onboard.yml` | `marketbrief/lifecycle/`, `core/market_config.py`, `scripts/company.py`, `.github/workflows/onboard.yml`, the files W1 assigns to B1 | W1 |
| B9 Monitoring | F5: intraday checks of every open paper trade at every horizon (incl. the fixed horizon in `intraday/rows.py`), the extended explainer input, the intraday alerts feed for B6 | `marketbrief/intraday/`, `scripts/intraday_check.py`, `config/intraday.yaml`, `routine/INTRADAY_PROMPT.md` | W1 |
| B6 Notifications | F9 Slack threads (morning, alerts, close, weekly) | `marketbrief/alerts/`, `scripts/alerts.py` | W1 |
| B5 Tools and channels | the tool layer, the gateway mode (middleware), Slack commands, form and confirm step, `/mcp` with GitHub OAuth, inbox writes, workflow dispatch, injection suite | `web/lib/tools/`, `web/app/slack/`, `web/app/mcp/`, `web/middleware.ts`, `mcp/` except `tools.yaml`, the minimal `web/` project files (`package.json`, `tsconfig.json`, `next.config.*`) | W1 |
| (owner) Design track | the owner with Fable designs the 12 pages in `design/` from the data catalogue and example files; a field the catalogue lacks is a "new data request" the owner approves and W1's catalogue then gains (by the orchestrator, judged) | `design/` except `design/catalogue/` | W1 |

**`web/` project files.** B5 creates `web/package.json`, its lockfile, `tsconfig.json` and
`next.config.*` in Wave 2. Later sessions (B4 in Wave 3; B7 and B8 in parallel in Wave 4) may only add
dependency lines and their lockfile entries (additive, never changing or removing another session's);
the lockfile is regenerated with the package manager, never edited by hand; a conflict in these files
is resolved by keeping both sides' dependencies, regenerating the lockfile, and the judge re-check of
step 3.

Sessions that need another session's data (B2, B3, B6, B9) build and test against W1's example
records; real data flows once all of Wave 2 has merged. B1 changes only the loader and the files W1
assigns to it; every other reader of `cfg` tickers keeps working through the loader.
`config/markets/<market>.yaml` `tickers:` and the ticker lists under `sectors:` stay until Wave 5
removes them. Shared files keep the additive rules of the earlier WS waves 0-1 (docs/ws) (one import + one spread line in
`core/schemas.py`, WS-marked constant blocks, `sql/views.sql` blocks at the end). Optional, in parallel:
a cleanup session for the older open GitHub issues and #59 (files not owned by another session).

**Wave 3: API layer (after the owner approves the mockups).**

| Session | Builds | Owns | Needs |
|---|---|---|---|
| B4 Contract and API | `api/openapi.yaml` 1.1 taken from the approved mockups' data files (each page's data file is the payload of its endpoint; section 5 lists the intended endpoints, adjusted to the mockups), the read models of section 4 in MotherDuck, every route under `web/app/api/v1/` (write handlers are thin calls into B5's tool layer), caching, revalidate; a contract test that every live response validates against the schema and matches its mockup's data file in shape | `api/`, `web/app/api/v1/`, `web/lib/data/`, `marketbrief/warehouse/` (new `rm_*` modules and the files W1 assigns to B4) | approved mockups, Wave 2 merged |

**Wave 4: app (2 sessions, after B4 merges).**

| Session | Builds | Owns | Needs |
|---|---|---|---|
| B7 Frontend | the 12 pages from the approved mockups as the Next.js app on the live API (each mockup's example data file replaced by its endpoint) | `web/` except the paths owned by B4, B5 and B8 | B4 |
| B8 Assistant | F11 chat panel and Slack `/ask` with the budget | `web/app/api/assistant/`, `web/lib/assistant/` | B4, B5 |

**Wave 5: consolidation (1 session, last).** The orchestrator applies the remaining proposed
shared-doc edits (judged); the session wires the
new runs into the routine prompts, create the schedules (post-close, intraday, weekly research),
update `CUTOFF_LOCAL` in `constants/ai_replay.py` to the new pre-open times, remove `tickers:` from the
market configs, measure the pre-open run's duration, end-to-end run of both markets, then switch on
the new paper trading. The 2-month review clock starts that day.

**After launch.** Retire the static pages 2 weeks after the new app is live (decision 25); first formal
review at 2 months (decision 23).

## 11. Owner actions (when each wave needs them)

| When | Action |
|---|---|
| Before Wave 5 switches on paper trading (B2 merges with the owner-provided values) | Confirm the broker charges of decisions 49 and 52 (F1.6): from an Axis Direct contract note, the 0.75% brokerage and its ₹50 minimum, GST, STT, stamp duty, the ₹200 NRO Non-PIS reporting charge per trade date and the DP charge per sale (still provisional); from the BUX app or site, the €0.99 order fee, the 0.75% FX markup and the 0.20% a year portfolio fee |
| Before B4/B5 go live (Waves 2-3) | Create the two Vercel projects; MotherDuck read token and inbox service account; GitHub fine-grained token |
| Before B5 Slack | Add `/company`, `/trade`, `/ask` and the interactivity URL to the Slack app |
| Before B8 | Anthropic workspace with a $20 monthly limit and a key in it |
| After B5 | Add the Claude app connector |
| After W1 merges | Design the 12 pages with Fable from the data catalogue and example files (design track) |
| Now (decision 36) | Create the tag `archive-dashboard-r1` on commit 85416b0 on GitHub (this session pushes a temporary branch with it if asked) |
| At the first review | Set the maximum drawdown limit |
