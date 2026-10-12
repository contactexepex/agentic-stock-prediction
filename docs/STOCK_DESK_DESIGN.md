# Stock desk design: a team of experts finding net profitable stock trades

Version 1 draft (12 Oct 2026), for the owner and ChatGPT to review. **Design only: nothing is built or changed until
both AIs agree every section and the owner approves** (section 12). It adapts the F&O desk design approved on 12 Oct
2026 (`exepex/trading`, `docs/DESK_DESIGN.md` v2.1, `AGENTS.md`, review 8) to this project: cash stocks on NSE (India)
and US exchanges, held 1-5 sessions (N+1..N+5), paper only. It adds to the existing system; it does not replace the
approved accounts and evaluation plan (`docs/PLAN_v16.md`), the strategy lab (DESIGN.md section 17) or the rules in
`CLAUDE.md`.

## 1. Why a team, and the goal

**Goal:** find stock trades that are profitable **after the owner's own costs** (`config/costs.yaml`, your-cost view:
brokerage, taxes and fees, India's NRI reporting charge of Rs 200 on the buy date and on the sell date, the DP charge,
BUX's FX markup and fee), proven on stored data and then on paper, before any real money. Research only: the system
never places orders and nothing here is investment advice.

**Why many roles (the owner's reason, 12 Oct 2026):** finding winning trades is a team effort, not one person's job.
Each expert looks at the same data from their own field (results, prices, flows, news, the economy, costs, risk),
challenges the others, and the team combines what survives. No single role, and no single model, decides a trade.
The machine's advantage is memory and testing power: every pattern can be checked on every stored day. Its danger is
the same power: testing many patterns finds lucky ones (section 6), so the team works under strict evidence rules.

**Where we start (honest):**
- The signal model shows no tradable skill after costs (`model_skill` false; DESIGN.md section 15.1); the rule
  strategies trade only when it leans clearly, so on 12 Oct India's rule strategies opened no trades.
- The first paper trades settle from 13 Oct 2026; no strategy is proven.
- Small moves rarely pay at the owner's cost: in India, Rs 400 of reporting charges per round trip alone needs a
  0.4% move on a Rs 1 lakh trade before any other cost.

**The first question for every idea:** who pays us and why will they keep paying; what measurable, entry-known sign
says it is happening today; what would prove it wrong.

## 2. The edge map for stocks (all untested unless stated)

Each family names who pays (the economic reason), the owning roles and the data we already store or can collect.

| # | Edge family | Who pays us, and why | Owning roles | Data (stored today unless marked) | Evidence now |
|---|---|---|---|---|---|
| S1 | Results reaction and drift | Investors under-react to results and guidance; prices keep moving for days | Equity research, results analyst, statistician | NSE results filings, SEC 8-K 2.02 and XBRL, consensus EPS point in time, prices | Untested |
| S2 | News under- or over-reaction | Slow readers move prices after verified news; crowds overreact to rumours | News analyst, claim checker, behavioural finance | News with verification status, article extracts, clusters | Untested; news enters the model only as a fixed prior |
| S3 | Forced and slow flows | Funds that must buy or sell (FII/DII flows, index changes, block deals) move prices for reasons other than value | Flows analyst, market microstructure | FII/DII and FPI flows, bulk and block deals, delivery %, 13F, short interest | Untested |
| S4 | Insider and promoter signals | Insiders and promoters know their company; pledges signal stress | Corporate-actions analyst, investment banker | SEBI PIT trades, pledges, Form 4, 13D/13G | Untested |
| S5 | Momentum and reversal | Trend-following and overreaction by other traders | Technical analyst, quant modeller | Prices, indicators, regime | A momentum baseline trades in the lab from 12 Oct; no forward result yet |
| S6 | Sector and market rotation | Money moving between sectors and with global cues | Sector analyst, macro economist | Sector indices, global cues, FX, rates, commodities | Cross-market model features: no tradable skill in the 15-year test |
| S7 | Corporate actions and events | Splits, bonuses, dividends, buybacks, index inclusion around known dates | Corporate-actions analyst, regulation | Events calendar, adjustments, NSE announcements | Untested |
| S8 | Cost advantage | Not an edge alone: few, patient trades with the move large enough to beat the owner's cost | Cost accountant, execution | `config/costs.yaml`, cost views | Measured per trade; the cost bar is high |

**Out of scope at first** (our data and schedule, not proof of no edge): intraday trading, high-frequency patterns,
short selling, leverage, small illiquid stocks outside the watchlist.

## 3. The team

### 3.1 Roles and how each runs

Every role works for the same goal. Each produces **finding cards** (section 3.2). "Existing" means an agent or code
path we already have, which takes on the role's way of working; "new" means it must be built.

| Role | Field and edge families | Runs as | Today |
|---|---|---|---|
| Head of desk | Sets the question, makes every role contribute, records decisions | AI | New (the research director does part of it weekly) |
| Portfolio manager | Who pays, ranking ideas against no trade, allocation, when to switch a strategy off | AI for research; code for daily allocation | New |
| Equity research analyst | S1: results against expectations, guidance, valuation | AI | Existing results-analyst (extended) |
| Technical / price-pattern analyst | S5: trends, ranges, reversals, indicators | Code measures + AI | Existing trader-pattern-mood (as a role) |
| Sector analyst | S6: sector moves, relative strength, peers | Code + AI | New |
| Macro economist | S6: RBI/Fed, rates, rupee/dollar, crude, global cues and gaps | AI | New (cues exist as data) |
| Flows / positioning analyst | S3: FII/DII, FPI, delivery %, block deals, short interest, 13F | Code + AI | New (data exists) |
| Corporate-actions analyst / investment banker | S4, S7: insider and promoter trades, pledges, splits, buybacks, fund raises | AI | New (data exists) |
| News analyst | S2: scores every new item | AI | Existing news-analyst |
| Claim checker | S2: verifies claims against primary sources | AI | Existing claim-checker |
| Behavioural finance | S2, S5: the crowd's biases and our own (chasing, overtrading) | AI | New |
| Statistician / quant researcher | Sample size, controls, out-of-sample, multiple testing | Code + AI | Partly (lab luck test, Bonferroni) |
| Quantitative modeller | Forecasts tested out of sample (the signal model, ranges) | Code | Existing model and ranges |
| Mathematician | Expected value per trade after cost, break-even move | Code + AI | Partly (`lab/gain.py`) |
| Execution / microstructure | Open and close prices, gaps, liquidity, slippage assumptions | Code + AI | Partly (open-to-close basis) |
| Tax and cost accountant | Net result at the owner's cost | Code | Existing (`lab/costs.py`) |
| Risk manager | Per-trade and portfolio limits, correlation, drawdown brake | Code | **New** (section 8) |
| Data and backtesting engineer | Data quality, availability times, no look-ahead | Code | Existing gates (`validate.py`, as-of reads) |
| Regulation | SEBI/NSE and SEC rules, trading windows, circuit limits | AI | New |
| Bull and bear researchers | The strongest case each way for a company | AI | Existing (become cross-examiners, 3.3 step 3) |
| Red team | Breaks every idea: luck, flattering period, disaster case | AI, a different model from the author | **New** |
| Judge | Verifies every claim and decision | Code checks + AI, a different model from the author | Existing for build work; extended to desk decisions |

Roles with nothing to say on a question report "not applicable". Not every role needs its own model call every day
(section 9); every AI role is kept only while its scorecard shows it adds value (3.4).

### 3.2 Finding cards

Each card: the observation (data, source, when it was known), the interpretation, the measurable implication for a
trade (direction, horizon N+k, size of move), confidence (strong / some / reasoning only), counter-evidence, and what
would prove it wrong. Never invented numbers; every number comes from stored data or the context pack (CLAUDE.md data
rule 4). The same evidence is counted once, however many roles cite it.

### 3.3 How an idea becomes a trade: no single role can make one

| Part | Question | Owner |
|---|---|---|
| Payer | Who pays us and why will they keep paying? | Portfolio manager, behavioural finance |
| Signal | What entry-known sign says it is happening today? | Statistician, quant modeller, the field's analyst |
| Context | Which results, events, flows or macro news in the holding window change it? | Equity, macro, flows, corporate actions, regulation |
| Price | Is the expected move larger than the owner's cost; can we get the open and close prices? | Mathematician, execution, cost accountant |
| Survival | Worst case, correlation with open trades, portfolio limits | Risk manager (code) |
| Attack | How could this be luck, a flattering period or a disaster? | Red team |

**The meeting** (research and daily use the same rhythm):
1. Question (head of desk).
2. Independent findings: each role works alone and submits cards before seeing the others (independent model calls).
3. Cross-examination: roles test each other's material assumptions; agreement after checking is a valid outcome.
4. Assembly (portfolio manager): combine findings into ideas; record disagreements.
5. Settle disagreements with data: the roles agree a test and its pass/fail before it runs; the result decides.
6. Red team, then judge (section 7).
7. Decisions: which ideas go to testing, to paper, or are dropped and why; the next question.

### 3.4 Scorecards: each role must earn its place

- **Optional judgement roles** (macro, sector, flows, news, behavioural, bull/bear, AI traders): compared on the same
  dated opportunities with and without the role's input (paired shadow decisions), as the difference in net result
  at the owner's cost after the role's own running cost; abstentions and rejections count; frozen before results.
- **Mandatory control roles** (data, risk, cost, judge's hard checks): scored on correctness and caught violations;
  never removed for a quiet period.

## 4. Two loops

- **Research loop (weekly, Friday 19:30 New York time, and monthly):** a meeting on one edge family -> idea -> test on
  stored data -> red team -> judge -> owner approval -> a strategy version in `config/strategies.yaml` -> paper -> results
  fed back. The research director's existing weekly run becomes this loop's head of desk.
- **Daily loop (the existing pre-open run):** data gates -> role reports on today's data -> each approved strategy's
  rule checked -> decision record -> judge (code checks) -> paper trade -> intraday checks -> post-close settlement
  and reasons.
- **Fixed policy, dynamic decisions:** a strategy is never invented and traded the same day. Daily choices happen only
  inside tested rules; any other change is a new version.

## 5. Strategy and decision records

- **Strategy version** (existing registry, extended): payer and edge family; entry-known conditions; horizon; size
  rule; exits; evaluation plan fixed before paper (expected range, review dates, pause rules); evidence links (test,
  red team, judge, owner); status.
- **Decision record** (per opportunity, code; mostly exists: predictions, reasons, checks, settlement and the "Full
  story" view): observations with availability times, the forecast, the trade, the expected net value at the owner's
  cost, the no-trade option, and disagreements.

## 6. Evidence rules

- **Idea ledger** (new, `research/LEDGER.md` or a data kind): every idea tried, including failures, before its result
  is read.
- **Discovery engine** (new, code; owned by the statistician and data engineer): a feature library with availability
  times (prices, results, news status, flows, insider trades, events, cues); a candidate generator; a scan after the
  owner's costs on discovery data; a mechanism filter (roles explain survivors); a bar that rises with the number of
  candidates tried (the scoreboard's existing luck test and Bonferroni correction extended to the whole ledger);
  confirmation on data not used for discovery, then forward paper. Example of the danger: among 1,000 random
  coin-toss rules, about 18 win 70% or more of 33 tries by luck alone.
- Pass/fail fixed before a test runs; no tuning on the check data; as-of reads only (no look-ahead); historical AI
  replays are exploratory and labelled `contaminated` before the model's training cutoff (existing rule).
- **Paper gate:** the approved go-live bar of `docs/PLAN_v16.md` applies unchanged.

## 7. Red team and judge

- **Red team:** a different model from the idea's author; attacks every idea that reaches paper.
- **Judge:** (1) hard validity in code (dates, ids, arithmetic, costs, limits; today's `validate.py` gates); (2)
  research sufficiency (sample, ledger count, counter-evidence); (3) interpretation (does the economic reason follow
  from the evidence). Fail = no trade or back to the author. Only the owner can overrule (2) or (3), in writing;
  overruled trades are scored apart. No one overrules a hard-validity failure.

## 8. Risk and money (the risk manager, code)

Today every qualifying prediction is its own paper trade (209 open in India on 12 Oct, many the same bet twice). That
stays for measuring strategies. The desk adds a separate **desk book**, the trades the team would actually take:
- per-trade amount from the existing per-company setting; a maximum loss per trade (proposed, set from research);
- at most N open trades and at most M per sector (proposed, set from research); identical bets counted once;
- correlation: trades on the same stock or sector, or all following the market, count as one bet;
- a drawdown brake: below a set amount from the high point, no new trades until the owner restarts in writing; open
  trades run to their own exits;
- stress tests of the whole book (market -5% overnight, sector shock, results gap).
The thresholds are proposals until research sets them and the owner approves.

## 9. Running cost

Cost is measured, not used to drop roles: numeric roles run as code; AI roles share model calls where their inputs
overlap and report "not applicable" when nothing applies; each AI role's cost is logged and its scorecard (3.4) must
show net value. The Sonnet / Opus split of CLAUDE.md stays; the red team and judge use a different model from the
author.

## 10. Build order (after approval)

1. Research meetings by hand on the edge map (S1 and S3 first: the data is stored), the idea ledger and the
   discovery engine on stored history.
2. Finding cards and independent findings for the existing agents; the red team; the risk manager and the desk book.
3. New AI roles (macro, sector, flows, corporate actions, behavioural, regulation) one at a time, each kept only if
   its scorecard shows net value.
4. Role scorecards in the weekly review; the head of desk in the weekly loop.

Each step is one batch under CLAUDE.md's delivery strategy: one builder, one judge review.

## 11. Open questions for review

1. Which edge families to research first (proposal: S1 results drift and S3 forced flows).
2. The desk book's limits (section 8): proposals to be set from research.
3. Whether the owner's own paper trades join the desk book or stay apart (proposal: apart).
4. Model for the red team (proposal: a different family from the author, e.g. Sonnet attacks Opus work).

## 12. Closing the design

| Section | Claude | ChatGPT | Owner |
|---|---|---|---|
| 1 Why a team, and the goal | Proposed | | |
| 2 Edge map | Proposed | | |
| 3 The team | Proposed | | |
| 4 Two loops | Proposed | | |
| 5 Records | Proposed | | |
| 6 Evidence rules | Proposed | | |
| 7 Red team and judge | Proposed | | |
| 8 Risk and money | Proposed | | |
| 9 Running cost | Proposed | | |
| 10 Build order | Proposed | | |

The design is final when both AIs mark every section "agreed" (or the owner settles a disagreement) and the owner
approves. No build starts before that.
