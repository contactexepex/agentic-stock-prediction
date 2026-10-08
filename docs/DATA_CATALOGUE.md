# Data catalogue

Status: Wave 1 (W1), 2026-10-07. This page lists every piece of information the cockpit will hold, so the owner
can design the 12 pages (docs/SPEC.md section 6) with Fable before the API exists. For each field it gives a
plain-language meaning, where the value comes from, its unit and a realistic example. Research only: nothing here is
advice. Every signal stays "Paper" until it is proven (SPEC F7).

**Example files.** Every entity below has an example file in `design/catalogue/` (JSON, one `records` list,
marked `"_example": true`). Prices, index moves and range widths in them are real stored bars and ranges of
29 Sep - 6 Oct 2026. Predictions, trades, reasons, news, commands and the portfolio are invented, but they are
computed from one set of inputs, so the files agree with each other: quantities, costs, profit, agreement counts and
scoreboard sums. Costs, head-to-head picks and cost views are computed with session B2's engine code
(`marketbrief/lab/`) and the rates in `config/costs.yaml`, at an example EUR/USD of 1.17.
`design/catalogue/make_examples.py` rebuilds them. The examples use the six companies NVDA, AAPL and JPM
(US, in $) and RELIANCE, HDFCBANK and MARUTI (India, in ₹), plus INDIGO and DAL as inactive companies.

**Status of each entity.**
- **Exists**: stored or computed today.
- **B1, B2, B3, B4, B5, B9, B10 builds it**: a Wave 2 session (SPEC section 10) builds it. Its storage format
  is fixed already (`scripts/marketbrief/core/schema_lab.py`, `schema_lifecycle.py`), so the field list will not
  change without a new data request.
- **Derived for pages**: no stored kind holds it as one record. Session B4 computes it for the page (read
  models, SPEC section 4) from the stored kinds named in "Source".

**Units used everywhere.**
- Money is in the market currency: ₹ (INR) for India, $ (USD) for the US. The owner's portfolio adds a € view
  of US positions.
- India amounts are written the Indian way on screen: ₹1,00,000.
- Prices are the exchange's raw prices (not adjusted for later splits) unless a field says otherwise.
- `_pct` fields are percent points: 1.25 means +1.25 %.
- Probabilities are 0-1: 0.57 means 57 %.
- Times are UTC (ISO 8601, e.g. `2026-10-07T11:45:00Z`); pages show them in the market's local time.
- Dates are the market's trading dates.

**Words.**
- **D** is the entry session: the first session after a prediction is made. Every paper trade buys at D's
  official open.
- **N+k** (k = 1-5) is the horizon: sell at the official close of the k-th market session after D. Weekends and
  holidays are skipped.
  - Example: bought Friday, N+1 sells at Monday's close.
  - Example (India): bought Wednesday 30 Sep 2026, N+2 sells on Monday 5 Oct, because Friday 2 Oct was a
    holiday.
  - The horizon list is a setting (`config/strategies.yaml`).

