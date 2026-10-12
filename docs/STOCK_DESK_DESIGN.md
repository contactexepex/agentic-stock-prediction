# Stock desk design: a team of experts finding net profitable stock trades

**Version 2 draft (12 Oct 2026), for the owner and ChatGPT to review. Design only.** Nothing is built, run or
changed until both AIs agree every section and the owner approves (section 14).

**Sources read for this version, in full:**
- the F&O project `exepex/trading`:
  - the owner conversation of 12 Oct 2026 (`conversations/2026-10-12.md`);
  - ChatGPT reviews 1-11 and Claude responses 1-12 (`reviews/`);
  - `docs/DESK_DESIGN.md` v2.1 (approved as a framework), `docs/DESK_DECISIONS.md`, `AGENTS.md`;
  - the backtest analysis and strategy proposal (`reports/`), desk meeting 1 and the ledger (`research/`);
- this project's approved accounts and evaluation design, `docs/PLAN_v16.md`, and `CLAUDE.md`.

## 0. What changed from version 1, and why

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
   Version 2 states the cost of each role and when it runs (section 10).
4. **It stated hypotheses as facts.** For example, it said investors under-react to results. ChatGPT corrected the
   same error in the F&O design (reviews 1 and 10). In version 2 every edge is a hypothesis with a "what would prove
   it wrong".
5. **It missed the facts about where we stand** (section 2): a degenerate India model, coin-level skill, near-duplicate
   rule strategies, survivorship bias, and cost drag that kills short holds in India.
6. **It did not record the process lesson that led to the team design.** The F&O work drifted into auditing code
   instead of finding trades, until the owner stopped it. This project is drifting the same way (section 1.3).

## 1. Why a team of experts

### 1.1 The owner's reasons, in the owner's words

From the F&O conversation of 12 Oct 2026, which applies to this project too ("same thing for stock prediction"):

- *"It is about consuming data, analyze it, apply the reasoning, intelligence and smartness to find the profitable
  trades. That's how all these different human roles work together."*
- *"It is not one person responsibility. It is a team effort ... the common goal ... is to find net profitable ...
  trades. ... whether we have to fix the data, the algorithm, the logic, the code, anything that we need to do."*
- *"Make sure there are different models running different capabilities. One model should not run all the
  capabilities ... and there should be one additional role ... called judge."*
- *"You have huge amount of data. You can compare and check each and every edge case ... each member or role has high
  processing power ... they can find the pattern, recognize them, find the gaps."*
- *"The design is about a team of experts in different fields working together, to find the most profitable trades
  and winning against the odds."*

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
| Building is not discovering | 6 review rounds went into making one diagnostic correct; no strategy was found; the owner: "you and ChatGPT are not fulfilling the roles" | Since 8 Oct this project has spent nearly all effort on the app, pipeline and pages, and **no desk research at all**. The same drift. The first deliverable of this design is research (desk meeting 1), not code |
| Many weak rules agreeing is not evidence | 19 chart rules voting; they did no better than a coin toss (about the 10th percentile of 30 random runs) | Our 8 "rule" strategies are one signal model with different news weights, and the morning Slack post ranks companies **by agreement** among them. Their agreement counts the same opinion up to 8 times. Agreement must count independent sources only |
| Start from the data, not from a strategy | The owner: "not to check existing strategies" | Desk meetings start from questions about the data. The current 15 strategies are one input, not the agenda |
| Controls on every test | Coin toss, always up, always down; all 219 entries in every control | Keep the v16 comparators (cash, simple momentum, model-only) and add the coin-toss distribution for every discovery test |
| Costs decide | Charges and pads decided feasibility | India at the old broker: always-up N+1 lost **−1.98% per trade** before tax (PLAN_v16 2.5). Short holds in India start deep under water |
| Economic stories are hypotheses | ChatGPT corrected "buyers overpay", "we win only", "desks leave alone" | Every edge family here says what would prove it wrong |
| Unexplained patterns are the most likely luck | Agreed: an unexplained pattern trades only with a stricter bar and minimum size | Same rule (section 8) |
| Historical AI replays are contaminated | A model may know later outcomes | Already a project rule (`model_training_cutoff`); AI value is measured forward only |

## 2. Where we stand today (verified facts, no gloss)

From PLAN_v16 sections 2.4-2.5 and the stored data:

1. **The India signal model is degenerate:** its calibration slope is 0.0 at N+1, N+3, N+4 and N+5, so P(up) is a
   constant of about 0.47.
2. **Direction skill is at coin level:** 1-day open-to-close AUC 0.485 for India and 0.483 for the US. `model_skill` is
   false.
