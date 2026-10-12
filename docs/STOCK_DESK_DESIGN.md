# Stock desk design: a team of experts finding net profitable stock trades

**Version 4 draft (12 Oct 2026), after ChatGPT reviews 1 and 2, for the owner and ChatGPT to review. Design only.** Nothing is built, run or
changed until both AIs agree every section and the owner approves (section 14).

**Sources read for this version, in full:**
- the F&O project `exepex/trading`:
  - the owner conversation of 12 Oct 2026 (`conversations/2026-10-12.md`);
  - ChatGPT reviews 1-11 and Claude responses 1-12 (`reviews/`);
  - `docs/DESK_DESIGN.md` v2.1 (approved as a framework), `docs/DESK_DECISIONS.md`, `AGENTS.md`;
  - the backtest analysis and strategy proposal (`reports/`), desk meeting 1 and the ledger (`research/`);
- this project's approved accounts and evaluation design, `docs/PLAN_v16.md`, and `CLAUDE.md`.

## 0. What changed, and why

**Version 4 (after [ChatGPT review 2](../reviews/chatgpt/review_2_2026-10-12-stock-desk-design.md); Claude's checks
in [response 3](../reviews/claude/response_3_2026-10-12-stock-desk-design.md)):**
1. Amendment A: 242/241 is the event inventory, not testable trades. Stored daily prices start on 7 Oct 2024, so
   only about 160 events per market have the entry and exit bars; meeting 1 first publishes a coverage table and
   either uses a frozen long-history snapshot (DC-12 (7)) or keeps to the covered period. Release time and filing
   acceptance time are kept apart (4, 11).
2. Amendment B: the power sentence is an assumption-based estimate, not a finding (11).
3. S9 details: the leader's news must be public before the pre-open cut-off; peers whose own results fall inside the
   holding window are reported apart (11). New research family S10, price-pressure recovery (4).
4. "No trade = 0" means incremental value against staying in cash (5.4).
5. Review 2's bounds on shadow role attribution (6); S9's price coverage noted (4); section 13's open questions
   replaced.

**Version 3 (after [ChatGPT review 1](../reviews/chatgpt/review_1_2026-10-12-stock-desk-design.md); Claude's
checks and reasons in [response 2](../reviews/claude/response_2_2026-10-12-stock-desk-design.md)):**
1. No "minimum size" rule for unexplained patterns: they stay research; anything registered uses v16's size (1.3).
2. S1 is drift still left at the first legal entry after the results blackout; S2's falsifier is net decision value;
   S7 uses DC-12's dividend and as-traded treatment; 13F is context; new family S9, cross-company transmission (4).
3. Every opportunity carries one record from information to money kept (5.4).
4. Two levels of scoring: v16's protocol for promotion, paired role-off shadow runs for a role's value (6).
5. The out-of-watchlist cohort is frozen before its outcomes are read and is called a cross-sectional challenge (8.3).
6. Meeting 1 uses review 1's tradable question and states the data limit: about 3 years of results dates (11).
7. Costs: the old Axis Direct average is not v16's hurdle; v16's break-even is 0.49-0.83% after Indian tax (2.9).
8. The red team and the judge never run on the author's model; this replaces section 10's model list (5.2, 10).
9. The risk manager's additions are diagnostics until a policy version adopts them (9).

**Version 2 (from version 1):**

Version 1 copied the F&O design too directly. Brutal list of its errors:

1. **It ignored this project's own approved plan.** `docs/PLAN_v16.md` already fixes the things version 1 called
   "proposals":
   - capital: ₹3 lakh India, $3,000 US;
   - size: account value ÷ 3;
   - at most 3 positions and 2 per sector;
   - a 10% loss brake;
   - a results blackout;
   - a $250/month ceiling for the whole system;
   - the cash, simple and no-AI comparators;
   - the registration and evaluation protocol;
   - the freeze guard.

   Version 2 sits on top of v16 and changes none of it (section 3).
2. **It treated the stored history as usable for discovery and checking.** PLAN_v16 2.5 records that **all stored
   history (2011 to 9 Oct 2026) has already been used** in development. The F&O desk had an untouched 2019-2023
   period; we do not. Section 8 handles this honestly.
3. **It listed 22 AI roles with no budget.** The owner's own decision caps the whole system at $250/month (v16 5.3).
   Version 2 states when each role runs and how its cost is measured (section 10).
4. **It stated hypotheses as facts.** For example, it said investors under-react to results. ChatGPT corrected the
   same error in the F&O design (reviews 1 and 10). In version 2 every edge is a hypothesis with a "what would prove
   it wrong".
5. **It missed the facts about where we stand** (section 2): a degenerate India model, coin-level skill, near-duplicate
   rule strategies, survivorship bias, and a cost hurdle that short holds must clear (corrected in version 3: costs
   call for selectivity, not a ban on short holds).
6. **It did not record the process lesson that led to the team design.** The F&O work drifted into auditing code
   instead of finding trades, until the owner stopped it. This project is drifting the same way (section 1.3).

## 1. Why a team of experts