Contents:
- Companies and the market: [Company](#company), [Lifecycle event](#lifecycle-event),
  [Command](#command), [Market status](#market-status), [Calendar event](#calendar-event)
- Strategies and predictions: [Strategy](#strategy), [Prediction](#prediction),
  [Abstention](#abstention), [Agreement](#agreement)
- Trades: [Head-to-head pick](#head-to-head-pick), [Paper trade](#paper-trade) (with its
  [automatic reason](#automatic-reason)), [Cost view](#cost-view), [Open trade](#open-trade), [Intraday trade check](#trade-check)
- Explanations and scores: [AI reason](#ai-reason), [End-of-day analysis](#eod-analysis),
  [Scoreboard row](#scoreboard-row), [Research review](#research-review)
- News and results: [News item](#news-item), [News-impact row](#news-impact-row),
  [Results digest](#results-digest)
- The owner's money: [Owner's paper portfolio](#portfolio)
- [What a page can combine](#combinations), [Technical fields](#technical-fields) and [How to ask for a new field](#requests)

---

<a id="company"></a>
## Company

One company on the watchlist, as of now. Status: the fields marked *config today* exist in
`config/markets/<market>.yaml`. From session **B1** on they come from the [lifecycle events](#lifecycle-event)
through the watchlist accessor (`marketbrief/contracts/watchlist.py`). The price and agreement fields are
**derived for pages**. Example file: `design/catalogue/company.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| market | Which market | config | `india` / `us` | `us` |
| ticker | Exchange symbol | config today; `watchlist_events` add (B1) | text | `NVDA`, `M&M` |
| name | Company name | same | text | `Nvidia` |
| exchange | Where it is listed (decision 14) | add event (B1) | `NSE`, `NYSE`, `NASDAQ` | `NASDAQ` |
| sector | Sector set at onboarding | config `sectors:` today; add event (B1) | text | `Tech` |
| state | Active: predicted and traded. Inactive: still collected, shown only in the Companies page's Inactive part (decision 13). Deleted companies are never shown | newest lifecycle event (F8.2) | `active` / `inactive` | `inactive` (DAL) |
| amount | Money per paper trade | `set_amount` event, else the default (F1.3, decisions 26 and 44) | ₹ / $ | `100000` (₹1,00,000); MARUTI `10000` |
| amount_overridden | Whether the amount differs from the default | same | yes/no | `true` for MARUTI |
| currency | Currency of every money field of this company | market | `INR` / `USD` | `INR` |
| yahoo, nse_symbol, cik | Identifiers checked at onboarding: Yahoo symbol; NSE symbol (India); SEC CIK (US) | add event (B1) | text | `RELIANCE.NS`, `RELIANCE`, `0001045810` |
| added_at | When it joined the watchlist; seeded companies get the start of stored history | first add event | time | `2011-01-03T00:00:00Z` |
| state_since | When its current state began | newest state event | time | `2026-10-05T11:45:00Z` (DAL inactive) |
| last_close, last_close_date | Latest stored close | `ohlc_raw` (exists) | ₹ / $, date | `239.24` on `2026-10-06` |
| change_pct | Last session's move | `ohlc_raw` | % | `2.66` |
| agreement_n1 | How many strategies buy it at N+1 today | [Agreement](#agreement) | count of count | `12 of 15` |
| open_trades | Its open paper trades, all strategies, horizons and both views | [Open trade](#open-trade) | count | `10` |

<a id="lifecycle-event"></a>
## Lifecycle event

One change to the watchlist: add, deactivate, reactivate, delete or set amount (F8). It is append-only, never
edited; a correction is a new event. Status: kind `watchlist_events`. Session **B1** builds the validator and the
loader. Example file: `lifecycle_event.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| id | Event id | F8 validator | text | `we-us-MSFT-add-20261005T140200Z` |
| event | What happened | request | `add`, `deactivate`, `reactivate`, `delete`, `set_amount` | `deactivate` |
| ticker, market | Which company | request | text | `INDIGO`, `india` |
| effective_from | When it counts (the next pre-open run); seeded adds use the start of stored history | validator | time | `2026-10-05T02:10:00Z` |
| recorded_at | When it was written | validator clock | time | `2026-10-02T09:18:00Z` |
| name, exchange, sector, yahoo, nse_symbol, cik | Identity; on add events only | onboarding (F8.3) | text | `Microsoft`, `NASDAQ`, `Tech` |
| amount | New per-trade amount (`set_amount`, or `add` with an amount); empty = default | request | ₹ / $ | `10000` |
| reason | Why, in the requester's words | request | text | `pause airlines` |
| requested_by | Who asked; taken from the channel's sign-in, never typed in | channel auth (F10) | text | `slack:U07ABCD123`, `dashboard:owner` |
| channel | Where the request came from | channel | `dashboard`, `slack`, `claude_code`, `claude_app`, `cli`, `seed` | `slack` |
| command_id | The [command](#command) that asked | command log | text | `cmd-20261005T135500Z-052b8228` |
| idempotency_key | Stops a double click from adding twice | client | text | `add-msft-7Hq2` |
| onboarding | Result of each onboarding check (add only) | onboarding (F8.3) | check -> `ok`/`failed`/`skipped` | `{"not_etf": "ok", "backfill_prices": "ok"}` |
| supersedes | The event this one corrects | validator | id | empty |

Pending requests: until the import writes the event, the page shows the request as "pending" (F10; B4 and B5).

<a id="command"></a>
## Command

Every command from any channel, whether it was accepted, refused or answered (F10). Status: kind `command_log`.
Session **B5** writes it. Example file: `command_log.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| received_at | When it arrived | tool layer | time | `2026-10-05T14:05:00Z` |
| channel, actor | Where it came from and who sent it (from the channel's sign-in) | channel auth | text | `slack`, `slack:U07ABCD123` |
| tool | Which tool of `mcp/tools.yaml` | request | text | `add_company` |
| kind | Read or write | tools.yaml | `read`, `read_ai`, `write` | `write` |
| arguments | What was asked | request | JSON | `{"market": "us", "symbol": "SPY"}` |
| result | Outcome | validator | `accepted`, `pending`, `refused`, `duplicate`, `failed` | `refused` |
| refusal_code, message | Why it was refused, in plain words | validator | text | `validation_failed`, "SPY is an ETF; only common stocks can be added" |
| record_ids | Records it wrote | validator | ids | `["we-us-MSFT-add-20261005T140200Z"]` |
| budget_left | Write actions the agent has left today | policy (F10) | count | `18` |

<a id="market-status"></a>
## Market status

Whether the market trades today, which session is being predicted, how fresh the data is, and the newest runs.
Status: the `session` block **exists** (`pipeline/market_status.py`, the `MarketStatus` schema of
`api/openapi.yaml`). The run list, freshness and the `benchmark` and `vol_index` blocks are **derived for pages**
(B4) from stored data; runs are in SPEC section 7.
Example file: `market_status.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| as_of | Newest trading date with stored indicators | `features` | date | `2026-10-06` |
| session.session_date | The session being predicted (D) | market calendar | date | `2026-10-07` |
| session.trading_day, in_session, late_run | Whether the market trades today; whether it is open now; whether it is already past the close | market_status (exists) | yes/no | `true`, `false`, `true` |
| session.session_open_utc, session_close_utc | Today's open and close | market calendar | time | `2026-10-07T13:30:00+00:00` |
| regime | Market mood label | `regime` (exists) | `TRENDING`, `EVENT_HEAVY`, `UNSTABLE`, ... | `EVENT_HEAVY` |
| benchmark.symbol, name | The index the stocks are measured against (role `benchmark` in `config/markets/<market>.yaml`) | market config | text | `NIFTY50`, "Nifty 50"; US `SPY`, "S&P 500 ETF" |
| benchmark.close, close_date | Its last stored close and that close's trading date | stored bars (`ohlc`) | index points or $ | `22776.0996`, `2026-10-06` |
| benchmark.change_pct, change_5d_pct | Change from the previous session's close, and from the close 5 sessions earlier (the indicators' `period_return`) | stored bars | % | `0.98`, `-0.02` |
| vol_index.symbol, name, close, close_date, change_pct, change_5d_pct | The same for the market's volatility index (role `vol_index`): how much movement traders expect. The regime is derived from the benchmark and this index | market config, stored bars | points, % | `INDIAVIX`, 13.61, `-7.92`; US `VIX` 15.01 |
| runs.pre_open, intraday, post_close, news | When each run last ran and whether it worked; the post-close run is new (B3) | run records | time, ok | pre-open `2026-10-07T02:10:00Z` ok |
| freshness.state, built_at, age_minutes | How old the page data is | read model `built_at` (B4) | `fresh`/`stale`/`unknown`, minutes | `fresh`, 29 |
| paper_label | The label every signal carries until proven | review `model_skill` / go-live bar (F7) | text | "Paper only - no proven edge yet" |

---

<a id="calendar-event"></a>
## Calendar event

What is coming that a reader should know before a horizon ends: the market's scheduled events and the active
companies' results and ex-dividend dates, from the session being predicted to 8 weeks after it, as known at the
page's "as of" time. Status: **derived for pages** (B4) from what **exists**: the rules and fixed dates of
`config/events.yaml` (`core/calendar.market_events`), the stored `events` kind (read as of a time like the
warehouse's `upcoming_events`: per company and type, the newest date first seen by then) and the market calendar.
Example file: `calendar_event.json` (7 Oct to 2 Dec 2026, read at `2026-10-07T12:00:00Z`; INDIGO and DAL are left out
because the examples show them as inactive).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| market | The market whose calendar it is (India also lists the US FOMC decision and jobs report) | | `india`/`us` | `india` |
| date | The trading date it falls on (a company date can fall on a weekend, see `reaction_sessions`) | config / `events` | date | `2026-10-08` |
| type | What kind of event. Market: `rbi_policy`, `fomc`, `cpi`, `jobs_report`, `fno_expiry`, `weekly_expiry`, `opex`, `triple_witching`, `index_rebalance`, `budget` (as in `config/events.yaml`); company: `earnings`, `ex_dividend`; calendar: `holiday` | | text | `earnings` |
| name | Plain words | config name; company name + "results" / "ex-dividend"; "NSE closed" or the holiday's name | text | "Tata Consultancy Services results" |
| ticker | The company; empty for market-wide events | `events` | ticker | `TCS` |
| timing | When the company reports, when the source says: `before_open`, `during`, `after_close`; empty when unknown (every stored upcoming date is empty today) | `events.timing` | text | empty |
| reaction_sessions | The session(s) whose move contains the results: `before_open`/`during` = that day; `after_close` = the next session; unknown timing = that day and the next (the range engine's `earnings_reaction.affected_sessions`); a weekend date = the next session. Empty for other types | engine rule | dates | `["2026-10-08", "2026-10-09"]` |
| major | A market-wide event: it raises the regime to EVENT_HEAVY within 2 days before it and widens every range of that market whose window (the day after the as-of close to the exit session) contains it (`major_event_factor` in `config/ranges.yaml`) | `config/events.yaml` | yes/no | RBI policy `true` |
| widens | Which ranges it widens: `market` (major market event), `company` (results widen that company's ranges, `earnings_vol_multiple`; a company with results within 1 day gets no new call), empty = none | engine rules | text | `company` |
| provisional | The date is not yet confirmed (the name says so too) | `config/events.yaml` | yes/no | US CPI 10 Nov `true` |
| release | Publication time for data released before the open | `config/events.yaml` | text | `08:30 ET` |
| source | Where the row comes from | | text | `config/events.yaml`, `events (yfinance)`, `market calendar` |
| event_id | The stored `events` row (company events only) | `events.id` | id | `TCS-earnings-2026-10-08` |

---

<a id="strategy"></a>
## Strategy

A frozen way of predicting. It is either a rule strategy, a baseline (the yardstick) or an AI trader (F2, F4).
An id never changes behaviour after its first live day; a change makes a new id. Status: the registry
`config/strategies.yaml` **exists** (W1). Session **B2** builds the rule strategies and baselines, **B3** the AI
traders. Example file: `strategy.json` (the registry entries plus counts).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| id | Strategy id | registry | text | `rule.model_news.v1`, `base.always_up.v1`, `ai.combined.opus.v1` |
| family | Kind of strategy | registry | `rule`, `baseline`, `ai` | `rule` |
| name | Short name for screens | registry | text | `Model + double news` |
| description | What it does, in plain words | registry | text | "Like the reference, but news counts twice as much..." |
| compared_to, differs_in | The strategy it is tested against, and the one setting that differs (F2.5) | registry | id, text | `rule.model_news.v1`, `news_weight` |
| parameters | Its settings (rule: signal, news weight, which news statuses and materiality count, global cues, regime filter; AI: model, inputs, whether it sees the model score) | registry | settings | `news_weight: 2.0` |
| threshold | Lowest probability of a rise that still makes a trade (empty for always-up and momentum) | registry | 0-1 | `0.55`, `0.60` |
| horizons | Horizons it predicts (decision 38) | registry | list of k | rule `[1,2,3,4,5]`, AI `[1,3,5]` |
| live_from | First session it trades for real; empty until Wave 5 switches paper trading on | registry | date | empty |
| live | Whether it is live | derived | yes/no | `false` |
| settled_trades | Its settled trades so far | [Paper trade](#paper-trade) | count | `16` |

The initial set has 15 strategies:
- 8 rule strategies. Each differs from the reference `rule.model_news.v1` in one setting: half news, double
  news, confirmed news only, major news only, global cues, calm markets only, or a 60 % bar.
- 3 baselines: always buy, follow yesterday, model without news.
- 4 AI traders: news & results (Sonnet); price pattern & mood (Sonnet); combined (Sonnet); combined (Opus).

<a id="prediction"></a>
## Prediction

One strategy's call for one company and one horizon, made before the open of D (F1, F2.6). Status: kind
`strategy_predictions`. Sessions **B2** (rule strategies and baselines) and **B3** (AI traders) write it. The
inputs come from **B10**: the model score and range for every horizon (`marketbrief/contracts/horizons.py`).
Example file: `prediction.json` (NVDA and RELIANCE, all 15 strategies, every horizon they predict).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| id | `<strategy>:<as-of date>-<ticker>-<k>d` | F2.6 | text | `rule.model_news.v1:2026-10-06-RELIANCE-3d` |
| strategy_id, family | Who predicted | registry | text | `ai.combined.opus.v1`, `ai` |
| made_at | When it was made (always before D's open; a later one is refused) | run clock | time | `2026-10-07T11:45:00Z` |
| as_of_date | Latest price date it used | stored bars | date | `2026-10-06` |
| session_date | D, the entry session | market calendar | date | `2026-10-07` |
| exit_date | Close of the k-th session after D | market calendar | date | `2026-10-12` (N+3) |
| horizon_days | k of N+k | strategy | 1-5 | `3` |
| direction | Up or down; a down call is scored but never traded (decision 3) | strategy | `up`/`down` | `up` |
| prob_up | Probability of a rise from D's open to the exit close; empty for always-up and momentum | model / trader | 0-1 | `0.572` |
| confidence | Probability of the stated direction | derived | 0-1 | `0.596` |
| threshold, qualifies | Its bar and whether this call becomes a trade (up and at or above the bar; the calm-markets strategy also skips unstable and event-heavy days) | registry, F1.2 | 0-1, yes/no | `0.55`, `true` |
| base_close | Latest close when made | `ohlc_raw` | ₹ / $ | `1218.00` |
| target_price | Expected exit close | ranges centre (B10) or trader | ₹ / $ | `1220.74` |
| lo50, hi50, lo80, hi80 | The range the exit close should fall in half of the time (50 %) and 8 times in 10 (80 %) | `ranges.py` per horizon (B10); may only be widened | ₹ / $ | 80 %: `1172.95` - `1270.46` |
| range_widen | How much the strategy widened the range | trader | 0-0.5 | `0.1` |
| model_prob, agent_adjustment, adjustment_reason | Combined AI traders only: the model's probability, their change (at most ±0.10) and why | model score, trader (forecast-v11 anchor) | 0-1, text | `0.566`, `+0.03`, "Corroborated news not yet in the model's news term" |
| evidence_ids | What it relied on. News ids must be verified enough (DESIGN 3b). Rule strategies cite their model score and feature snapshot | strategy | ids | `["nse-ann-7781203", "model_scores:2026-10-06-RELIANCE-3d"]` |
| reason | AI traders: why, in at most 60 words | trader | text | "Exchange filing confirms the retail unit's capital raise..." |
| regime, quality | Market mood and data quality at the time | `regime`, `features` | text | `EVENT_HEAVY`, `OK` |
| amount, currency | What a trade of it would invest | [Company](#company) | ₹ / $ | `100000`, `INR` |

Old records stay apart: the forecaster's `predictions` (1 and 5 days) and the old "5-day" calls, which sold at
D+4, keep their own label and are never mixed with N+5 (SPEC F2.7).

<a id="abstention"></a>
## Abstention

A day on which an AI trader made no prediction for a company. This happens when it chose not to, when it failed
its check twice, or when it ran out of time (F4.3). An abstention is not a loss. Status: kind
`strategy_abstentions`; session **B3** writes it. Example file: `abstention.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| strategy_id, ticker, session_date | Who skipped what | trader run | text, date | `ai.news_results.sonnet.v1`, `JPM`, `2026-10-07` |
| horizons | Horizons not predicted | run | list | `[1,3,5]` |
| reason_code | Why | gate | `abstained`, `gate_failed`, `timeout`, `blocked_quality`, `earnings_window`, `killed` | `gate_failed` |
| reason | The trader's own words, when it chose to skip | trader | text | "Price pattern is mixed..." |
| gate_codes, attempts | Which checks failed, and the number of attempts | gate | codes, count | `["NEWS_STATUS_MAIN"]`, `2` |

<a id="agreement"></a>
## Agreement

How many strategies would buy a company at a horizon today. It is used for Home's ranking (decision 30) and for
the Slack morning picks. Status: **derived for pages** from today's [predictions](#prediction) (B4, `rm.home`).
Example file: `agreement.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| horizon_days | Horizon shown (Home opens on N+1) | selector | 1-5 | `1` |
| rank | Place in the market's ranking: most buyers first, then the higher average probability | derived | number | `1` |
| buy, of | Strategies whose call qualifies as a trade, and strategies that predicted it at this horizon | predictions | count | `12` of `15` |
| by_family | The same split into rule, baseline and AI | predictions | counts | rule 6 of 8, baseline 2 of 3, AI 4 of 4 |
| avg_prob_up | Average probability of the buyers that give one | predictions | 0-1 | `0.5661` |
| label | Ready-made sentence | derived | text | "Reliance Industries: 12 of 15 strategies buy at N+1" |

The strongest other horizon for the Slack morning picks (decision 39) is the other horizon with the highest `buy`
count; on a tie, the shorter one wins.

---

<a id="head-to-head-pick"></a>
## Head-to-head pick

Each day and for each company, the strongest rule strategy and the strongest AI trader each choose one horizon,
under two pick rules: "best expected gain" and "highest probability". That makes up to four head-to-head trades
(F1.7, decisions 41-42, with B2's two corrections: see docs/ws/b2.md). Status: kind `head_to_head_picks`; session
**B2** writes it. Example file: `head_to_head_pick.json` (RELIANCE, NVDA, and HDFCBANK with no candidate), built by
B2's own pick code.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| family | Rule or AI side | F1.7 | `rule` / `ai` | `ai` |
| pick_rule | How the horizon was chosen | F1.7.3 | `best_expected_gain` / `highest_probability` | `highest_probability` |
| status | Whether a pick was possible | engine | `picked` / `no_candidate` | `no_candidate` (HDFCBANK: nobody buys) |
| strategy_id | The family's strongest strategy with at least one buyable horizon | ranking | id | `ai.combined.opus.v1` |
| strongest_basis | Ranked on this company (from 20 settled trades on it) or on all companies of the market; a strategy with no settled trade ranks last | decision 41 (corrected) | `per_company` / `all_companies` | `all_companies` |
| ranking | The full ranking it came from, within the market: rank, settled trades and profit after costs | settled trades | list | 1. `rule.model_news.v1`, 10 trades, $99.00 |
| horizon_days, prediction_id | The chosen horizon and the prediction behind it | engine | k, id | `5` |
| prob_up | That prediction's probability | prediction | 0-1 | `0.615` |
| move_pct, loss_pct, costs_pct | Expected rise when the stock ends above the latest close C; expected shortfall when it ends below C (both from the strategy's own 80 % range); round-trip costs of the amount at C. All as a % of the amount | F1.7.3 (corrected) | % | `3.9597`, `3.601`, `0.234` |
| expected_gain_pct | `p × move − (1 − p) × loss − costs`, per trade | F1.7.3 | % | `0.8148` (NVDA, AI, N+5) |
| candidates | Every horizon the strongest strategy predicted, each with the numbers above plus: `gain_per_session_pct` (expected gain ÷ k, what "best expected gain" ranks, owner decision); `eligible` (the prediction qualifies; only eligible horizons can be picked); `expected_move_pct`, `your_cost_pct`, `expected_gain_your_pct`, `cost_viable` (see [Cost view](#cost-view)) | engine | list | N+5: gain per session `0.163`, `eligible: true`, expected move `0.4932`, your cost `1.738`, gain after your cost `-0.6892`, `cost_viable: false` |
| amount, currency | Money per head-to-head trade | company | ₹ / $ | `1000`, `USD` |

<a id="paper-trade"></a>
## Paper trade (settled)

What one prediction became under the protocol, once its exit close is stored (F1). There are two views of the
same predictions:
- The **accuracy view**: every qualifying prediction is its own trade.
- The **head-to-head view**: only the up to four picks above, one trade each.

Settlement is deterministic: the same stored bars always give the same numbers. A corrected split or bonus gives a
new settlement row, not an edit. Status: kind `paper_trades_settled`; session **B2** (the engine) writes it. Example
file: `paper_trade.json` (75 rows from the predictions of 29 Sep, settled on 1-6 Oct, including 10 skipped MARUTI
trades).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| trade_id | `acc:<prediction>` or `h2h:<pick rule>:<prediction>` | engine | text | `acc:rule.model_news.v1:2026-09-29-NVDA-3d` |
| view, pick_rule | Accuracy or head-to-head; which pick rule it came from | engine | text | `head_to_head`, `highest_probability` |
| strategy_id, family, ticker, horizon_days | Whose trade | prediction | text, k | `rule.model_news.v1`, `rule`, `NVDA`, `3` |
| entry_date, exit_date, exit_date_actual | D; the planned exit; the exit used (a later one when the exit close is missing: flag `exit_delayed`) | calendar | date | `2026-09-30`, `2026-10-05` |
| status | Outcome | F1.1-F1.4 | `settled`, `no_entry` (no open price on D), `skipped_price_above_amount` (India: one share costs more than the amount) | `skipped_price_above_amount` (MARUTI, ₹10,000 vs ₹11,901 a share) |
| flags | Special cases | engine | `exit_delayed`, `split_in_window`, `resettled` | empty |
| amount | Money invested | company | ₹ / $ | `1000` |
| entry_price, exit_price | Official raw open of D, and official raw close of the exit session | `ohlc_raw` | ₹ / $ | `229.27` -> `238.90` |
| quantity | Shares bought: whole shares in India, fractional in the US (6 decimals); never recomputed | F1.4 | shares | India `84`, US `4.36167` |
| exit_quantity, adjustment_ids | Shares after a split or bonus in the window, and that adjustment | `adjustments` (exists) | shares, ids | `4.36167`, empty |
| entry_value, exit_value | Quantity × price | engine | ₹ / $ | `1000.00` -> `1042.00` |
| gross_pnl | Profit before costs | engine | ₹ / $ | `42.00` |
| costs, cost_lines | Round-trip charges with their parts, the **market-cost view** that strategies are ranked on (F1.6; rates in `config/costs.yaml`, marked verify). India: brokerage (0.75 %, at least ₹50 per order), STT, exchange, SEBI, stamp duty, GST. US: BUX order fee converted to $, SEC fee. The owner's own extra charges are in the [Cost view](#cost-view) | B2's engine | ₹ / $ | `2.34` = order fee `2.32` + SEC fee `0.02`; India RELIANCE N+1 `1966.41` |
| net_pnl | Profit after costs (the headline number) | engine | ₹ / $ | `39.66` |
| return_pct | Net profit as % of the amount (compares across amounts, decision 44) | engine | % | `3.97` |
| prob_up, target_price, lo80, hi80 | What was predicted | prediction | 0-1, ₹ / $ | `0.583`, `227.84`, `218.36`-`237.72` |
| target_error_pct | How far the exit close was from the target | F1.9 | % | `4.85` |
| range_hit | Exit close inside the 80 % range | F1.9 | yes/no | `false` |
| target_reached, target_reached_session | Whether any session's high from D to the exit reached the target, and the first such session (1 = D) | F1.9 (adjusted bars) | yes/no, number | `true`, `1` |
| max_favourable_pct, max_adverse_pct | Best high and worst low in the window, against the entry | F1.9 | % | `4.72`, `-0.48` |
| settled_at, supersedes | When it was settled; the row it replaces after a correction | engine | time, id | `2026-10-05T22:15:00Z` |

<a id="automatic-reason"></a>
### Automatic reason (part of every settled trade)

Computed, no AI (F1.10, decision 43). The move from entry to exit is split into four parts that add up to the
move. These parts feed the reason-code heatmaps.

| Field | Meaning | Unit | Example (NVDA N+3) |
|---|---|---|---|
| move_pct | Exit vs entry | % | `4.20` |
| market_pct | The part the market explains (beta × benchmark move) | % | `2.05` (SPY +1.09 %, beta 1.874) |
| sector_pct | The sector's move beyond the market (sector index, ETF or peer) | % | `1.70` (XLK) |
| news_pct | The rest of the move after market and sector, credited to news only when verified news (confirmed_primary or corroborated) was published (else first seen) from D's open to the exit close and its summed sentiment has the same sign; else 0 (B2's `lab/reasons.py`) | % | `0.45` |
| company_pct | What is left: company-specific | % | `0.0` |
| reason_code, reason_codes | The main cause, and all codes that apply | `market_up`, `market_down`, `sector_lift`, `sector_drag`, `news_positive`, `news_negative`, `company_specific`, `target_reached`, `range_missed` | `market_up`; `[market_up, target_reached, range_missed]` |
| news_ids | Verified news published (else first seen) inside the window | ids | `["d93b1f5e7c2a4b60"]` (published 2 Oct) |
| reason_detail | Benchmark, beta, sector source, news statuses | JSON | `{"benchmark": "SPY", "beta": 1.874, "sector_source": "XLK"}` |

The examples follow B2's split (`marketbrief/lab/reasons.py`).

<a id="cost-view"></a>
## Cost view

The two cost views of one record (owner decisions 50-51):
- **market cost**: the costs strategies are ranked on, the same as the [paper trade](#paper-trade)'s `costs`;
- **your cost**: market cost plus the owner's own charges. India: the NRI reporting charge ₹200 on the buy date and
  ₹200 on the sell date, and the DP charge. US: BUX's FX markup 0.75 % each way and the 0.20 % a year portfolio fee,
  pro-rated.

It also holds the **cost-viable** flag: whether the expected gain after your cost is above zero (owner decision of
2026-10-07, built by B2). That is `expected_gain_your_pct = p × move − (1 − p) × loss − your_cost_pct > 0`, with
the same conditional move and loss as the [head-to-head pick](#head-to-head-pick) (`marketbrief/lab/gain.py`). The
Slack morning picks (session B6) use the same rule. A prediction is made, traded and scored either way; the flag is
shown, and a non-viable head-to-head candidate can still be picked. A prediction without a probability (the
always-up and momentum baselines) has no expected gain, so its flag is empty.

Status: kind `cost_views`. Session **B2** writes it (`core/schema_b2.py`, `marketbrief/lab/cost_views.py`) and owns
it; it is joined to the other records on `record_id`. W1 keeps it as B2's kind rather than folding it into
`paper_trades_settled`, because the your-cost view is an owner-specific layer on top of the market view the
strategies compete on.

Example file: `cost_view.json` (199 rows, built with B2's own row functions):
- 118 prediction rows: every qualifying prediction of NVDA and RELIANCE on 7 Oct (20 of them baselines without a
  probability, so with an empty flag);
- 16 pick rows;
- 65 settlement rows.

None of the example predictions or picks is cost-viable: a round trip at your cost is about 1.7 % (US) and 2.4 %
(India), and every example's expected gain after your cost is below zero (at best -0.69 %).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| id, record_kind, record_id | `cv:<kind>:<record id>`; which record it describes: a prediction or pick before the open, a settled trade after the close | B2 | text | `cv:settlement:acc:rule.model_news.v1:2026-09-29-NVDA-3d@20261005T221500Z` |
| trade_id, prediction_id, strategy_id, ticker, horizon_days, session_date, exit_date, amount, currency | The record's keys | the record | text, date, ₹ / $ | `NVDA`, `3`, `1000`, `USD` |
| reference_price, target_price | C (the latest close; for a settlement, the entry price) and the target | prediction | ₹ / $ | `229.27`, `227.84` |
| expected_move_pct | `(target / C − 1) × 100` (predictions and picks only) | B2 | % | RELIANCE N+3: `0.225` |
| market_cost_pct, your_cost_pct | The round trip in each view as a % of the amount | B2 | % | `1.99`, `2.4299` |
| expected_gain_your_pct | `p × move − (1 − p) × loss − your_cost_pct` (predictions and picks only) | B2, `lab/gain.py` | % | `-1.9891` |
| cost_viable | Expected gain after your cost is above zero (predictions and picks only; empty without a probability) | B2, decision 51, owner decision of 2026-10-07 | yes/no | `false` |
| market_costs, market_cost_lines | The market view, total and per charge | B2 | ₹ / $ | `2.34` = order fee `2.32` + SEC fee `0.02` |
| your_costs, your_cost_lines | Your view, total and per charge | B2 | ₹ / $ | `17.68` = market lines + FX markup `15.31` + portfolio fee `0.03`; India adds `nri_reporting_buy` and `nri_reporting_sell` `200` each and `dp_charge` |
| net_pnl_market, return_pct_market, net_pnl_your, return_pct_your | Profit after costs in each view (settlements only) | B2 | ₹ / $, % | `39.66` / `3.966`; `24.32` / `2.432` |
| holding_days | Calendar days from D to the exit (the US portfolio fee) | calendar | days | `5` |
| eurusd_entry, eurusd_exit | The EUR/USD closes used for the US order fee and FX markup | `EURUSD=X` (B2) | rate | `1.17` (example rate) |
| computed_at, method_version | When it was computed; engine version | B2 | time, text | `engine-v1` |

<a id="open-trade"></a>
## Open trade

A trade that has entered but not yet exited. Status: **derived for pages** (B4, `rm.trades`). It is computed from
qualifying [predictions](#prediction), the entry bar and the latest close. Example file: `open_trade.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| trade_id, view, strategy_id, ticker, horizon_days | Which trade, in which view (accuracy or head-to-head) | prediction, pick | text | `acc:rule.model_news.v1:2026-09-29-NVDA-5d`; `h2h:highest_probability:ai.combined.opus.v1:2026-09-29-NVDA-5d` |
| entry_date, exit_date, entry_price, quantity | Entered when and at what price; planned exit | bars, engine rules | date, ₹ / $, shares | `2026-09-30`, `2026-10-07`, `229.27`, `4.36167` |
| target_price, lo50..hi80 | What was predicted | prediction | ₹ / $ | `228.03`; 80 % `215.86`-`240.88` |
| last_price, last_price_date | Latest stored close (intraday: see [trade check](#trade-check)) | `ohlc_raw` | ₹ / $ | `239.24` |
| unrealised_pnl, unrealised_pct | Profit so far, before costs | derived | ₹ / $, % | `43.49`, `4.35` |
| to_target_pct | Distance from the last price to the target | derived | % | `-4.69` (already past it) |

<a id="trade-check"></a>
## Intraday trade check

Twice per session, every open paper trade is compared with its prediction (F5; monitoring only, never a trade).
Status: kind `trade_checks`. Session **B9** writes it, on top of the existing per-company `intraday_checks`, which
**exist** (WS5) and hold the market, sector and news candidates. The prices of the prediction are stored as
predicted; every measure is on today's price basis (after a split or bonus in the window). Rows written before issue
#78 keep the measures from `quality` on in B9's `trade_check_details`; the view `trade_check_rows` joins both.
Example file: `trade_check.json` (the RELIANCE N+4 trade checked at 11:13 IST is the example below).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| check_at, session_date | When the check ran | intraday run | time | `2026-10-07T05:43:00Z` (11:13 IST) |
| trade_id, strategy_id, ticker, horizon_days | Which open trade | trades | text | `acc:rule.model_news.v1:2026-09-29-RELIANCE-4d` |
| session_number | Which session of the holding window today is (1 = D) | calendar | number | `5` |
| entry_price, last_price, ret_since_entry_pct | Entry, latest 5-minute price, move since entry | Yahoo 5-min bars | ₹ / $, % | `1182.0`, `1224.6`, `3.6041` |
| target_price, to_target_pct | Target and the distance left (negative: already past it) | prediction | ₹ / $, % | `1184.81`, `-3.2492` |
| band | Where the price sits in the trade's own range | derived | `below80`, `below50`, `inside50`, `above50`, `above80` | `above50` (NVDA: `above80`) |
| flags, flagged | Warnings | F5 | `outside_range`, `far_from_target`, `against_prediction` | NVDA `["outside_range"]` |
| check_id, check_row_id | The check (`ic-<market>-<time to the minute>`), and the company's intraday check row (market, sector and news causes; the explainer's note); empty for a company not on the watchlist | `intraday_checks`, `intraday_explanations` (exist) | id | `ic-india-2026-10-07T05:43Z`, `ic-us-2026-10-07T16:27Z-NVDA` |
| target_z | Distance to the target in 1-day volatility units, scaled to the sessions left | B9 | number | `-2.182` (past the target) |
| family, pick_rule | The trade's family; the pick rule for a head-to-head trade | trade | text | `rule`, empty |
| quality | Whether the price could be measured; anything but `ok` means no measures and no flags | B9 | `ok`, `stale_quote`, `no_quote`, `no_entry_price` | `ok` |
| entry_source | Where the entry price came from | B9 | `intraday_open` (D is today), `stored_open` | `stored_open` |
| basis_factor, entry_adj, target_adj, lo80_adj..hi80_adj | The split/bonus factor since the prediction, and the trade's prices on today's basis | `adjustments` (exists) | factor, ₹ / $ | `1.0`, `1182.0`, `1184.81`, 80 %: `1131.42`-`1240.71` |
| last_time | Start of the 5-minute bar the last price is from | Yahoo 5-min bars | time | `2026-10-07T05:35:00Z` |
| sigma_1d, elapsed_fraction | 1-day volatility; share of today's session already past | features, calendar | fraction | `0.017987`, `0.3147` |
| sessions_held, sessions_left | Sessions held so far (today's part included) and sessions to the exit close | calendar | sessions | `4.3147`, `0.6853` |
| z_since_entry | Move since entry in volatility units (`against_prediction` at -1 or below) | B9 | number | `0.965` |
| target_reached, target_reached_session | Whether a high since D reached the target so far, and the first such session (1 = D); empty when unknown | bars | yes/no, number | `true`, `1` |
| high_since_entry_pct, low_since_entry_pct | Best high and worst low since entry | bars | % | `3.6041`, `-1.7936` |
| notes | Data notes | B9 | `no_bar_<date>`, `no_sigma`, `not_on_watchlist` | empty |

A day's path for one prediction (made -> checks -> settled -> explained) combines a [prediction](#prediction),
its trade checks, its [settled trade](#paper-trade) and any [AI reason](#ai-reason) (read model `rm.lifecycle`,
last 30 sessions).

---

<a id="ai-reason"></a>
## AI reason

A plain-language reason of at most 60 words, written after the close by the end-of-day analyst. It is written
for every head-to-head trade settled that day and for the day's 5 biggest wins and 5 biggest misses (F6.1,
decision 43). It is grounded in the trade's automatic reason, cites ids and passes a deterministic check. Status:
kind `trade_reasons_ai`; session **B3** writes it. Example file: `reason_ai.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| trade_id, ticker, strategy_id, session_date | Which trade, on which day | settlement | text | `h2h:highest_probability:rule.model_news.v1:2026-09-29-RELIANCE-3d` |
| kind, rank | Why it got a reason | F6.1 | `head_to_head`, `biggest_win`, `biggest_miss`; rank 1-5 | `biggest_win`, `1` |
| text | The reason | EOD analyst (gated) | ≤ 60 words | "RELIANCE moved +3.05% from entry: the market explains +0.46 points and the sector -3.10. Verified news nse-ann-7790412 added about +5.69 points..." |
| cited_ids, reason_codes | What it cites | gate | ids, codes | trade id + `nse-ann-7790412` |

<a id="eod-analysis"></a>
## End-of-day analysis

The post-close summary per market: today's result per family (rule, baseline, AI) and per pick rule (F6.1).
Status: kind `eod_analyses`; session **B3** writes it. Example file: `eod_analysis.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| session_date, settled_trades | The day, and the trades settled that day | settlement | date, count | `2026-10-06`, `11` (India) |
| results | Per family (accuracy view): trades, wins, net profit; per pick rule: trades, net profit | deterministic | JSON | `{"rule": {"trades": 2, "wins": 1, "net_pnl": -975.83}}` |
| summary | The analyst's text, citing ids | EOD analyst (gated) | ≤ 150 words | "11 paper trades settled today..." |
| reason_ids | The [AI reasons](#ai-reason) written with it | analyst | ids | `tra:...` |

<a id="scoreboard-row"></a>
## Scoreboard row

How a strategy is doing (F7). Status: **derived for pages**. B2 computes the rows (`marketbrief/lab/scoreboard.py`)
and B4 serves them (`rm.strategies`, `rm.compare`). Example file: `scoreboard_row.json` (152 rows, built with B2's
own scoreboard code from the example trades and their your-cost numbers, so every count matches `paper_trade.json`).

There is one row per market × view × basis × slice:
- per strategy, with every horizon pooled ("all") and for each horizon;
- per strategy and company (the stock strategies page), all horizons and each horizon;
- per family and pick rule (head-to-head portfolios), all horizons and each horizon;
- per strategy and regime at prediction time, all horizons (F2.6: the effect of regimes is measured).

Money and returns are in the market-cost view (strategies are ranked on it). The `your_cost` block repeats them in
the your-cost view, which the go-live bar uses.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| scope | Which cut | F7.1 | `strategy`, `strategy_company`, `pick_rule`, `strategy_regime` | `strategy` |
| view, basis, strategy_id, family, horizon_days | Which slice (examples below: US, accuracy, forward, `rule.model_news.v1`, all horizons) | settled trades | text; `all` or k | `accuracy`, `forward`, `rule.model_news.v1`, `all` |
| ticker | The company, for `strategy_company` rows (else empty) | settled trades | text | `NVDA`: 4 trades, $103.48 |
| pick_rule | The pick rule, for `pick_rule` rows (head-to-head view; strategy_id empty, family set) | settled trades | text | rule family, `highest_probability`: 1 trade, $41.15 |
| regime | The regime at prediction time, for `strategy_regime` rows | `regime` | text | `EVENT_HEAVY` (India) |
| trades | Settled trades in the slice | count | count | `10` |
| first_entry, last_exit | First entry and last exit of the slice's trades | trades | date | `2026-09-30`, `2026-10-06` |
| net_pnl | Profit after costs: the headline | sum | ₹ / $ | `99.00` ($) |
| mean_return_pct | Average return per trade | mean | % | `0.992` |
| win_rate | Share of trades with a profit after costs | count | 0-1 | `0.7` |
| target_reached_rate, median_reached_session | Share that touched the target, and the typical session it happened | F1.9 | 0-1, number | `1.0`, `1` |
| avg_target_error_pct | Average miss of the target | F1.9 | % | `1.604` |
| range_hit_rate | Share of exit closes inside the 80 % range | F1.9 | 0-1 | `0.9` |
| worst_losing_streak | Most losses in a row | sequence | count | `2` |
| max_drawdown | Deepest fall of cumulative profit from its peak | sequence | ₹ / $ | `-11.24` |
| luck_test | Bootstrap interval of the mean return per trade (`n` trades), and the same interval corrected for the `m` rows compared with it (Bonferroni). Only `corrected: true` counts as an edge; fewer than 2 trades give no interval | F7.1, `lab/luck.py` | %, yes/no | n `10`, m `5`: `0.006` to `2.076` (excludes zero), corrected `-0.1701` to `2.467`, `corrected: false` |
| your_cost | The same row in the your-cost view: net_pnl, mean_return_pct, win_rate, worst_losing_streak, max_drawdown, luck_test | B2 | mixed | net `-52.09`, win rate `0.3` |
| sample_badge | Fewer than 20 trades: "too few trades to rank" (greyed out, SPEC section 6) | rule | `ok` / `too_few_to_rank` | `too_few_to_rank` |
| go_live | Strategy rows: position against the go-live bar on the your-cost view: `proven`, `months_forward`, `trades_needed`, `beats_best_baseline`, `best_baseline_net_pnl`, `drawdown_limit`, `drawdown_within_limit`, `holds_in_calm_and_volatile`, `cost_view` | F7.2 | mixed | not proven; `0.2` months; `290` trades needed; best baseline `33.88` not beaten; limit `10000.0` |
| as_of | The newest close the rows are computed to | settlement | date | `2026-10-06` |

Heatmaps (F2.8) use the same numbers by strategy × horizon, × company and × reason code, each week.

<a id="research-review"></a>
## Research review

The weekly research director's report (F6.2). It covers who is ahead and why, which information helped, and
proposals as config diffs for the owner to approve; it changes nothing itself. Status: kind `research_reviews`;
session **B3** writes it. Example file: `research_review.json` (one review per market).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| iso_week, period_start, period_end | The week | run | text, dates | `2026-W41` |
| leaders | Who leads in each family | scoreboard | list | `rule.model_news.v1`: $61.4 on 38 trades |
| findings | Findings with ids | director | list | "Corroborated product news added about 0.6 points..." |
| proposals | Suggested changes as diffs, each `proposed` until the owner approves | director | list | a new strategy version with threshold 0.57 |
| report_path | The full markdown report | run | path | `reports/us/research-2026-W41.md` |

---

<a id="news-item"></a>
## News item

One article or announcement, with its verification status. Status:
- Stored news, the analyst's scores (`news_enriched`), clusters and verification status (`news_verified`)
  **exist**.
- The headline history **exists** since the Wave 0 news fix (one item per link and market, a later headline at the
  same link kept as a `news_updates` row; decisions 45-46; the `news` view shows the latest headline by now).
- The combined record is **derived for pages** (B4, `rm.news`).

Example file: `news_item.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| id | News id | `news` (exists) | text | `a41c9e07b2d35f18` |
| tickers, primary_tickers | Companies it is about | news tagger (exists) | list | `["NVDA"]` |
| title | Latest headline as of now | `news` view (latest `news_updates` title) | text | "Nvidia wins multi-year data-centre order..." |
| source, source_domain, url | Outlet and link | `news` | text | `Reuters`, `reuters.com` |
| published_at, first_seen_at | When the outlet published it, and when we first stored it (calls may use it only after this) | `news` | time | `2026-09-29T21:10:00Z`, `2026-09-29T22:47:05Z` |
| enrichment.event_type | Category | news analyst (`news_enriched`) | `earnings`, `macro`, `product`, `legal`, `sector`, `analyst`, `ma`, `flows`, `other` | `product` |
| enrichment.materiality, sentiment, relevance, novelty, urgency, priced_in | How much it matters, its tone and so on | same | levels, -1..1, 0-1 | `high`, `0.6` |
| status | Verification status (DESIGN 3b) | `news_status.py` (exists) | `confirmed_primary`, `corroborated`, `single_source`, `unverified`, `rumour`, `promotional`, `contradicted` | `corroborated` |
| status_as_of | Time the status refers to | `news_verified_asof` | time | `2026-09-30T11:15:00Z` |
| independent_origins, primary_ids, cluster_id | Independent outlets confirming it; filings or exchange announcements behind it; its same-event group | `news_clusters` (exists) | count, ids | `2`, `[]` |
| headline_history | Earlier headlines at the same link, with when each was seen | `news_updates` (exists) | list | "Nvidia said to win data-centre order" at `2026-09-29T22:47:05Z` |

Rumour and promotional items never support a call. A single-source or unverified item lowers the confidence of
any call that cites it.

<a id="news-impact-row"></a>
## News-impact row

"Which news moves prices, and how much" (F3). It gives the average move beyond the market and sector after news
of one category, status and materiality, for each horizon. It is refreshed weekly. Status: kind `news_impact`;
session **B2** writes it. Example file: `news_impact.json` (both markets).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| iso_week, as_of | Week and cut-off (no later information used) | run | text, time | `2026-W41` |
| event_type, status, materiality, horizon_days | The slice | news + status | text, k | `earnings`, `confirmed_primary`, `high`, `1` |
| n_events | Events in the slice | count | count | `34` |
| mean_abnormal_pct, ci_low_pct, ci_high_pct | Average move beyond market and sector, with its 95 % interval | F3 | % | `1.12` (`0.21` to `2.03`) |
| mean_benchmark_pct, mean_sector_pct | The market's and the sector's average move over the same windows | F3 | % | `0.08`, `0.15` |
| enough | False shows "not enough events yet" | rule | yes/no | `false` with 4 events |

<a id="results-digest"></a>
## Results digest

Quarterly results and earnings-call texts of a watchlist company. The numbers are as reported at the release and
there are at most 5 quoted bullets (WS6). Status: kind `results_digests` **exists**; the context pack does not
show it yet. Example file: `results_digest.json` (JPM Q2 2026 and HDFC Bank Q1 FY27, the India one with numbers only because
no PDF parser reads NSE attachments yet: `status` `text_unavailable`; the numbers are illustrative).

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| id, release_kind | Release id; results or earnings call | `results_digest.py` (exists) | text | `JPM-results-2026-07-14`, `results` |
| release_at, release_timing | When it was released; before the open, during or after | filing time | time, text | `2026-07-14T10:45:12Z`, `before_open` |
| fiscal_label, period_end, basis, currency | Which quarter, and on which basis | filing | text | `Q2 2026`, `consolidated`, `USD` |
| status, numbers_status | Whether the text and numbers are ready | script | `ok`, `pending_report`, ... | `ok` |
| numbers | Revenue, profit, EPS, margins, year-on-year and quarter-on-quarter growth, as filed (never later restatements) | SEC XBRL / NSE filing | currency, % | revenue `46.1 bn`, EPS `5.31`, revenue YoY `6.42 %` |
| consensus | The analysts' estimate collected before the release (context only) | Yahoo (exists) | EPS, % | estimate `5.05`, surprise `5.15 %` |
| reaction | Stock vs market move around the release | bars | % | stock `1.84`, excess `1.63` |
| bullets | At most 5 points, each with a verbatim quote and its source | results-analyst (gated) | list | "Quarterly net income was $15.2 billion." |
| sources | Filings it was read from | script | list | SEC 8-K exhibit 99.1 |

---

<a id="portfolio"></a>
## Owner's paper portfolio

The owner's own manual paper trades (they exist: WS4 `portfolio_trades`, `scripts/portfolio.py`). Session **B2**
adds the € view of US positions, with the rate change and BUX's FX fee (F1.11, decision 11). The head-to-head
portfolios per family and pick rule are [scoreboard rows](#scoreboard-row) of the head-to-head view. Status: trades
and positions **exist**; the € view is **B2**. Example file: `portfolio.json`.

| Field | Meaning | Source | Unit | Example |
|---|---|---|---|---|
| owner_trades | Each recorded trade: side, quantity, price and its basis (open, close or manual), date, channel | `portfolio_trades` (exists) | rows | buy 3 AAPL at the open of 30 Sep, `330.80` |
| positions.quantity, avg_price, last_close | Holding and its marks | FIFO (exists) | shares, ₹ / $ | `3`, `330.80`, `333.63` |
| positions.cost, value, pnl, pnl_pct | In the trade currency | exists | ₹ / $, % | `992.40`, `1000.89`, `8.49`, `0.86` |
| eur_view.eurusd_at_buy, eurusd_now, mark_date | EUR/USD on the buy date and now (`EURUSD=X`, added by B2); the date of the mark | Yahoo | rate, date | `1.165`, `1.17`, `2026-10-06` |
| eur_view.fx_fee_rate | BUX's FX markup on each EUR/USD conversion (`config/costs.yaml`, verify) | config | fraction | `0.0075` |
| eur_view.cost_usd, value_usd | Dollars paid, including the buy order's cost, and dollars held now | B2 | $ | `993.55`, `1000.89` |
| eur_view.cost_eur | Euros needed to buy those dollars: `cost_usd / eurusd_at_buy × (1 + fx_fee_rate)` | B2 (`portfolio/eur_view.py`) | € | `859.23` |
| eur_view.value_eur | Euros back if converted now: `value_usd / eurusd_now × (1 − fx_fee_rate)` | B2 | € | `849.05` |
| eur_view.pnl_eur | `value_eur − cost_eur` | B2 | € | `-10.19` |
| eur_view.fx_effect_eur | The part due to the rate change alone: `value_usd / eurusd_now − value_usd / eurusd_at_buy` | B2 | € | `-3.67` |

The default amounts are ₹1,00,000 and $1,000; every number is labelled Paper.

---

<a id="combinations"></a>
## What a page can combine (examples)

- **Home (per market, horizon selector N+1..N+5).** Shows:
  - the top 5 of [Agreement](#agreement);
  - today's [head-to-head picks](#head-to-head-pick);
  - rule vs AI today, from the [EOD analysis](#eod-analysis) `results`, and to date, from the
    [Scoreboard](#scoreboard-row);
  - [open trades](#open-trade) and alerts (flagged [trade checks](#trade-check));
  - [market status](#market-status) with the benchmark and volatility index;
  - the coming week of [calendar events](#calendar-event).
- **Stock strategies (decision 30).** For one ticker:
  - [Agreement](#agreement) at every horizon;
  - the four [head-to-head picks](#head-to-head-pick) with their `candidates`;
  - scoreboard rows for that company, with `sample_badge` and `luck_test` beside every profit;
  - today's [predictions](#prediction) per strategy (target and range);
  - the best strategy overall beside the per-company best.
- **Company.** Shows:
  - [Company](#company) and its [predictions](#prediction) drawn on the price chart (target and 50/80 % bands);
  - today's path from the [trade checks](#trade-check);
  - [settled trades](#paper-trade) with their [automatic](#automatic-reason) and [AI reasons](#ai-reason);
  - [news](#news-item) with status, the [results digest](#results-digest) and its
    [calendar events](#calendar-event).
- **Strategy lab, Rule vs AI, Paper portfolios, Track record, News, Companies.** These use the
  [Scoreboard](#scoreboard-row), [Research review](#research-review), [News-impact](#news-impact-row),
  [Portfolio](#portfolio), [Lifecycle events](#lifecycle-event) and [Commands](#command) (pending requests).

<a id="technical-fields"></a>
## Technical fields (bookkeeping, not usually shown)

These columns appear on several records. A page rarely shows them; they link records, record when something was
written, and say which version of a method or prompt wrote it.

| Field | On | Meaning | Example |
|---|---|---|---|
| range_id | prediction | The `ranges` row the prediction's band was copied from (`<as-of date>-<ticker>-<k>d`) | `2026-10-06-RELIANCE-3d` |
| model_score_id | prediction | The `model_scores` row the probability came from (empty for strategies that do not use the model) | `2026-10-06-RELIANCE-3d` |
| config_hash | prediction | A fingerprint of the strategy's registry entry, so a changed entry is detectable | `sha256:e36a2f3d91456272` |
| pick_id | paper trade | The head-to-head pick a head-to-head trade came from (empty in the accuracy view) | `h2h:2026-09-29-NVDA-rule-best_expected_gain` |
| settlement_id | AI reason | The settled-trade row the reason was written for | `h2h:highest_probability:rule.model_news.v1:2026-09-29-RELIANCE-3d@20261006T121500Z` |
| check_id, check_row_id | trade check | The intraday check (`ic-<market>-<time to the minute>`) and the company's row in it | `ic-us-2026-10-07T16:27Z` |
| target_z | trade check | Distance to the target in 1-day volatility units over the sessions left; `far_from_target` at 2 or more | `-2.182` |
| method_version, validator_version | most records | Which version of the deterministic code wrote the row | `engine-v1`, `lab-v1`, `tc-v1` |
| prompt_version | AI-written records | Which version of the agent's instructions was used | `trader-v1`, `eod-v1` |
| made_at, created_at, computed_at, written_at, settled_at, recorded_at, received_at, completed_at | all records | When the row was written (UTC). Every page reads data only up to its own "as of" time by these columns, so nothing from later leaks into an earlier view | `2026-10-07T11:45:00Z` |

<a id="requests"></a>
## How to ask for a new field

A field the catalogue lacks is a "new data request" (SPEC section 10): the owner approves it, and the orchestrator
adds it here and to the example files, with a judge review. Ask with the page, the field's meaning, and an
example value.