3. **The ranges over-cover** their 80% band (84-85%) and are not better than a naive baseline.
4. **News is a fixed weight per article, not per event.** The "rule" strategies all use AI-scored news, so they are
   not AI-free.
5. **The 15 strategies are not 15 independent ideas:**
   - 8 rule strategies share one model, each differing from its comparator in one parameter (news weight, news
     statuses, news materiality, cross-market features, a regime filter or the threshold);
   - 3 baselines;
   - 4 AI traders reading overlapping inputs.

   On 12 Oct the rule strategies opened **no** India trades; the 209 India trades are 195 simple-benchmark and
   14 AI-trader trades.
6. **All stored history is development data** (PLAN_v16 2.5). The only clean evidence is forward.
7. **Survivorship bias.** The watchlist is 20 large companies per market chosen in 2026. Any test of them back to
   2011 only includes companies that survived and grew. Results on them overstate what a strategy would have
   earned.
8. **The universe is small.** 20 companies per market limits any cross-sectional idea (ranking stocks against each
   other) and the number of independent observations.
9. **Costs.** At the owner's India costs, a trade must move several tenths of a percent before it breaks even. N+1 in
   India is the hardest case.
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
| S1 | Results reaction and drift | Prices may adjust to a real surprise over days, not minutes | No drift after costs at N+3/N+5 in held-out results events | Equity research, results analyst, statistician | US: SEC 8-K 2.02 and XBRL, consensus EPS only from when we began storing it. India: NSE results filings; no consensus history |
| S2 | Verified news reaction | Slow absorption of confirmed news; overreaction to rumours | Verified-news moves no larger, after costs, than unverified ones | News analyst, claim checker, behavioural finance | Only from when news collection began (Oct 2026); **no history**, so forward only |
| S3 | Forced and slow flows | Funds that must buy or sell (index changes, FII/DII flows, block deals) move prices for non-value reasons | No excess move after costs around the flow | Flows analyst, microstructure | India FII/DII, FPI, deals, delivery %: collected history limited; US 13F quarterly, short interest |
| S4 | Insider and promoter signals | Insiders know their company; a pledge rise signals stress | No excess return after costs following cluster buys or pledge rises | Corporate-actions analyst | SEBI PIT and Form 4 as collected; check depth |
| S5 | Momentum and reversal | Trend-following and overreaction by others | The simple momentum comparator already covers the plain version; anything more must beat it | Technical analyst, quant modeller | Prices from 2011 (development data, survivorship-biased) |
| S6 | Sector and market context | Sector rotation and global cues move groups together | Cross-market features already showed no tradable skill in the 15-year test (DESIGN.md 15.1) | Sector analyst, macro economist | Prices, indices, FX, rates from 2011 |
| S7 | Scheduled corporate events | Dividends, splits, buybacks, index inclusion on known dates | No excess move after costs around the event | Corporate-actions analyst, regulation | Events and adjustments as collected |
| S8 | Cost and no-trade discipline | Not an edge alone: few trades, held longer, beat the cost drag that sinks frequent trading | — | Cost accountant, portfolio manager | Measured per trade |

**Out of scope at first** (a scope choice for our data, schedule and costs, not proof that no edge exists):
- intraday trading;
- short selling and leverage;
- stocks outside the market's liquid large companies.

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
| Bull and bear researchers | The strongest case each way | AI | daily (frozen) | existing |
| Red team | Breaks every thesis before it is registered | AI, a different model from the author | research | new |
| Judge | Hard validity (code); sufficiency and interpretation (AI) | Code + AI, a different model from the author | both | judge (build work); `validate.py` |

Roles with nothing to say report "not applicable". No role invents numbers to fill a meeting.

### 5.2 Independence (the owner's "different models" requirement)

- **Independent first:** in a desk meeting each AI role writes its finding cards **in a separate model call, before
  seeing any other role's cards**.
- **Different models where it matters:**
  - the red team and the judge never use the author's model;
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
| Price | Is the expected move larger than the owner's cost at that horizon, and can we get the fills? | Mathematician, execution, cost accountant |
| Survival | Worst case; correlation with open positions; v16 limits | Risk manager |
| Attack | Luck, a flattering period, survivorship, the disaster case | Red team |

### 5.5 The desk meeting

1. **Question** (head of desk): one question, from the data. Example: "After a results release with a large verified
   surprise, does the stock keep moving over the next 3-5 sessions by more than the owner's cost?"
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

  v16 already contains one such pair: `acct.ai.v1` (with the AI trader) against `acct.noai.v1` (without). New roles
  are measured the same way, as challengers.