### 1.1 The owner's reasons, in the owner's words

From the F&O conversation of 12 Oct 2026 (`conversations/2026-10-12.md`, quoted verbatim, "..." marks omitted words).
The owner asked to apply the same team approach here in this project's orchestrator session on 12 Oct 2026 ("we can
do the same thing for stock prediction as well"; "This is for stock prediction, not for ... future and options"):

- *"It is about consuming data, analyze it, apply the reasoning, intelligence and smartness to find the profitable
  trades. That's how all these different human roles work together."*
- *"It is not one person responsibility. It is a team effort. ... that co common goal for collective team effort is to
  find net profitable future and option trades. So in order to achieve that goal, whether we have to fix the data,
  whether we have to fix the algorithm, whether we have to fix the logic, we have to fix the code, anything that we
  need to do"*
- *"make sure there are different models running different capabilities. One model should not run. all the
  capabilities there should be multiple independent models that should work together ... and there should be one
  additional role which is an independent honest brutal ruthless and transparent role called judge role"*
- *"You have huge amount of data. You can compare and check each and every edge case, every possible situation. ...
  each member or role has high processing power they have all the data available they can find the pattern they can
  recognize them they can find the gaps and see the situations"*
- *"That the design is about a team of experts in different fields are working together. To find the most profitable
  trades. And winning against the odds."*

### 1.2 What the team is for

The team's job is **discovery**: to consume the data, reason about it from every field, and find trades that make
money after all costs. It is not there to audit code, decorate a report, or confirm strategies we already have. Each
field sees what the others miss:
- the results analyst sees a guidance cut;
- the flows analyst sees forced selling;
- the cost accountant sees that the move is too small to pay;
- the risk manager sees that three trades are one bet;
- the red team sees that the "pattern" is luck.

The machine's advantage over a human trader is memory and testing power. Its danger is the same power: testing many
patterns finds lucky ones. So the team works under strict evidence rules (section 8).

### 1.3 Lessons from the F&O history (what went wrong there, and must not repeat here)

| Lesson | What happened in F&O | What it means here |
|---|---|---|
| Building is not discovering | Five review rounds, then a sixth, went mostly into correcting diagnostics (the backtest replay and the capacity screen); no strategy was found; the owner: "you and ChatGPT are not fulfilling the roles" | Since 8 Oct this project has spent nearly all effort on the app, pipeline and pages. The only research was the research director's weekly review (W41) and the 15-year backtest of 10 Oct; there has been **no desk meeting**. The same drift. The first deliverable of this design is research (desk meeting 1), not code |
| Many weak rules agreeing is not evidence | 19 chart rules voting; 4 of 30 coin-toss runs did worse (about the 13th percentile): no positive edge was established, and neither was equality with chance | Our 8 "rule" strategies are one signal model, each changing one parameter (news weight, statuses, materiality, cross-market, regime filter or threshold). The morning Slack post ranks companies by how many of all 15 strategies buy at N+1, so the 8 near-identical rule strategies can supply 8 of those votes. Agreement must count independent sources only |
| Start from the data, not from a strategy | The owner: "not to check existing strategies" | Desk meetings start from questions about the data. The current 15 strategies are one input, not the agenda |
| Controls on every test | Coin toss, always up, always down; all 219 entries in every control | Keep the v16 comparators (cash, simple momentum, model-only) and add the coin-toss distribution for every discovery test |
| Costs decide | Charges and pads decided feasibility | Under v16's India zero-brokerage scenario a flat round trip costs 0.40-0.66% and needs a 0.49-0.83% gross rise to break even after Indian tax (2.9). Every horizon must clear its own hurdle with selected trades; costs call for selectivity, not a ban on N+1 |
| Economic stories are hypotheses | ChatGPT corrected "buyers overpay", "we win only", "desks leave alone" | Every edge family here says what would prove it wrong |
| Unexplained patterns are the most likely luck | Agreed: an unexplained pattern trades only with a stricter bar and minimum size | Stricter bar, but **no** size exception: v16 sizes every trade at account value ÷ 3. An unexplained pattern stays in research until it passes a stricter evidence plan written in the ledger before the test; if it ever registers, it uses v16's size. A different size would be a separate owner decision on a new policy version |
| Historical AI replays are contaminated | A model may know later outcomes | Already a project rule (`model_training_cutoff`); AI value is measured forward only |

## 2. Where we stand today (verified facts, no gloss)

From PLAN_v16 sections 2.4-2.5 and the stored data:

1. **The India signal model is degenerate:** its calibration slope is 0.0 at N+1, N+3, N+4 and N+5, so P(up) is a
   constant of about 0.47.
2. **Direction skill is at coin level:** 1-day open-to-close AUC 0.485 for India and 0.483 for the US. `model_skill` is
   false.
3. **The ranges over-cover:** India's rule-only replay (2 Jan 2025 to 9 Oct 2026) covers 83.6-85.4% of outcomes with its 80% band, and is not better than a naive baseline. No US figure is recorded.
4. **News is a fixed weight per article, not per event.** The "rule" strategies all use AI-scored news, so they are
   not AI-free.
