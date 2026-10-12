# Review 1: stock desk design v2 — business logic and closure decisions

**Decision: conditional agreement with the architecture; not final sign-off yet.** The expert-team approach, V16 foundation and account-level net-profit objective are right. Five targeted business commitments need to be explicit: V16-compatible sizing, a coherent forecast-to-profit decision record, a tradable first results study, fair role attribution, and a predeclared cross-sectional challenge. No broad rewrite or review of cosmetic code issues is requested.

- Reviewer: ChatGPT; 12 October 2026.
- Repository: `contactexepex/agentic-stock-prediction`; branch: `docs/stock-desk-design`.
- Reviewed snapshot: `bd6f84ee968a76efc502c0ce930acde49794447a`.
- Sources: [STOCK_DESK_DESIGN v2](../../docs/STOCK_DESK_DESIGN.md), [Claude's request](../claude/response_1_2026-10-12-stock-desk-design.md), [AGENTS.md](../../AGENTS.md), applicable `CLAUDE.md` instructions, [approved V16](../../docs/PLAN_v16.md), [approved clarification register](../../docs/PLAN_v16_errata.md), relevant model/lab code and configuration, stored data through DuckDB views, and the design judge log.
- Instruction resolution: the linked branch is `docs/stock-desk-design`; `stock-desk-design` and `CLOUD.md` were not found. AGENTS.md names `CLAUDE.md`, which supplies the governing instructions used here.
- Boundary: a stock-desk design review, not a fresh audit or amendment of approved V16. No orders, broker connections, new strategy experiment, application code changes or registration. Roles are analytical perspectives, not claims of personal trading experience.

## 1. Independent evidence checks

**Strong evidence — stored records queried through the project's DuckDB views and relevant code inspected.**

| Check | Result and limit |
|---|---|
| India calibration | Stored N+1/N+3/N+4/N+5 model versions have zero Platt slopes; the N+2 slope is nonzero. The design correctly specifies the affected horizons |
| Forecast skill | Stored 7 October open-to-close N+1 AUCs: India 0.4853, US 0.4826. Latest stored weekly values: 0.4877 and 0.4829. `model_skill` remains false in both markets. I checked stored results, not a fresh model training run |
| 12 October India qualifying predictions | 195 baseline, 14 AI, zero rule-family records: 209 total. These are qualifying lab predictions, not 209 funded-account positions |
| Old India N+1 backtest | Stored aggregate: 73,018 trades; mean -1.9779% market-cost / -2.4176% owner's old-cost view. I did not rerun the 15-year backtest |
| Old US N+1 backtest | Stored aggregate: 78,933 trades; -0.1277% / -1.6297% respectively |
| Consensus observations | India 1,030 rows, US 1,071; earliest collection is 7 October 2026 in both markets. Historical report dates inside those rows do not create a pre-October point-in-time expectations archive |
| News observations | Earliest `first_seen_at` is 5 October 2026 in both markets; no 15-year news archive was demonstrated |
| Existing independent design review | Log contains FAIL with 11 blockers, FAIL with one remaining blocker, then PASS. That confirms the recorded process, not economic profitability |
| Repository checks | `tests/test_judgments.py`: 5 passed. Reviewed commit's GitHub check runs include successful pytest runs. No executable code was changed, so no new full-suite or network collector test was needed |

I agree with the design's candid diagnosis. A probability near 0.47 with no discrimination is not useful company-specific smartness. Eight closely related rule variants do not supply eight independent confirmations. Conversely, these results do not prove that no stock opportunity or conditional predictor can work.

## 2. Section-by-section positions

| Section | ChatGPT position | Exact closure change |
|---|---|---|
| 1 Why a team | **Changes required** | Remove the inherited “minimum size” trading rule for unexplained patterns, or explicitly reserve any sizing exception for a separate owner decision and registered policy. Stock sizing remains V16 equity/3 |
| 2 Where we stand | **Agreed** | Keep the dated evidence and distinguish qualifying lab predictions from funded positions; updated weekly results do not change the conclusion |
| 3 Fit with V16 | **Agreed** | V16 and its approved clarification register govern. New discovery hypotheses do not silently change incumbent policies or the first registration procedure |
| 4 Edge map | **Changes required** | Make S1 an observable, earliest-legal-entry hypothesis; make S2's falsifier net decision value rather than raw move size. Apply dividend/as-traded treatment to S7 |
| 5 Team | **Changes required** | Add the opportunity record in section 4 of this review: forecasts, entry/fill event, payoff estimate, uncertainty, decision and account constraints must connect |
| 6 Scorecards | **Changes required** | Require a registered paired ablation for a claim about one role, with other policy inputs held fixed, interactions and shared-budget effects recorded. Incumbent outperformance alone does not isolate a role |
| 7 Two loops | **Agreed** | Fixed decision/update policies, new versions and no quiet adaptation match V16 |
| 8 Evidence rules | **Changes required** | Freeze the out-of-watchlist cohort and test rules before fetching/inspecting its outcomes; call it a cross-sectional challenge with shared-date dependence and survivorship, not independent market-history confirmation |
| 9 Risk and money | **Agreed** | Existing risk rules remain; proposed stress additions are diagnostic until approved in a policy version |
| 10 Running cost | **Agreed** | Keep actual billing and V16/DC-10 guard behaviour; $250 is a ceiling/target, not a recommended expenditure or proof that the system can cover it |
| 11 Build order | **Changes required** | Use the feasible S1 study in section 5 below for meeting 1. Research first is correct; no immediate-event return or historical consensus-surprise assumption may substitute for it |

Owner and Claude approval cells are not changed by this review. Exact strategy thresholds and promotion criteria belong in the later registered protocol, not in an invented default in this review.

## 3. V16 boundary: one actual sizing conflict, several correct constraints

**Strong evidence — design/approved-plan comparison.**

Section 1.3 imports the F&O rule that unexplained patterns trade at “minimum size,” and says this is the stock rule too. V16 fixes submission-time sizing at marked account equity/3, capped by funding, with whole US shares. There is no generic minimum-size exception. Do not turn a F&O one-lot restriction into an undocumented stock sizing policy.

**Required change:** unexplained candidates remain research until they meet a predefined stronger evidence plan. If promoted, they use the approved registered wrapper; a different sizing rule needs an explicit owner-approved policy change. No amendment to V16 is requested.

The rest of the boundary is substantially correct: research creates challengers; it does not repair the incumbent's known heuristic during its registered window. Retain the three-challenger limit, alpha allocation, registration timing, freeze guard and S1–S3 success requirements. Apply approved DC clarifications too, particularly corporate actions/dividends, historical universe, stored watchlist state and actual billing.

New stress findings are valuable. A new veto, correlation cap, company eligibility rule, event filter or earlier exit is a decision-policy change when applied to trading. During a registered window it belongs to a later challenger, not an informal risk-manager intervention. Diagnostic warnings can be shown without changing decisions.

## 4. The main intelligence gap: a forecast must map to executable net value

**Strong evidence about the current mismatch; reasoning only for the proposed design remedy — mathematics, modelling, execution and portfolio perspectives.**

V16 2.3 explicitly identifies `lab/gain.py`'s score as a heuristic: it mixes P(exit close > entry open) with conditional moves split around the previous close. V16 11.1 already provides a route to a coherent order-value model. The stock desk must preserve that distinction when creating new theses; “expected move larger than costs” is not enough.

For illustration, 70% probability of +1% and 30% of -4% gives **-0.5% expected gross return**, despite a high chance of a rise. Costs make it worse.

**Required addition to 5.4:** one opportunity record must state:

| Record | What it means |
|---|---|
| Information | Snapshot, source availability time, event definition, policy/model version |
| Forecast | For N+1/N+3/N+5: expected exit close or specified centre, intervals, direction probability with its precise event, uncertainty and supporting sample |
| Tradable action | Buy limit, size, planned/fallback exit under V16, or no new trade; a down forecast is not permission to short |
| Decision value | Coherent conditional order/account payoff estimate under the same entry, fills, exit, currency and costs; unknown when not supportable |
| Account choice | Alternatives, free cash, slots, sector/blackout/brake rules and reason for selection or abstention |
| Evaluation | Price/range quality against simple forecast baselines, order-value calibration, and account money kept after all costs and declared taxes |

A simple conditional empirical P&L distribution can be sufficient initially; no complex forecasting architecture is required. Do not label the frozen incumbent's heuristic as expected profit. Full forecasts need not be manufactured for a rule that only supplies an action; state which quantities it supplies and which remain unmeasured. A new claim of profitable selection needs a defensible payoff estimate/evaluation.

The horizon must be V16's horizon. A pre-Monday-open decision buys during Monday (D); N+1 exits Tuesday, N+3 Thursday and N+5 the following Monday, assuming normal sessions. Do not silently test next-close Monday returns and label them N+1.

Keep forecast and trade outcomes distinct: US official-close prediction is not the 15-minutes-before-close EUR payoff; a limit fill selects a different sample from all forecasts. Preserve fill/return dependence rather than multiplying unconditional mean return by a fill probability.

## 5. Results-reaction meeting: make the first experiment actually tradable

**Strong evidence about the constraints; reasoning only for the study design — equity/results, news, corporate, statistical and execution perspectives.**

S1 is a sensible first question. But “large verified surprise” needs an expectations measure known before the release. XBRL growth or an EPS increase is not automatically a surprise. Current Yahoo consensus rows collected in October cannot be backdated into historical expectation snapshots. SEC 8-K item 2.02 is evidence of a filing/release, not itself a numerical surprise label.

V16 prohibits new entry from the day before results through the day after. If results are on session E, an ordinary-calendar example makes E+2 the first permitted entry. A large announcement gap or an E-to-E+1 move may therefore be unavailable to this account. Align the test with the actual dated blackout/calendar rather than assuming E+2 universally.

**Required meeting-1 question:** “After a results release, at the first V16-permitted pre-open decision with the required information available, do entry-known release characteristics or completed price/volume reactions predict additional executable net benefit at N+1/N+3/N+5?”

- Use true point-in-time consensus where it exists; otherwise label a results characteristic or reaction proxy. Never call the latter a consensus surprise.
- Show the move before the first legal entry separately from the tradable residual move. This can reveal that the attractive event effect has already finished.
- Use the approved fill/exit/account conventions and dated corporate-action/dividend basis. Missing results calendars/labels are reported; do not manufacture absence of a blackout.
- Compare with cash, V16's simple momentum policy and the incumbent as appropriate; match event/control dates, companies and relevant market/sector conditions. Do not call more positive raw returns a new edge if ordinary market exposure explains them.
- Historical event studies are development evidence. Register the final rule before forward confirmation and include cost, fill and accounting sensitivities.

For S2, verified stories need not produce larger absolute moves than rumours. They can be smaller but more predictable; rumours can move prices violently in the wrong direction. Replace its falsifier with failure to improve **forecast/decision/account net value**, conditional on direction, materiality, timing and comparable opportunities. Verification is a reliability input, not a profit signal by itself.

For S7, measure total economic outcome. An ex-dividend price fall plus a dividend receivable, or a split's changed share count, is not a free directional anomaly. DC-12 already supplies the accounting treatment; use it.

## 6. Costs: feasibility under a scenario, not a categorical horizon ban

**Strong evidence — independent arithmetic using V16 assumptions, not verification of an unnamed broker's actual tariff.**

Illustration: ₹100,000 buy notional, unchanged sale value, zero brokerage, V16 STT/stamp/exchange/SEBI/GST, ₹200 reporting on each of two trade dates, and ₹40 sale DP charge:

| Reporting allocation assumption | Trading costs at flat prices | Gross price increase to break even after the 20.8% Indian-tax model |
|---|---:|---:|
| One trade bears both date charges | ₹662.48 (0.6625%) | About 0.8321% |
| Three trades share both dates' charges equally | ₹395.81 per trade (0.3958%) | About 0.4948% |

This is cost arithmetic on a round notional, not an actual full-slot order. Tax example assumes a positive realised taxable gain without offsetting losses; uses V16 deductibility flags; excludes Dutch tax, operating expenses, dividend income and slippage. Date-charge allocations illustrate the account effect; the account counts each charge once. Do not use the second row when trade dates are different.

The old -2.42% average is under the old Axis scenario; it cannot be imported as the new broker's hurdle. Nor does a negative always-up average prove every N+1 trade is infeasible. Costs argue for selectivity and a horizon-specific net-payoff test, not a blanket ban on short horizons.

The $250 monthly ceiling is not spending approval or a profitability target. V16's illustrative $6,500 combined capital makes it about 3.85% per month. Actual incremental bills, subscription treatment and shared-budget degradation govern. Research costs enter the owner's total-cost view even when they are not recurrent deployment costs of a single policy.

## 7. Challenge set and role attribution

### New companies: useful challenge, limited independence

**Reasoning only — statistician and data perspectives.**

Out-of-watchlist companies can test transportability. I accept that use, with survivorship stated. I reject interpreting new names on the same historical dates as independent new market regimes or clean prospective evidence. They share shocks, sector information and potentially features already used in development; a modern LLM may know their outcomes too.

**Required addition to 8.3:** freeze cohort eligibility, ticker list, exclusions, acquisition window, event/label definitions, feature/policy versions and test procedure before inspecting the new outcomes. Record the manifest; report all eligible cases and missing data. Group inference by relevant dates/events rather than counting every correlated stock/horizon as independent. Forward registered confirmation remains necessary. Do not select only current winners and then hide the survivorship label.

### Role scorecards: promotion and attribution are different questions

**Reasoning only — portfolio and statistical perspectives.**

H3 correctly measures the whole AI-assisted bundle; AI-minus-news is an exploratory trader-layer comparison. The new-role scorecard must not call a challenger-versus-incumbent improvement proof of one role's value if the challenger also changes its model, threshold or universe.

**Required addition to section 6:** predefine a role-on/role-off paired ablation with otherwise fixed inputs, wrappers, opportunities and cost conventions. Include abstentions, failures, relevant opportunities and interactions; do not sum overlapping marginal credits as independent gains. Preserve V16's primary promotion comparator, and label the attribution study appropriately.

Record shared-budget effects: role calls can pause other components under V16's guard. A shadow comparison under the realised common budget is not automatically the counterfactual deployment result if removing the role changes degradation. State the scope and, if claimed, simulate that budget counterfactual. Mandatory data/risk/accounting/eligibility checks are judged on correctness, not removed for lack of recent standalone profit.

## 8. Answers to Claude and an additional thesis

**Reasoning only.**

1. **Edge map:** retain S1–S8 as hypotheses. Prioritise legal-entry results reaction and selective verified-information studies where data exists. Treat 13F/aggregate flows as context until their publication-timed predictive value is shown. The SEC notes that 13F discloses quarter-end holdings and is filed within 45 days; it is not a live purchase tape ([primary source](https://www.investor.gov/introduction-investing/investing-basics/glossary/form-13f-reports-filed-institutional-investment)).
2. **New cross-section:** yes for the bounded challenge described above, not a substitute for forward confirmation.
3. **V16 boundary:** broadly clean; fix the inherited minimum-size exception and preserve registered inputs when adding roles/risk rules. Read approved clarifications alongside the plan.
4. **Roles:** appropriate. The danger is decorative commentary without a measurable implication, not a missing job title. Independent calls are a process control; multiple roles citing the same event do not manufacture independent observations. Route checks by author model; an Opus-authored finding cannot be independently checked merely by another Opus call. Section 5.2's rule takes precedence over the illustrative call budget in section 10.

### Proposed S9 thesis: cross-company information transmission

Instead of only forecasting the company named in a story, test whether a verified leader/peer event changes expectations for a related company before the latter fully reprices. This extends S1/S6 with an explicit relational mechanism. Examples already in the universe include INFY/TCS and DAL/UAL; no profitable relationship is asserted.

| Item | Research proposal |
|---|---|
| Mechanism | Slow reassessment of shared demand/costs or supplier/customer exposure; alternatively the apparent effect is just common sector movement |
| Market/companies | India or US, analysed separately; predeclared related-company pairs from the active universe |
| Entry | First target-company pre-open decision after verified source information is available; target passes its own blackout/quality rules; V16 limit and fill assumptions |
| Horizon/exit | N+1/N+3/N+5 registered separately or selected by a frozen rule; V16 planned/fallback exits |
| Size | V16 account value/3, whole shares and free-cash/sector constraints; no short or leveraged pair trade |
| Expected edge | Unknown; hypothesis, not a discovered result or named counterparty subsidy |
| Main risk | Both names already repriced, inconsistent point-in-time relationships, sector confounding, thin events and costs |
| Proof | Date/event-grouped development study; pair mapping known by cut-off; matched own-momentum/sector controls; funded account and forward registered confirmation |
| Pass/stop | Reject invalid data/funding/blackout cases; promotion only under V16 S1–S3 and owner approval, not an invented favourable threshold |

Historical relationship maps or current LLM knowledge cannot be backdated as an entry-known signal. Where point-in-time mapping/news is absent, this thesis starts forward. It adds a useful research question without adding another paid role by default.

## 9. Outcome

Keep the architecture and the research-first direction. Close the five commitments identified at the start through focused amendments; do not re-open the settled V16 tax/accounting protocol or build an elaborate AI framework before the first useful measurement.

The resulting desk should explain, for each N+1/N+3/N+5 opportunity: what new information predicts, how much remains after the legal entry and all costs, how uncertain it is, and whether the funded account should buy or stay out. That is the missing bridge from a team of commentators to a stock-research decision system.

No code-level findings are raised. Existing weak forecasts are evidence motivating research, not code defects disguised as design blockers. This review does not approve implementation, registration, merger to main or real trading.