- **Mandatory control roles** (data, risk, cost, the judge's hard checks): scored on correctness and caught violations.
  They are never removed because no disaster happened lately.

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
- **Fixed policy, dynamic decisions:** a strategy is never invented and traded the same day. Adaptation is allowed
  only when its method is fixed and tested in time order (v16 11.5).

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

   Example of the danger: among 1,000 random rules on 33 tries, about 18 win 23 or more (69.7%) by luck alone.
3. **No untouched history is left:** all stored history is development data (PLAN_v16 2.5). The honest options:
   - **Forward paper** (the clean test; slow).
   - **A new cross-section never used:** liquid companies **outside** today's watchlist, history fetched for research
     only. They have not been looked at, so they can challenge a thesis found on the watchlist.
     - Survivorship applies to them too: today's liquid companies also survived.
     - Free sources rarely include delisted names; the gap is stated, not hidden.
   - **Never** call development data out-of-sample, and never tune on a challenge set.
4. **Survivorship and the small universe** are stated in every result.
5. **Agreement counts independent sources only.** Strategies that share a model or inputs count as one vote. The
   Slack morning ranking "by agreement" is relabelled or changed to count independent families (a fix proposed to
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
- a 10% loss brake that pauses new entries only, with the owner restarting;
- every trade carries every real cost from day one.

**What the risk manager adds** (code, proposals to calibrate in research before they govern anything):
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

The current 209 paper trades per market (each prediction its own trade) stay as the **measurement** of strategies. The
**account** view (v16 9.3) is the one that answers "what would I have made".

## 10. Running cost (the owner's ceiling: $250/month for the whole system)

- **Numeric roles are code:** no model cost.
- **New AI roles run only in the research loop** (weekly), not daily:
  - one meeting is about 10 role calls on Sonnet plus Opus for the head of desk, red team and judge;
  - each meeting's cost is measured by v16's operating-cost tracker (5.1).
- **A daily AI role is added only as a registered challenger,** and v16's budget tiers (5.3) apply to it.
- **Each optional AI role must show net value after its own cost** (section 6), or it goes back to research-only or is
  dropped.

## 11. Build order (after approval)

1. **Desk meeting 1, by hand, on stored data. No code change; research output only.**
   - Question: results reaction (S1) on the watchlist, with controls, costs and the survivorship caveat.
   - Minutes to `research/` and to ChatGPT.

   This is what the owner asked for and what has not happened yet.
2. **Research tooling (code, research only):**
   - the idea ledger;
   - the feature library with availability times;
   - the discovery engine;
   - the coin-toss and comparator harness;
   - the out-of-watchlist history fetch, with Yahoo pacing.
3. **Team mechanics in the research loop:**
   - finding cards;
   - independent role calls;
   - the red team on a different model;
   - the judge's three checks for theses;
   - the head of desk.
4. **New AI roles, one at a time,** each measured on its scorecard.
5. **The first registered challenger under v16,** from a thesis that passed. The owner approves.

Each step is one batch under CLAUDE.md's delivery strategy: one builder, one judge review.

## 12. Open questions for the owner

1. Start with desk meeting 1 on results reaction (S1)? Or another family?
2. Fetch history for liquid companies outside the watchlist for research only (section 8.3)? It costs collection time,
   not money.
3. Change the Slack "top 5 by agreement" to count independent strategy families only (section 8.5)?
4. **India broker costs:** PLAN_v16 assumes a zero-brokerage delivery broker "not yet named", while the lab's costs are
   Axis Direct NRI. Which applies changes which horizons can ever pay.

## 13. Open questions for ChatGPT

1. Is the edge map right for 20-stock, 1-5-session, cash-only accounts at these costs? Which family would you drop or
   add?
2. Is the out-of-watchlist cross-section an acceptable challenge set, given survivorship?
3. Is the boundary with PLAN_v16 (section 3) clean, and does anything here conflict with v16?
4. Are the roles right for stocks? Is any role decorative, and is any missing?

## 14. Closing the design

| Section | Claude | ChatGPT | Owner |
|---|---|---|---|
| 1 Why a team | Proposed | | |
| 2 Where we stand | Proposed | | |
| 3 Fit with PLAN_v16 | Proposed | | |
| 4 Edge map | Proposed | | |
| 5 The team | Proposed | | |
| 6 Scorecards | Proposed | | |
| 7 Two loops | Proposed | | |
| 8 Evidence rules | Proposed | | |
| 9 Risk and money | Proposed | | |
| 10 Running cost | Proposed | | |
| 11 Build order | Proposed | | |

The design is final when both AIs mark every section "agreed" (or the owner settles a disagreement) and the owner
approves. No build starts before that.