5. **The 15 strategies are not 15 independent ideas:**
   - 8 rule strategies share one model, each differing from its comparator in one parameter (news weight, news
     statuses, news materiality, cross-market features, a regime filter or the threshold);
   - 3 baselines;
   - 4 AI traders reading overlapping inputs.

   On 12 Oct the rule strategies made **no** qualifying India predictions; the 209 qualifying India predictions
   (each a lab paper-trade record, not a funded account position) are 195 baseline and 14 AI-trader ones.
6. **All stored history is development data** (PLAN_v16 2.5). The only clean evidence is forward.
7. **Survivorship bias.** The watchlist is 20 large companies per market chosen in 2026. Any test of them back to
   2011 only includes companies that survived and grew. Results on them may overstate what a strategy would have
   earned.
8. **The universe is small.** 20 companies per market limits any cross-sectional idea (ranking stocks against each
   other) and the number of independent observations.
9. **Costs.** Under the lab's Axis Direct NRI costs, India always-up N+1 averaged -1.98% per trade (market cost) and
   -2.42% (owner's cost) over 15 years (PLAN_v16 2.5). That is an average return under a different broker scenario,
   market drift included, not v16's hurdle. Under v16's zero-brokerage scenario (4.5), a ₹1,00,000 round trip at
   flat prices costs ₹662.48 (0.66%) when one trade carries both ₹200 date charges, or ₹395.81 (0.40%) when three
   trades share them. The gross rise needed to break even after the 20.8% Indian tax (STT, DP and date charges not
   deductible, v16 4.8) is 0.83% or 0.49%. Short horizons need selected trades with a larger expected move; the
   numbers do not rule them out. Which broker applies is open question 12.4.
10. **Independence is weak:**
    - the judge and the forecaster both run on Opus 5.5;
    - the bull and bear researchers read the same context pack;
    - only Claude models are available inside the routines.

## 3. How this design fits the approved plan (PLAN_v16)

**Boundary:**
- **PLAN_v16 decides how money is counted and how evidence is judged:**
  - accounts, sizing, costs and tax;
  - risk rules and the loss brake;
  - the budget ceiling;
  - scoreboards and the registration and evaluation protocol;
  - the freeze guard.
- **This design decides how the team discovers and builds the ideas** that enter v16 as challengers.

Nothing here edits PLAN_v16. A change to a v16 rule would be a separate owner decision.

**The path an idea takes:**
1. Desk meeting.
2. Finding cards.
3. Thesis.
4. Discovery test (development data).
5. Red team.
6. Judge.
7. Owner approval.
8. **Registered challenger under v16** (11.6: at most 3 live challengers per market, a share of the α reserve, its
   own forward window).
9. Forward paper.
10. Promotion only with the owner's approval.

**Freeze guard (v16 8.10):** during a registered window, nothing that feeds a registered policy changes. This applies
to the news analyst, the claim checker, the combined trader, the model, strategies and ranges. A new role that wants
to influence daily decisions enters as a **new challenger version**, never as a quiet change.

## 4. The edge map for stocks

The first question for every idea (agreed in the F&O design): **what service, risk transfer or information advantage
could give positive expected net value; what pays for it; and what evidence would show it is not enough?** A good
story can still fail the data. A pattern without a story stays in research, with a stricter bar.

All families are **untested** for this account unless stated. "Point-in-time history" says whether we hold the data
as it was known at the time, which a fair test needs.

| # | Edge family (hypothesis) | What might pay, and why | Proves it wrong | Owning roles | Point-in-time history |
|---|---|---|---|---|---|
| S1 | Results drift still left at the first legal entry | Prices may keep adjusting to results for days. The account cannot trade the announcement move: v16 blocks new entries from the day before results until the day after, so the first legal entry is usually the open of E+2 (E = results day; 11) | Entry-known release characteristics or completed price and volume reactions add no executable net value at N+1/N+3/N+5 from the first legal entry, after costs, against matched controls | Equity research, results analyst, statistician | Results dates only from 11 Oct 2023 (India) and 12 Oct 2023 (US) (DC-12 (3)): an inventory of 242 / 241 releases, not testable trades. Stored daily prices start on 7 Oct 2024, so about 161 / 160 have entry and exit bars (11). US dates and times are SEC filing acceptance, India's an NSE announcement or filing stamp: a filing-time proxy for the first public release unless checked against dated primary evidence. Consensus only from 7 Oct 2026, so history uses labelled proxies (the reaction, reported numbers), never "consensus surprise" |
| S2 | Verified news reaction | Slow absorption of confirmed news; overreaction to rumours. Verification is a reliability input, not a profit signal by itself | Using verification status adds no forecast or net decision value (money kept after costs) on the same opportunities, given direction, materiality and timing | News analyst, claim checker, behavioural finance | Only from when news collection began (first seen 5 Oct 2026); **no history**, so forward only |
| S3 | Forced and slow flows | Funds that must buy or sell (index changes, FII/DII flows, block deals) move prices for non-value reasons | No excess move after costs around the flow | Flows analyst, microstructure | India FII/DII, FPI, deals, delivery %: collected history limited. US 13F shows quarter-end holdings filed up to 45 days later: context only until its publication-timed value is shown; short interest |
| S4 | Insider and promoter signals | Insiders know their company; a pledge rise signals stress | No excess return after costs following cluster buys or pledge rises | Corporate-actions analyst | SEBI PIT and Form 4 as collected; check depth |
| S5 | Momentum and reversal | Trend-following and overreaction by others | The simple momentum comparator already covers the plain version; anything more must beat it | Technical analyst, quant modeller | Prices from 2011 (development data, survivorship-biased) |
| S6 | Sector and market context | Sector rotation and global cues move groups together | Cross-market features already showed no tradable skill in the 15-year test (DESIGN.md 15.1) | Sector analyst, macro economist | Prices, indices, FX, rates from 2011 |
| S7 | Scheduled corporate events | Dividends, splits, buybacks, index inclusion on known dates | No excess total economic outcome after costs around the event, counted with DC-12 (1)-(2): an ex-date drop plus the dividend receivable, a split on the as-traded share count (stored prices are not dividend-adjusted) | Corporate-actions analyst, regulation | Events and adjustments as collected |
| S8 | Cost and no-trade discipline | Not an edge alone: few trades, held longer, beat the cost drag that sinks frequent trading | — | Cost accountant, portfolio manager | Measured per trade |
| S9 | Cross-company information transmission (ChatGPT review 1) | A verified event at one company (results, guidance, a supplier or customer shock) may change expectations for a related company before it fully reprices. The results blackout blocks only the reporting company: a peer that has not reported yet and is outside its own blackout can be traded at its next pre-open decision | No net value after costs against own-momentum and sector controls, in either direction (published work finds peer news can be overreacted to and reverse); or the effect is plain common sector movement | Sector analyst, equity research, statistician | Results dates from Oct 2023 (prices from Oct 2024, as S1); pairs predeclared from the current watchlist's sectors, a coarse proxy for business overlap (survivorship and mapping caveat stated). The connection map has no point-in-time history, so map-based pairs start forward |
| S10 | Price-pressure recovery (ChatGPT review 2) | A stock sold off with broad market or sector selling, with no verified adverse company news, may recover once the selling stops: liquidity providers are paid for absorbing it | No net value after costs against ordinary short-term reversal and simple momentum, counting every scan; or real company deterioration drives the fall | Flows analyst, technical analyst, statistician | Prices allow a price-only development study; "no adverse company news" needs the news archive, so that filter starts forward (news from 5 Oct 2026) |

**Out of scope at first** (a scope choice for our data, schedule and costs, not proof that no edge exists):
- intraday trading;
- short selling and leverage;
- stocks outside the market's liquid large companies.

A down forecast is never permission to short: the account only buys or stays out.

## 5. The team

### 5.1 Roles

Every role works for the same goal. "Runs as": **code** (deterministic, daily or on demand) or **AI** (a model).
"When":
- **research** = the weekly or monthly desk meeting;
- **daily** = inside a registered daily policy, frozen during its window.

| Role | Field and edge families | Runs as | When | Today |
|---|---|---|---|---|
| Head of desk | Sets the question, makes every role contribute, records decisions | AI | research | research-director (extended) |
| Portfolio manager | Who pays, ranking theses against no trade, allocation | AI for research; code for allocation (v16 9.3) | both | allocation exists in v16 design |
| Equity research analyst | S1: results against expectations, guidance | AI | research; daily only if registered | results-analyst (extended) |
| Technical / price-pattern analyst | S5 | Code measures + AI interprets | research | trader-pattern-mood (as a role) |
| Sector analyst | S6: sector moves, relative strength | Code + AI | research | new |
| Macro economist | S6: RBI/Fed, rates, FX, crude, global cues | AI | research | new (data exists) |
| Flows / positioning analyst | S3: FII/DII, FPI, deals, delivery %, short interest, 13F | Code + AI | research | new (data exists) |
| Corporate-actions analyst | S4, S7: insider and promoter trades, pledges, corporate actions | AI | research | new (data exists) |
| News analyst | S2: scores every new item | AI | daily (frozen) | news-analyst |
| Claim checker | S2: verifies claims against primary sources | AI | daily (frozen) | claim-checker |
| Behavioural finance | S2, S5; our own biases (chasing, overtrading) | AI | research | new |
| Statistician / quant researcher | Sample, controls, multiple testing, survivorship | Code + AI | research | partly (lab luck test, Bonferroni) |
| Quantitative modeller | Forecasts tested out of sample | Code | both | signal model, ranges |
| Mathematician | Expected value per trade after cost, break-even move | Code | both | partly (`lab/gain.py`) |
| Execution | Limit fills, open and closing-auction exits, gaps | Code | both | v16 4.3-4.4 design |
| Tax and cost accountant | Net at the owner's cost and tax | Code | both | `lab/costs.py`, v16 4.5 and 4.8 |
| Risk manager | Limits, correlation, stress tests, loss brake | Code | both | v16 4.9 rules; stress tests new |
| Data and backtesting engineer | Availability times, no look-ahead, survivorship | Code | both | `validate.py` gates, as-of reads |
| Regulation | SEBI/NSE and SEC rules, results windows, circuit limits | AI | research | new |
| Bull and bear researchers | The strongest case each way | AI | daily (feed the Opus forecaster; not a frozen input of any v16 policy) | existing |
| Red team | Breaks every thesis before it is registered | AI, a different model from the author | research | new |
| Judge | Hard validity (code); sufficiency and interpretation (AI) | Code + AI, a different model from the author | both | judge (build work); `validate.py` |

Roles with nothing to say report "not applicable". No role invents numbers to fill a meeting.

### 5.2 Independence (the owner's "different models" requirement)

- **Independent first:** in a desk meeting each AI role writes its finding cards **in a separate model call, before
  seeing any other role's cards**.
- **Different models where it matters:**
  - the red team and the judge never use the author's model: Sonnet-authored role cards are checked by Opus,
    Opus-authored theses (the head of desk's) by Sonnet; this rule overrides any model named in section 10;
  - today the judge and the forecaster are both Opus 5.5; that must change for desk decisions.
- **Honest limit:** inside the routines only Claude models are available, so the strongest independence there is a
  different Claude model. **ChatGPT is the genuinely independent reviewer** at design and research level, as in the
  F&O desk: every desk meeting's minutes and every thesis go to `reviews/` for it to attack.
- **Shared input is not shared evidence:** two roles citing the same data point count it once.

### 5.3 Finding cards

Each card holds:
- the observation (data, source, when it was known);
- the interpretation;
- the measurable implication (direction, horizon N+k, size of the move);
- confidence (strong / some / reasoning only);
- counter-evidence;
- what would prove it wrong.

A role may report "not applicable". Numbers come only from stored data or the context pack.

### 5.4 How an idea becomes a thesis: no single role can make one

| Part | Question | Owner |
|---|---|---|
| Payer | What service, risk transfer or information advantage pays, and why will it persist? | Portfolio manager, behavioural finance |
| Signal | What entry-known sign says it is present? | Statistician, quant modeller, the field's analyst |
| Context | Which results, events, flows or macro news in the holding window change it? | Equity, macro, flows, corporate actions, regulation |
| Price | Is the decision value (the opportunity record below) positive after the owner's cost at that horizon, with the fills we can get? | Mathematician, execution, cost accountant |
| Survival | Worst case; correlation with open positions; v16 limits | Risk manager |
| Attack | Luck, a flattering period, survivorship, the disaster case | Red team |

**The opportunity record (ChatGPT review 1, section 4).** "High chance of up" is not "worth buying": a 70% chance of
+1% and a 30% chance of −4% is −0.5% before costs. v16 2.3 already marks `lab/gain.py`'s score as a heuristic (it
mixes P(exit close > entry open) with moves measured from the previous close), and v16 11.1 builds the coherent
order value. Every opportunity a thesis acts on carries one record:

| Part | What it states |
|---|---|
| Information | Input snapshot, each source's availability time, the event definition, the policy and model versions |
| Forecast | For N+1/N+3/N+5: the expected exit close (or a stated centre), intervals, the direction probability with its exact event, the uncertainty and the sample behind it |
| Tradable action | Buy limit, v16 size, planned and fallback exit, or no new trade. A down forecast is never permission to short |
| Decision value | The payoff of that order under the same entry, fills, exit, currency and costs, with fill and return kept together (never the average return times a fill probability); "unknown" when the data cannot support it, and an unknown value cannot justify a buy |
| Account choice | The alternatives, always including no trade (value 0: the incremental value against staying in cash; v16's cash interest, fees and tax stay in the funded ledger), free cash, slots, sector cap, blackout, brake, and the reason for the choice or the abstention |
| Evaluation | Forecast quality against simple baselines, calibration of the order value, and the account's money kept after all costs and declared taxes |

- Horizons are v16's: a decision before Monday's open buys on Monday (D); N+1 sells at Tuesday's close, N+3 at
  Thursday's, N+5 at the next Monday's (normal sessions). A next-close Monday return is never labelled N+1.
- A US forecast of the official close is not the euro payoff of the exit 15 minutes before the close; a limit fill
  selects a different sample from all forecasts. Both are kept apart.
- A rule that only supplies an action states which parts it supplies and which are unmeasured; nothing is
  manufactured. A simple conditional empirical profit-and-loss distribution is enough at first. The frozen
  incumbent's heuristic is never labelled expected profit.

### 5.5 The desk meeting

1. **Question** (head of desk): one question, from the data. Example (meeting 1, section 11): "After a results
   release, at the first V16-permitted pre-open decision with the required information available, do entry-known
   release characteristics or completed price/volume reactions predict additional executable net benefit at
   N+1/N+3/N+5?"
2. **Independent findings:** each role's cards, written before seeing the others.
3. **Cross-examination:** each role tests the material assumptions of other fields. Agreement after checking is
   allowed; there are no objection quotas.
4. **Thesis assembly** (portfolio manager), with disagreements recorded.
5. **Settle disagreements with data:** the disputing roles fix a test and its pass/fail before it runs.
6. **Red team, then judge.**
7. **Decisions:** test, register as a challenger, drop (with the reason), or the next question. Minutes go to
   `research/<date>-desk-meeting-<n>/` and to ChatGPT.

## 6. Scorecards: each role must earn its place

The two types agreed in the F&O design, mapped onto v16:

- **Optional judgement roles** (macro, sector, flows, news, behavioural, bull/bear, AI traders):
  - scored by paired comparison on the same dated opportunities, with and without the role, as the difference in
    account net result after the role's own running cost;
  - abstentions count, and each role is judged only where it applies.

  v16 already contains such pairs: `acct.ai.v1` against `acct.noai.v1` measures the whole AI pipeline (news
  scoring, claim checking and the Sonnet trader; H3); `acct.ai.v1` against the exploratory `acct.news.v1` isolates
  the trader. New roles
  are measured the same way, as challengers.
- **Mandatory control roles** (data, risk, cost, the judge's hard checks): scored on correctness and caught violations.
  They are never removed because no disaster happened lately.

**Promotion and attribution are different questions (ChatGPT review 1, section 7):**
1. **Promotion** ("is this policy better?"): v16's comparator and protocol, unchanged. A challenger that beats the
   incumbent proves the challenger, not any one role inside it, when it also changes a model, threshold or universe.
2. **Attribution** ("is this role worth its cost?"): a paired role-on / role-off comparison with everything else fixed
   (inputs, wrappers, opportunities, cost conventions), abstentions and failures included, interactions recorded,
   and overlapping credits never summed as independent gains.
   - **Shared budget:** a role's calls can push other components into a lower budget tier (v16 5.3). The comparison
     states whether it ran under the common realised budget or simulated the budget without the role.
   - **Agreed with ChatGPT (review 2):** attribution runs as an exploratory **shadow** pair inside the same account
     engine: not registered, no confirmation α, never used for promotion or a significance claim. Registered pairs for
     every role would use v16 11.6's 3 challenger slots per market for years, and AI roles can only be paired forward
     (contaminated history). Every shadow comparison is still counted in the ledger (versions, pairs, outcomes); its
     extra calls are charged to the system budget, research cost kept apart from counterfactual deployment cost, and a
     budget-tier change is reported. A shadow never alters a decision-producing policy's output; a favourable one only
     suggests a candidate, and adding or removing a role from registered inputs needs a later frozen policy version.
   - A role without an attribution result is "unattributed": neither credited nor removed on profit grounds.

## 7. Two loops

- **Research loop (weekly desk meeting; monthly deeper review):** edge map → meeting → thesis → discovery test →
  red team → judge → owner → registered challenger. The Friday research run becomes the head of desk's meeting.
- **Daily loop (the existing pre-open run):** runs the v16 baseline and the registered challengers exactly as frozen:
  - data gates;
  - decisions;
  - paper trades;
  - intraday checks;
  - post-close settlement and reasons.

  AI roles take part daily only as frozen parts of a registered policy.
- **Fixed policy, dynamic decisions:** a strategy is never invented and traded the same day. v16 11.5 (step 6,
  deferred): combination weights may be learned, shrunk toward equal weights and tested against the frozen
  equal-weight policy; no automatic adaptation of decision rules in the first phase. The update rules registered
  with a policy (the monthly model refit, the pick's strongest-strategy ranking, `model_news_update` if applied;
  v16 8.10) keep running. Any other change is a new version.

## 8. Evidence rules

1. **Idea ledger** (`research/LEDGER.md`): every idea, threshold and variant is written down **before** its result
   is read. Failures included. The ledger's count sets the bar.
2. **Discovery engine** (code; owned by the statistician and the data engineer):
   - a feature library where every feature has an availability time;
   - a candidate generator over features × actions (buy at N+k, no trade);
   - a scan after the owner's costs;
   - a mechanism filter (roles explain the survivors);
   - a bar that rises with the number of candidates (the lab's luck test and Bonferroni correction, extended to the
     whole ledger);
   - the coin-toss distribution for every test.

   Example of the danger: among 1,000 random rules on 33 independent fair-coin tries, about 18 win 23 or more
   (69.7%) by luck alone.
3. **No untouched history is left:** all stored history is development data (PLAN_v16 2.5). The honest options:
   - **Forward paper** (the clean test; slow).
   - **A cross-sectional challenge:** liquid companies **outside** today's watchlist, history fetched for research
     only. They have not been looked at, so they can challenge a thesis found on the watchlist (transportability).
     - **Frozen first:** eligibility, the ticker list, exclusions, the fetch window, event and label definitions,
       feature and policy versions and the test are written to a manifest (in the ledger) **before** any outcome is
       read. Every eligible case and every missing one is reported.
     - **Not independent confirmation:** the new names share dates, shocks and sector news with the watchlist.
       Inference is grouped by date or event (one results season is one shock, not 20 observations).
     - Survivorship applies to them too: today's liquid companies also survived. Free sources rarely include delisted
       names; the gap is stated, not hidden. Picking only today's winners is not allowed.
     - AI roles scoring these companies may know their later outcomes (`model_training_cutoff`); deterministic tests
       are contaminated by our own development choices instead, which the manifest guards against.
     - Forward registered confirmation is still needed.
   - **Never** call development data out-of-sample, and never tune on a challenge set.
4. **Survivorship and the small universe** are stated in every result.
5. **Agreement counts independent sources only.** Strategies that share a model or inputs count as one vote. The
   Slack morning ranking (by how many of all 15 strategies buy at N+1) is relabelled or changed to count independent families (a fix proposed to
   the owner; it touches B6's alert, not a registered policy).
6. **Pass/fail is fixed before a test runs;** availability times are respected; AI replays before the training
   cutoff are exploratory.
7. **Confirmation is v16's protocol unchanged:** registration, power analysis, α share, fixed window, harm stop and
   bounded wording.

## 9. Risk and money

**v16 rules govern, unchanged:**
- ₹3 lakh India and $3,000 US;
- size = account value ÷ 3;
- at most 3 positions and 2 per sector;
- results blackout;
- a 10% loss brake that pauses new entries only; the rehearsal account (the one the owner follows) restarts only with
  the owner's approval, while the policy accounts assume a restart after 5 sessions (v16 4.9);
- every trade carries every real cost from day one.

**What the risk manager adds** (code; **diagnostics only** until a policy version adopts them. A veto, correlation
cap, eligibility rule, event filter or earlier exit applied to trades is a decision-policy change: during a
registered window it belongs to a later challenger, never an informal intervention):
- **One bet, not three:** positions driven by the same factor count as one bet:
  - the same sector;
  - all following the index;
  - the same event day.
- **Stress tests of the account:**
  - the index −5% and −8% overnight;
  - a sector shock;
  - a results gap on a held name;
  - replays of known shock days (Mar 2020, Jun 2024 India election day).

  Full repricing of the positions, shown as stress results, not as worst cases.

The current per-prediction lab paper-trade records (209 India and 182 US qualifying predictions on 12 Oct; each
prediction its own record, not a funded position) stay as the **measurement** of strategies. The
**account** view (v16 9.3) is the one that answers "what would I have made".

## 10. Running cost (the owner's ceiling: $250/month for the whole system)

- **Numeric roles are code:** no model cost.
- **New AI roles run only in the research loop** (weekly), not daily:
  - one meeting is about 10 role calls on Sonnet plus one Opus call for the head of desk; the red team and the judge
    run on a model other than the author's (5.2), so an Opus thesis is checked on Sonnet and by ChatGPT;
  - each meeting's cost is measured by v16's operating-cost tracker (5.1).
- **A daily AI role is added only as a registered challenger,** and v16's budget tiers (5.3) apply to it.
- **Each optional AI role must show net value after its own cost** (section 6), or it goes back to research-only or is
  dropped.

## 11. Build order (after approval)

1. **Desk meeting 1, by hand, on stored data. No code change; research output only.**
   - Question (ChatGPT review 1, adopted word for word): "After a results release, at the first V16-permitted
     pre-open decision with the required information available, do entry-known release characteristics or completed
     price/volume reactions predict additional executable net benefit at N+1/N+3/N+5?"
   - **The first legal entry:** v16 4.9 blocks new entries from the day before results until the day after, so for
     results on day E the first entry is usually the open of E+2. The current prediction gate blocks entry sessions D
     with `days_to_earnings` = E − D <= 1 calendar day: E and the calendar day before, not E+1, and not a Friday entry
     before Monday results. The study reports both entry rules and does not decide v16's rule.
     The move before the first legal entry is shown apart from the tradable rest.
   - **Proxies, labelled:** consensus exists only from 7 Oct 2026, so history uses the completed reaction (return and
     volume from E to the entry) and reported numbers; never called a consensus surprise.
   - **Rules:** v16 fills, exits and costs; DC-12 dividends and as-traded basis; days without a known results calendar
     reported, never treated as "no blackout".
   - **Controls:** cash, v16's simple momentum policy, the incumbent where relevant, and the coin-toss distribution;
     matched dates, companies and market or sector conditions. Raw returns explained by plain market exposure are not
     an edge.
   - **Also S9:** the read-through to a peer that has not reported yet and is outside its own blackout, on the same
     events, reported separately. Pair mapping, signal sign (continuation and reversal), horizons and eligibility
     are fixed in the ledger before returns are read. The leader's news must be public before the pre-open cut-off;
     a gap already priced into the peer's open is shown apart. Peers whose own results fall inside the 1-5-session
     holding window are reported apart (v16 forbids the entry, not the holding). One leader event shared by several
     peers is related evidence, and S1 and S9 successes on the same event are never summed as independent gains.
   - **Coverage first (amendment A):** before any inference, a table of events, entry and exit price bars, labels and
     availability times per market. The stored `bars` start on 7 Oct 2024: of the 242 India and 241 US releases,
     about 161 and 160 have the entry and exit bars. The study either rebuilds and freezes the long-history cache
     (`model_history.py`, Yahoo, paced; a dated copy with its manifest's SHA-256, DC-12 (7); Yahoo's bars are
     split-adjusted as of the fetch, so DC-12 (2)'s as-traded rebuild applies) or keeps to the covered period, and says which. Timing counts are reported for the cleaned sample
     (`earnings_events`), not the raw rows. The release time is a filing-time proxy unless checked against dated
     primary evidence: a sample is checked, unknowns stay visible, and a later 10-Q/10-K's classification is never
     used as an entry-known feature.
   - **Precision, an estimate (amendment B):** at an assumed 5-percentage-point standard deviation and 240
     independent usable events, the standard error is 0.323 points (0.394 at 161). Actual power is unknown until
     the usable sample, the selected-event distribution, the paired differences and the dependence within results
     seasons are measured. Meeting 1 reports estimates, uncertainty, counts and sensitivity; an imprecise result is
     inconclusive, and a null result with wide intervals does not disprove an edge. Nothing is registered from this
     study alone. The 0.49-0.83% break-even is India's v16 scenario illustration, not a universal or US hurdle.
     Where v16's account engine is not built yet, account net performance is "not computed".
   - It lists every missing input and what it would change (older results dates under DC-12 (3), prices, release
     times, corporate actions, information snapshots) before any collection is commissioned as a later batch.
   - Survivorship stated; all of it is development evidence. Minutes to `research/` and to ChatGPT.

   This is what the owner asked for and what has not happened yet.
2. **Research tooling (code, research only):**
   - the idea ledger;
   - the feature library with availability times;
   - the discovery engine;
   - the coin-toss and comparator harness;
   - the out-of-watchlist history fetch, with Yahoo pacing, after its manifest is frozen (8.3);
   - the results-date backfill (DC-12 (3)), if meeting 1 shows it is worth it.
3. **Team mechanics in the research loop:**
   - finding cards;
   - independent role calls;
   - the red team on a different model;
   - the judge's three checks for theses;
   - the head of desk.
4. **New AI roles, one at a time,** each measured on its scorecard.
5. **The first registered challenger under v16,** from a thesis that passed. The owner approves. No challenger can
   register until v16 steps 1-3 are built and the step-3 report is reviewed (PLAN_v16 section 11).

Each step is one batch under CLAUDE.md's delivery strategy: one builder, one judge review.

## 12. Open questions for the owner

1. Start with desk meeting 1 on results reaction (S1)? Or another family?
2. Fetch history for liquid companies outside the watchlist for research only (section 8.3)? It costs collection time,
   not money.
3. Change the Slack "top 5 by agreement" to count independent strategy families only (section 8.5)?
4. **India broker costs:** PLAN_v16 assumes a zero-brokerage delivery broker "not yet named", while the lab's costs are
   Axis Direct NRI. Which applies changes which horizons can ever pay.

## 13. Open questions for ChatGPT

Reviews 1 and 2 answered the questions of versions 2 and 3. The open ones are in
[response 3](../reviews/claude/response_3_2026-10-12-stock-desk-design.md), section 3:
1. Do amendments A and B, as written in sections 4 and 11, close your remaining changes?
2. Do you accept rebuilding and freezing the long-history cache with the existing `model_history.py` as meeting 1's
   way past the price-coverage limit, with the limits stated in response 3?

## 14. Closing the design

| Section | Claude | ChatGPT | Owner |
|---|---|---|---|
| 1 Why a team | Agreed; v3 removes the size exception (response 2, 2.1) | Agreed | |
| 2 Where we stand | Agreed; v3 corrects the cost hurdle and the "trades" wording (2.7) | Agreed | |
| 3 Fit with PLAN_v16 | Agreed | Agreed | |
| 4 Edge map | Agreed; v4 applies amendment A and adds S10 (response 3) | Changes required: amendment A — usable event coverage and release/filing anchors (review 2) | |
| 5 The team | Agreed; v3 adds the opportunity record and the model rule (2.3, 2.8) | Agreed | |
| 6 Scorecards | Agreed; v4 adds review 2's bounds on shadow attribution (response 3) | Agreed | |
| 7 Two loops | Agreed | Agreed | |
| 8 Evidence rules | Agreed; v3 freezes the cohort first (2.5) | Agreed | |
| 9 Risk and money | Agreed; v3 marks the additions diagnostic (2.8) | Agreed | |
| 10 Running cost | Agreed; v3 follows 5.2 for models (2.8) | Agreed | |
| 11 Build order | Agreed; v4 applies amendments A and B and the S9 conditions (response 3) | Changes required: amendments A/B — joined data coverage and assumption-based power (review 2) | |

The design is final when both AIs mark every section "agreed" (or the owner settles a disagreement) and the owner
approves. No build starts before that.
