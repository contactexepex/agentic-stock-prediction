# Agentic Stock Prediction: final design (v16)

Prepared 11 October 2026 by Claude, for the owner and for ChatGPT's targeted check of the v16 changes.

**Review status.** ChatGPT agreed with v13 as the complete, phased design for paper research; v14 added only its three wording clarifications. The independent judge then reviewed v14 (FAIL: 6 blockers, 13 cosmetic findings; all arithmetic passed). ChatGPT reviewed the judge's findings and Claude's verification: it accepted the six blockers (several with changed fixes), rejected cosmetic finding #11, and asked for a focused correction pass. v15 applied those corrections. ChatGPT then checked v15: it accepted the architecture and most corrections, and asked for three bounded corrections plus the volatility reconciliation. **v16 = v15 with only those corrections**, each marked **[CHANGED IN v16]**; nothing else changed. Appendix D records every review and each decision. **Next: ChatGPT's targeted check of the v16 changes, then the judge's re-check, then the owner's decision on the build.**

**Status.** v16 is complete and self-contained. It replaces every earlier version; no earlier document is needed. It includes everything agreed with ChatGPT, every owner decision of 10 and 11 October 2026, and the corrections agreed after the judge's review.

**What this document is: the complete design, corrected.**
- **Nothing is built until Claude and ChatGPT agree on this design and the owner approves it** (owner decision, 11 October 2026). Sections 10 and 14 describe the build that follows that approval.
- The design includes the **procedure** that later fixes the evaluation's numbers (window lengths, method, α split, power). Those numbers are produced in build step 3 from development data only, and are themselves reviewed by ChatGPT before they are registered (Section 8.1).
- This document therefore registers nothing.

**Evidence base:**
- repository `contactexepex/agentic-stock-prediction`, `origin/main` at 82ff0f5 (10 Oct 2026);
- stored data queried on 10–11 October 2026;
- public sources in Appendix C.

---

## Contents

1. Goal, success definition and claims policy
2. What exists today (verified facts)
3. Owner decisions
4. Trading conventions (accounts, execution, costs, attendance, currency, tax, risk)
5. Operating costs, the budget ceiling and the AI comparison
6. Data and audit model
7. Scoreboards
8. Evaluation protocol
9. The baseline and the account policies
10. Build plan for steps 1–3
11. Deferred design for steps 4–6
12. What the owner sees
13. Open items and verification status
14. Governance, sessions and timeline

Appendix A: worked trades. Appendix B: failure fixtures. Appendix C: sources. Appendix D: review record. Appendix E: volatility script and output.

---

## 1. Goal, success definition and claims policy

### 1.1 The owner's goal

The owner is a retail investor, not a financial specialist, and wants:
- a research tool where **AI does the heavy lifting**, so the owner never has to choose indicators, strategies or weights;
- per company: an expected price for N+1, N+3 and N+5, a likely range, an up/down lean and a plain-language reason;
- **paper trading run exactly as the owner would trade real money** at the real brokers, before any real money is used.

The system never places real trades and never connects to a broker.

### 1.2 Success definition

A policy is a success only if **both** hold over its evaluation window:
1. **Absolute:** money kept is **positive after all relevant deductions**: trading costs at their charging unit, the declared tax scenario computed per tax period (Section 4.8), and the policy's deployment operating costs (Section 5.2).
2. **Relative:** its **after-tax** advantage over its designated comparator meets the declared economic criterion (Section 8.7).

"Better than cash" alone is not success, because cash can lose money after tax and a smaller loss would beat it.

**Net profit per trade (owner decision, 11 Oct).** Every paper trade is charged, from its first day, every cost a real trade would pay: broker fees, government transaction taxes (STT, stamp duty), exchange and regulator fees with GST, depository and NRI reporting charges, order fees and currency conversion. The **net profit of each trade after all trading costs** is the primary per-trade number. Income tax is assessed per year, not per trade, so it is shown as a yearly estimate beside it (Section 4.8).

**The account result governs.** Per-trade net profit is shown on every trade, but success is decided only on the **account**: profitable individual trades can still leave an unprofitable account after idle cash, the plan fee, AI costs and tax. Every report shows the account result first.

Forecast accuracy is a means, not the measure.

### 1.3 Claims policy (binding)

- No claim of profitability without passing the protocol in Section 8, and even then only in the bounded wording of Section 8.9.
- Reproducing a number shows that it follows from its inputs and rules. It does not show that the rules match reality.
- Account profit is **derived under assumptions**, even when every price input was observed.
- Two AIs agreeing on a plan is a design review, **not evidence of a trading edge**.
- If trading benefits do not cover costs, including AI operating costs, that is reported as the finding. AI is never added "until the backtest looks good".
- Steps 1–3 build a truthful account of what the current system would have earned. **They do not improve its forecasts.**
- Statistical power is stated **per hypothesis**, from the variability of **that comparison's paired difference**, once step 3 has estimated it. No categorical "cannot be established" claim is made. Where a hypothesis is underpowered, the report says so with its numbers.
- No result label claims more than its evidence. The statistical evidence in this protocol is **before tax**. No label says an **after-tax** minimum improvement is "established" (Section 8.9).
- Whether the system pays for itself depends on the **actual bills** (Section 5.1). Token usage valued at list prices is information, not money paid. Neither profitability nor unprofitability is claimed from it.
- Absence of harm is **not** evidence of a positive net expectation. Insufficient power never replaces the profitability objective with a weaker one. If profitability is not established, the report says exactly that. Any real-money step is then the owner's own risk decision, and the system does not recommend it.

---

## 2. What exists today (verified facts)

### 2.1 Pipeline

- Daily pre-open runs per market collect data and compute:
  - indicators and the regime;
  - signal-model scores (`model_scores`);
  - price ranges (`ranges.py`).
- They run 15 strategies (8 rules, 3 baselines, 4 AI traders) and record `strategy_predictions` and `head_to_head_picks`.
- Paper trades settle after the close (`lab/settle.py`) in two cost views ("market cost" and "your cost", `cost_views`).
- Everything is append-only in `data/<market>/`, mirrored to MotherDuck for the web app, and posted to Slack.

### 2.2 Go-live and horizons

**Go-live:** strategies count from **12 October 2026** (`live_from` on all 15; switch-on content commit `d5eb82c`, merged to main by `d5c8a27e`) .

**Horizons:**
- D = the first session after the last known close.
- N+k = the close of the k-th session after D.
- Example: a forecast before Monday's open means buy at Monday's open; N+1 sells at Tuesday's close.

### 2.3 What the current quantities mean

| Quantity | Exact event or formula | Code |
|---|---|---|
| Model P(up) | P(X > O_D): the exit **close** X above **the open of D**, in the stock's currency, before costs | `model/labels.py` |
| Rule strategy probability | sigmoid(logit(prob_model) + news_weight × coefficient × clipped news score), where prob_model is the calibrated model score **without** news, so news enters once | `lab/strategies.py` lines 5, 88–92 |
| Target and 80% range | the exit close, anchored on **the previous close C** | `analytics/range_row.py`, `range_math.py` |
| `move`, `loss` | E[X/C − 1 \| X > C] and E[1 − X/C \| X < C], for X ~ N(target, σ) with σ from the 80% range | `lab/gain.py` lines 22–34 |
| `expected_gain_pct` | p × move − (1 − p) × loss − round-trip cost, with **p from the model** (event split at O_D), **not** the normal's own P(X > C) | `lab/gain.py` line 37 |

**Consequences:**
- `expected_gain_pct` is a **heuristic score**, not the expectation of a single distribution. It equals (target/C − 1) + (p − P_N(X > C)) × (move + loss) − cost. The frozen baseline keeps it, but it is never shown as an expected profit.
- Even for an order filled at the open, P(up) is about the **close in the stock's currency before costs**. For the US account, the trade's profit is decided at **15:45 ET**, in **EUR**, **after costs**. Those are different events. P(up) is therefore never presented as a chance of profit.

### 2.4 Known weaknesses (verified on 10 Oct)

1. **Reference mismatch** (2.3). Example : for Delta Air Lines, the 9 Oct open was 3% below the 8 Oct close, and the sign of the score flipped from −0.26% to +0.87% between references.
2. **The India signal model is degenerate:** Platt slope 0.0 at N+1, N+3, N+4 and N+5, so P(up) is a constant of about 0.47.
3. **No learned move size:** the price centre is about "no change".
4. **Direction skill at coin level** : the weekly review of 7 Oct 2026 reports, for the **1-day open-to-close** label, AUC 0.485 for India and 0.483 for the US; India's 1-day **close-to-close** AUC is 0.519. None of these establishes useful discrimination; `model_skill` is false.
5. **Ranges: over-cover, and better quality is not shown** . The historical rule-only replay (`python scripts/replay.py --market india`, 2 Jan 2025 – 9 Oct 2026) over-covers its nominal 80% bands. Its intervals are wider than the naive baseline and have slightly worse observed interval scores at N+1, N+3 and N+5 (lower is better):

   | Horizon | Coverage of the 80% band (95% interval) | Engine width | Naive width | Engine interval score | Naive interval score |
   |---|---|---|---|---|---|
   | N+1 | 83.6% (82.1–85.2%) | 5.73% | 5.19% | 7.777 | 7.745 |
   | N+3 | 84.3% (82.4–86.3%) | 8.64% | 7.34% | 11.077 | 10.856 |
   | N+5 | 85.4% (83.1–87.6%) | 10.88% | 8.99% | 13.697 | 13.277 |

   Each coverage interval excludes 80%. **Superior interval forecasting has not been demonstrated.** These figures do not establish a statistically significant inferiority either. (v14's "84.3% / 87.8%, reasonably calibrated" could not be reproduced and is withdrawn.)
6. **News** is a fixed-weight sum counted per article, not per event.
7. **The "rule" strategies are not AI-free:** all 8 use news (`news_weight` 0.5–2.0) scored by the news-analyst agent, with statuses from the claim-checker agent. Only `base.always_up`, `base.momentum` and `base.model_only` are AI-free.
8. **The head-to-head pick is adaptive:** within a family it picks the "strongest strategy" by settled profit to date (`lab/picks.py` lines 83–104). This is an update rule, frozen as a rule.
9. **No learned forecast combination.** The ACI range correction exists but is off.
10. **Paper trading** today: each prediction trades ₹1L / $1k independently. There is no funded account and no early exit.

### 2.5 History

**15-year backtest at the old broker costs** (`data/<market>/lab_backtests/2026/10/2026-10-10.jsonl`, 2011-01-03 to 2026-10-09):

| Market / rule | Trades | Mean result per trade |
|---|---|---|
| India, always-up, N+1 | 73,018 | −1.98% (market cost) / −2.42% (owner's then cost, Axis Direct NRI) |
| US, always-up, N+1 | — | −0.13% / −1.63% (BUX Basic, FX each way) |

**All stored history (2011 to 9 Oct 2026) has already been used** in development. It is development or retrospective data only. The only clean evidence is forward data.

---

## 3. Owner decisions (10 October 2026)

| Topic | Decision |
|---|---|
| Objective | net money kept after all costs and taxes; forecasts support it |
| India broker | zero-brokerage delivery broker, **not yet named**; the India account is labelled "broker scenario" until confirmed |
| US broker | **BUX Plus**: €2.99/month, 0.25% FX each way, €0.99 per US order, limit orders, fractional shares market-only |
| Capital | India **₹3,00,000**; US **$3,000** (counted in EUR) |
| Size per trade | **account value (marked to market) ÷ 3**, capped by free cash, fixed at order submission |
| Positions | at most **3** open per market; at most **2** in one sector |
| US shares | **whole shares with limit orders**; unused cash stays cash; stocks priced above the slot cannot be bought |
| Limit orders | placed before the open, **stay active all day** |
| India exit | **NSE closing auction (CAS)**: market sell 15:20–15:24 IST; the owner confirmed the 4-minute window |
| US exit | **the owner sells by hand 15 minutes before the scheduled close** (normally 15:45 ET) |
| Loss brake | pause new entries when equity is **10% below its peak**; restart only with owner approval |
| Results | **no new entry from the day before a company's results until the day after** |
| Tax | Netherlands Box 3 (rules per calendar year; the 2028 actual-return plan as a scenario); India short-term capital gains 20% + 4% cess for an NRI, per Indian financial year |
| Currency | **US equity in EUR**; **India equity in INR** |
| AI costs | cut now: rules daily, AI traders daily on Sonnet, Opus only on event days and weekly; **$250/month ceiling for the whole system** (both markets; Section 5.3); 4-week cost study |
| Minimum worthwhile improvement | **0.5% of funded capital per month** (₹1,500 / about $15 in EUR terms) |
| AI autonomy | AI tests ideas automatically; **the owner approves every promotion** |
| Build start | **only after Claude and ChatGPT agree on the full design and the owner approves it** (11 Oct) |
| Trading costs | every paper trade carries every real trading cost from day one; per-trade net profit is the headline number (11 Oct) |
| Personal inputs | none needed during the paper phase; the tax and interest details use labelled defaults and are confirmed only before any real money is used (11 Oct) |
| Evening forecast run | 21:30 UTC India / 18:30 New York time US, Mon–Fri. **Owner decision (11 Oct): it waits.** It was due to be built from 13 Oct; it is now built only after Claude and ChatGPT agree on this design and the owner approves it. The same hold applies to the morning revision, moving the weekly run to Friday and retiring the old dashboard page. The build session (B17) has confirmed the hold; the live system runs unchanged from 12 Oct. Its outputs and any morning revision are **additive records**; registered policies read only the frozen pre-open rows (Section 8.10) |

---

## 4. Trading conventions

### 4.1 Account types

| Type | What it is | Attendance and approvals | Starts |
|---|---|---|---|
| **Policy account** | one per policy per market (Section 9.3), run by the simulator from decisions recorded before the open | **assumed**: every instruction counts as carried out at its declared time; **assumed approval scenario** for the loss-brake restart (Section 4.9) | once built, computed forward from the pre-open decisions recorded since 12 Oct 2026 (exploratory until registration, Section 8.3); also replayed over history as development data |
| **Owner rehearsal account** | one per market, following `acct.rule.v1`; instructions sent live to the owner | **recorded**: Done taps, misses, fallbacks and real restart approvals | the first session after live instructions and Done buttons are built, judged and deployed; **never back-dated** |

The difference between the rehearsal account and the `acct.rule.v1` policy account on the same dates measures **the combined effect of real attendance and real restart approvals**. It is not attendance alone, because the policy account uses an assumed approval scenario.

### 4.2 Funding, sizing, reservations and cash interest

**Starting cash:**
- **India:** ₹3,00,000.
- **US:** $3,000 converted to EUR at q₀, the latest stored EUR/USD observation with timestamp ≤ the first decision's information cut-off (Section 4.7). Equity is kept in EUR.

**Slot size:** S = (marked-to-market equity) ÷ 3, computed at order submission.

**Reservations at submission:**
- the order value at its limit L;
- the estimated buy fees;
- the estimated future sale fees, with the slot value as the base;
- any date-level charge not already reserved that day.

No tax reserve at submission. Under every broker scenario of Section 4.8, tax is withheld or blocked **out of the proceeds of the sale** it relates to, so it never makes cash negative, and the submission-time quantity never depends on a future gain. Its effect is to reduce the cash **available for trading after the sale**. How much is held back depends on the broker: a share of the gain (W1, W2) or a block based on the **sale proceeds** (W3). Withholding is therefore not limited to a share of the gain.

Reservations are released or adjusted when the order fills or expires.

**Quantity at submission:**
- India: floor((S − reserved fees) ÷ L) whole shares.
- US : floor(USD available ÷ L) whole shares, where USD available = (S − €0.99 buy − €0.99 sale reserve) × q_sub × (1 − b) × (1 − 0.25%); q_sub is the latest EUR/USD observation with timestamp ≤ the submission time and b is the FX buffer below (default 2%). This is the **only** US quantity formula, used in sizing, reservations, the worked trade and every fixture.

**Free cash** = cash available for trading − reservations. A new order needs free cash ≥ its reservation; otherwise it is skipped with reason `insufficient_free_cash`.

**Cash states (ledger), kept separate:**

| State | Meaning |
|---|---|
| Settled cash | cash after exchange settlement |
| Unsettled sale proceeds | proceeds of a sale before its settlement date |
| Available for trading | what the broker scenario lets the account spend now (below) |
| Temporary block | an amount the broker holds back pending a tax computation (India scenario W3, Section 4.8). **[CHANGED IN v16]** **Not a separate asset and not an expense.** The blocked money stays counted **once**, inside the underlying balance it belongs to: **unsettled proceeds before settlement, settled cash afterwards**. The block only restricts **availability**: it is excluded from cash available for trading until released |
| TDS credit receivable | tax withheld, a credit against the year's liability |
| Other receivables | refunds and interest awaiting payment |

**Buying-power scenario for sale proceeds** (broker-dependent, not established by exchange rules alone):
- **Default: proceeds become available for new orders only after settlement.** Exchange settlement is T+1 (NSE; US equities since May 2024). An exit at the close of day E therefore cannot fund an entry at the open of E+1.
- **Sensitivity:** proceeds available immediately after the sale.
- **Neither is a bound on profit.** Delayed cash can prevent a profitable trade, but it can equally prevent a losing one, so the delayed default is **not** called conservative. The results show both, and a finding that holds under only one is labelled "depends on the broker's buying-power rule".

**US FX reservation buffer and rejection rule.** The euro cost of a US buy depends on EUR/USD at the fill, which is unknown at submission. Example: slot €1,000, limit $99, q_sub 1.10 → 11 shares ($1,089); at the limit the euro cost including the buy fee is €993.47 at q 1.10 but **€1,011.85 at q 1.08**.
- **Quantity and reservation use the buffered rate** q_sub × (1 − b): USD available = (S − €0.99 − €0.99) × q_sub × (1 − b) × (1 − 0.25%), and the reservation = the euro cost of that quantity at the limit at the buffered rate, plus fees. So the reservation stays within the slot even if EUR/USD falls by b before the fill. The buffer b is a registered parameter: the 99.9th percentile of the absolute overnight EUR/USD move, measured in step 3 from the long-history cache (the main store holds only about a month of EUR/USD); until then the default is **b = 2%**.
- **Quantity stays fixed** at submission. It is never resized after the fact.
- **At the fill:** if the actual euro cost exceeds the reservation plus free cash, the order is **rejected** (`insufficient_cash_at_fill`) and counted as unfilled. A fill is never resized to fit.

**Marking:**
- equity is marked at each close, using the official close and, for the US, the EUR/USD value of Section 4.7;
- open orders are not equity.

**Cash interest:**
- Interest is a property of the **account plan**, never granted without that plan's fee.
- **US trading accounts (BUX Plus):** the Plus rate on uninvested cash, accrued daily (actual/365) and credited monthly, **with** the €2.99 monthly fee.
  - BUX's two official sources disagree: the pricing page says 1.75% for Plus (2.00% Prime); the fee-schedule PDF says 1.50% for Plus (1.75% Prime).
  - The rate is a **dated parameter**: the default is **1.50%** (the lower official figure, so the trading account is not flattered); sensitivity 1.75%. Confirmed only before any real money is used.
- **India trading accounts:** the actual rate on idle trading cash, from the owner (dated parameter); default 0% (assumed); sensitivity 3%.

**No leverage, no short selling.**

The 15 research strategies keep their independent simulations for comparison. **Their summed results are never shown as an account return.**

### 4.3 Entry execution

1. **Decision time:** the pre-open run. The decision record stores its information cut-off timestamp and the input snapshot ids.
2. **Order:** a day **limit buy** at L, placed before the open.
   - India: an after-market order into the NSE pre-open; unmatched orders move to the normal market.
   - US: a BUX Plus limit order that waits and becomes active at the open (the owner confirmed this in the app).
3. **Entry limit for all policies:** **L = previous close × 1.005**.
   - Sensitivity alternatives: L = previous close × 1.000, and a market order at the open.
   - The limit is not tuned afterwards.
4. **Simulated fill (from daily bars):**
   - if Open ≤ L → **filled at the open**;
   - else if the day's Low < L by at least one tick → **filled at L** (intraday fill);
   - else → **unfilled** (expires at the close).
   - A buy fill is never above L.
5. **Execution sensitivity variants**, reported every time:
   - (a) trade-through of 1 tick, 0.1% or 0.25%;
   - (b) open-only;
   - (c) intraday fills only when Low ≤ L − 0.25%.

   Any result that holds only under the most optimistic variant is reported as **not robust**.
6. **Forward period:** fills are still simulated from published prices. A fill is always labelled **assumed**, never "executed".

### 4.4 Exit execution

**Planned exit day:** the N+k session of the trade's horizon.

**India** (CAS applies to F&O stocks from 3 Aug 2026):
1. **Closing auction:** a **market** sell submitted **15:20–15:24 IST** (market-order entry closes 15:25), at the auction price, which is the official close. Verified in NSE circular NSE/CMTR/73362:
   - the reference price is the VWAP of 15:00–15:15;
   - the band is ±3%;
   - only limit and market orders are allowed;
   - if no equilibrium is found, the close = the reference price.
2. **Fallback 1:** a market order in the **post-close session (15:50–16:00 IST)** at the closing price. A fill is not guaranteed.
3. **Fallback 2:** a market sell at the **next opening auction**, placed the evening before.
4. **None carried out:** **"exit not executed"**. The position stays open, is marked to market, counts in the loss brake, and the chain is re-attempted the next session.
5. **Historical replay:** before 3 Aug 2026 the official close was the 15:00–15:30 VWAP. Each date's own convention is used.

**US:**
1. Exit time = **15 minutes before that day's scheduled regular close** from the exchange calendar: normally 15:45 ET; 12:45 ET on early-close days (e.g. 27 Nov 2026).
2. A market sell by hand at that time. Fill = the observed price from the 5-minute bar ending at the exit time, fetched by the post-close run for every US ticker exiting that day. If it is unavailable, the proxy below is used and labelled.
3. **Fallback:** a market sell at the next open.
4. **Not carried out:** "exit not executed".
5. **Historical replay:** 15:45 prices do not exist for 15 years. The proxy is the close × a factor drawn from the measured (15:45 price ÷ close) distribution, with:
   - **common random numbers** across competing policies;
   - repeated simulations, with the spread reported;
   - differences smaller than the proxy spread reported as "**advantage not established**".

**Time zones:** IANA time-zone database. Examples:
- 15:45 ET = 21:45 Amsterdam on 12 Oct 2026, **20:45 on 27 Oct 2026**, 21:45 on 3 Nov 2026;
- 15:20 IST = 11:50 Amsterdam on 12 Oct 2026, 10:50 on 3 Nov 2026.

### 4.5 Costs, at their real charging unit

**India: zero-brokerage scenario**, an estimate until the broker is named and its NRI schedule confirmed.

| Charge | Rate | Unit | Tax-deductible from the gain? (scenario, Section 4.8) |
|---|---|---|---|
| Brokerage | ₹0 (scenario) | order | yes (transfer expense) |
| STT | 0.1% | each side | **no** (excluded by Indian guidance) |
| Stamp duty | 0.015% | buy | yes (part of cost of acquisition) |
| Exchange fee | 0.00307% | each side | yes |
| SEBI fee | 0.0001% | each side | yes |
| GST | 18% | on brokerage + exchange + SEBI fees | yes |
| NRI reporting | ₹200 | **trade date**, shared by all orders that date | **no** (conservative default; sensitivity yes) |
| DP charge | max(₹30, 0.04% of sale value) | **scrip sold** | **no** (conservative default; sensitivity yes) |

**US: BUX Plus** (official fee schedule, plus the pricing page for order fees):

| Charge | Rate | Unit |
|---|---|---|
| Plan fee | €2.99 | **month**, account level, charged even with no trades |
| Order fee | €0.99 | US order |
| FX markup | 0.25% | each EUR↔USD conversion |
| Variable service fee | 0% below €250k | — |
| Zero orders | not available for US shares | — |

**Slippage stress view:** +0.05% per side on market-order fills. A buy-limit fill is never stressed above L.

The existing cost views (Axis Direct / BUX Basic) stay for history. The new scenarios are **added as named cost scenarios**; old records are not rewritten.

### 4.6 Owner attendance (rehearsal account only)

- Every required action gets its own Slack reminder with a **"Done"** button, through the existing `/slack/interactions` route. The actions are:
  - the morning order;
  - each exit step: India auction, post-close and next open; US 15:45-equivalent and next open.
- Each tap is stored with its timestamp as an append-only event.
- A missed action does not imply that the next one happens; each fallback needs its own acknowledgement.
- A tap records a **paper instruction**. The fill stays **assumed**.
- **Caveat:** paper attendance may overstate or understate real-money discipline.

### 4.7 Currency

**Source:** stored EUR/USD observations (Yahoo `EURUSD=X`, quoted as USD per EUR):
- daily bars, each with its declared `close_time`;
- 5-minute bars collected forward by the intraday checks (EURUSD=X added to `config/intraday.yaml`) and by the post-close fetch.

**Rule:** every use takes **the latest observation whose timestamp is ≤ the event's timestamp**.

| Event | Rate used | History fallback (labelled approximation) |
|---|---|---|
| Account start | latest observation ≤ the first decision's cut-off | — |
| Quantity at submission | latest observation ≤ submission time | the latest daily close dated **before** the event's date |
| Buy conversion at fill | latest 5-minute observation ≤ fill time | the latest daily close dated **before** the event's date (see the timing note below) |
| Sale conversion at exit | latest 5-minute observation ≤ exit time | the latest daily close dated **before** the event's date |
| Daily mark | latest observation ≤ the US close (16:00 ET) | the latest daily close dated **before** the event's date |

Formula: 1 + r_EUR = (1 + r_USD) × q_entry / q_exit, with q in USD per EUR. Each conversion also pays the 0.25% markup. The reservation buffer and the rejection rule at the fill are in Section 4.2.

**Timing of historical FX** . Daily stock bars show **that** a limit was reached (Low < L), not **when**, so the fill-time EUR/USD rate cannot be known. The stored EUR/USD daily close is declared at **23:59 London** (`config/markets/us.yaml`), later than any US fill, exit or 16:00 ET mark of the same date, so using it for that date's events would be a look-ahead. The rules:
- **every historical US-session conversion, rejection test and mark uses the latest daily close dated before the event's date** (declared 23:59 London of an earlier day, e.g. Friday's close for a Monday event, so certainly earlier than the event). This avoids relying on an unverified timestamp convention for the daily open;
- it is labelled "historical FX approximation", and **[CHANGED IN v16]** **the observation's actual age** (event time minus observation time) **is recorded with every use**. It is often more than one day: Friday's close serves a Monday event, and holidays lengthen the gap. It is **not** inherently conservative;
- **predefined adverse stresses** are run and reported: the rate moved against the account by the 95th and 99th percentiles of the absolute one-day EUR/USD move, measured from the long-history cache;
- the **account-level effect** of these choices (fills rejected or allowed, holdings, later buying power and money kept) is measured and reported, not assumed small;
- the same-day close may be shown only as a separately labelled **diagnostic**; it never governs a decision attributed to an earlier time;
- forward fills, exits and marks use the 5-minute observation at the event time where available.

**India account:** INR only. A EUR view is shown for information.

### 4.8 Tax (scenario estimates, never exact liability)

**Principles:**
1. Tax is computed **per tax period**, by that jurisdiction's own rules:
   - Netherlands: the **calendar year**;
   - India: the **financial year 1 April – 31 March**.
2. **Taxable gain and economic profit are separate calculations.** Each cost carries a deductibility flag (Section 4.5).
3. The after-tax result of a window = economic money kept − the tax attributed to the window (rule 6).
4. Tax enters the **economic success conditions** (Section 8.7) for the candidate **and** its comparator, computed the same way.
5. Tax does not enter the daily series used for the statistical test (Section 8.6). The test's conclusion is labelled "before tax".
6. **Attribution of a period's tax to a window:**
   - Netherlands deemed return: the tax of a calendar year is fixed by the 1 January holdings. It is attributed **pro rata to the days of that year inside the window** (registered rule), with sensitivity "full year".
   - India: the tax of the window's part of a financial year is computed on **the net short-term gains realised inside the window in that financial year**, with losses offset within the same financial year.
   - A net loss is carried forward as a tax asset valued at **0** (conservative default), with sensitivity "valued at the full rate".

**Netherlands Box 3 (deemed return):**
- **2026, used for 2026 only:** 6.00% on investments and 1.28% on savings (provisional), taxed at 36%, on holdings at the 1 January reference date.
- **Funding origin and counterfactual.** Box 3 taxes the household's assets and debts on 1 January, not a particular account. The capital used by the tool existed somewhere on 1 Jan 2026. So:
  - the simulation uses a **default funding origin**: the capital would otherwise have stayed in a savings account (the counterfactual). The paper accounts hold no real money, so this is a labelled modelling assumption, not a question to the owner; it is confirmed only before any real money is used;
  - the **marginal tax** of a policy = the household tax with the policy − the household tax under the counterfactual, per calendar year;
  - **2026 under the deemed regime:** the 1 Jan 2026 position is the same in every policy and in the counterfactual, so the **difference between policies is €0**. That does **not** mean the capital carries no 2026 tax: its tax is the same whatever the policy, and it is shown in the absolute view as the counterfactual's tax;
  - **2027 onwards:** the 1 January mix of shares and cash in each policy changes the deemed tax against the counterfactual.
- **Counter-evidence regime: a household-level comparison, not a flat 36%.** The actual return is used only when it gives the **lower** tax, and it covers the whole household. So the household tax is min(deemed, actual), and the **marginal** effect of a policy = min(deemed, actual) with the policy − min(deemed, actual) without it. It can be:
  - **zero**, when the deemed calculation stays the lower one (e.g. deemed €1,000, actual €1,500: a trading gain that raises the actual figure by €36 changes nothing payable);
  - **36% of the policy's actual return** (costs not deductible), when the actual calculation is and stays the lower one;
  - **in between**, when the policy moves the household across the boundary.
  - The actual-return calculation follows the published rules: a **negative total actual return is set to zero** for that year and **cannot be carried into another year**. The C scenarios apply this floor.
  - There are no household inputs during the paper phase, so the simulator reports three labelled scenarios: **C0** (deemed stays lower: marginal = the deemed effect only), **C1** (actual stays lower: 36% of the policy's actual return), and **C2** (boundary: computed with a stated household deemed and actual figure as an assumption).
- **Attribution to a window** (the pro rata of rule 6) is a **reporting convention**, labelled as such.
- **Other years:** entered only when the Belastingdienst publishes them. Until then the rate is "unknown", with a sensitivity of 6.00–7.78% (public 2027 figures conflict: 6.37% in one report, 7.78% in a parliamentary motion).
- **Anti-arbitrage (corrected wording):** a pair of transactions is flagged only when **all** of the following hold:
  - a shift between investments and cash happens before 1 January;
  - it is reversed after 1 January;
  - **the shift and its reversal are no more than 3 months apart**.
  The scenario then shows both values. The non-tax-reason exception (scheduled N+k exits are plausibly non-tax) is for the tax adviser.
- **Counter-evidence scheme:** allows declaring the actual return when it is lower, including in positive years. **Costs are not deductible** under it (Supreme Court, 6 June 2024).
- Box 3 works on total wealth, so the simulator reports a **marginal scenario estimate**.

**Netherlands 2028+ (planned actual-return system):** a separate scenario; net trading gains taxed at about 36%; deductibility of costs not assumed.

**India (NRI):**
- **Rate:** short-term capital gains (listed equity held ≤ 12 months, STT paid) at 20% + 4% cess, about 20.8% (Finance Act 2024, transfers from 23 July 2024).
- **Taxable gain** = sale value − cost of acquisition (including stamp duty) − transfer expenses (brokerage, exchange and SEBI fees, GST on them). **STT is not deductible.** DP and NRI reporting charges are not deducted by default.
- **TDS: four separate amounts, never a second tax.**
  1. **Available broker cash:** the sale proceeds minus the TDS withheld on that sale.
  2. **TDS credit (an asset):** each amount withheld is booked as a **tax credit receivable**, not as an expense. Equity includes it at face value.
  3. **Final tax expense:** the financial year's liability from the tax computation above. It is the **only** tax expense.
  4. **Settlement:** credit − liability = a refund (an asset until its assumed date) or an extra payment.
  - Example (fixture B.23): ₹1,000 withheld and a final liability of ₹600 → cash drops by ₹1,000 when withheld; the tax expense is ₹600; ₹400 is a refund receivable. The total tax charged is ₹600, never ₹1,600.
- **Withholding mechanics are broker scenarios, not one universal rule.** ChatGPT reports from broker documents that HDFC's PIS route sets off current-year losses, and that Zerodha's Non-PIS route provisionally blocks, releases and deducts, with losses offset against later profits. I have not read those documents. Until the owner names the broker, three scenarios are reported:
  - **W1, per sale:** withholding on each profitable sale, refund after the year (the most cash drag);
  - **W2, year-to-date netting:** withholding on the cumulative net gain of the financial year, so earlier losses reduce later withholding;
  - **W3, proceeds-block liquidity stress (custom scenario):** a temporary block of a registered share of the **sale proceeds** on the sale date (stress parameter, default 25%), released at the end of T+1 and available from T+2, after which the actual TDS is deducted, with losses offset against later profits in the financial year. The timing follows ChatGPT's description of Zerodha's published Non-PIS process; the 25% size is our stress assumption. **It is a custom stress scenario, not a reproduction of any broker's confirmed mechanics.** Not read by Claude; confirmed only once the broker is named.
  - The refund date is an assumption: 31 December after the year end, with a sensitivity of 6 months later. The receivable is valued at face value, with a sensitivity discounted at the cash interest rate.
- The treaty interaction with the Netherlands is **not verified**.

**India account and Dutch tax.** The India account's value is also household wealth for Box 3. Its result after Indian capital-gains tax is **not** the owner's complete personal after-tax result; the India–Netherlands treaty interaction is unverified. Every India after-tax figure carries the label "after Indian tax only; Dutch tax and treaty relief not included" unless the registered scenario below adds them.

**The registered governing scenario for S2 and S3 (Section 8.7)**, fixed now so that it cannot be chosen after seeing results:
- **US account:** Box 3 deemed regime per calendar year, savings-account counterfactual, 2026 rates for 2026 and the **high end** of the published range (7.78%) for later years until officially set, i.e. the less favourable plausible case for a policy holding shares on 1 January; counter-evidence scenario C0.
- **India account:** Indian STCG at 20.8% with the deductibility defaults of Section 4.5, per financial year, loss carry-forward valued at 0, withholding scenario W1; **plus** the Box 3 deemed marginal effect of the account's 1 January mix against the savings counterfactual, with **no** treaty relief (conservative).
- Every other scenario is reported beside it and labelled "sensitivity".
- **Both directions are flagged.** A success that holds only under a sensitivity is labelled "depends on the tax scenario". A success under the governing scenario that **fails** under any registered sensitivity is reported in the headline as: "**Meets the economic target under the registered tax assumption; fails under the <name> sensitivity.**" Pre-declaring a scenario prevents choosing it after the results; it does not make it accurate.

**The owner's tax adviser decides what actually applies.**

### 4.9 Risk rules

- At most 3 positions; at most 2 per sector (the sector in `company_meta`).
- **Results blackout:** no new entry from the day before a company's results until the day after (`days_to_earnings`).
- **Loss brake:**
  - triggered when marked-to-market equity falls ≥ 10% below its running peak;
  - **pauses new entries only**; open positions follow their exits;
  - it is a pause, **not a loss cap**;
  - restart: **rehearsal account** only after the owner's real approval in Slack or the app, with a short drawdown review. **Policy accounts** use an **assumed approval scenario**: restart after 5 sessions, labelled as an assumption. Sensitivity: restart after 10 sessions, and never.
- **Gap risk** is shown per position (reported, not prevented).

---

## 5. Operating costs, the budget ceiling and the AI comparison

### 5.1 Tracking

- Every run records its model usage cost per component (news analyst, claim checker, each AI trader, forecaster, reflector, EOD analyst, research director, results analyst, deviation explainer, and the routine session itself) in `operating_costs`.
- A monthly **operating-cost report** is produced per market and component.
- **Billing basis (open item):** the tracker records token usage and its list-price value. Whether the owner pays per token (API) or a flat subscription covers the routine sessions decides what the **actual bill** is. Until it is confirmed, both are shown (per-token value and subscription view).
- **Estimate before any change:** about $8 per pre-open run, about $330/month for two markets before other runs. The tracker replaces these estimates with measurements.
- **Scale:** combined funded capital is about $6,500. **$250/month is about 3.8% of capital per month**: a ceiling, not a target.
- **Conclusion conditional on the billing basis:**
  - per-token API billing: each run is a direct extra bill, and at about 3.8% of capital per month in the worst case the system is very unlikely to pay for itself;
  - an existing subscription the owner pays anyway: a run may add no extra cash cost;
  - a subscription taken only for this tool: its fee is a deployment cost.
  - Token usage valued at list prices is shown for information. It is **not** treated as money paid unless the billing basis says so.

### 5.2 Two economic views

**1. Deployment economics, per policy.** Each policy is charged, as if deployed alone, the full cost of every component it needs:

| Policy | Components charged | Note |
|---|---|---|
| `acct.cash.v1` | the account plan's fee (Section 9.3) | — |
| `acct.simple.v1`, `acct.noai.v1` | data (free) | **assumed** runnable as plain scheduled scripts without an LLM session |
| `acct.rule.v1` | news analyst + claim checker + their share of the routine session | the rule strategies need AI-scored news |
| `acct.news.v1` | news analyst + claim checker + their share of the routine session | model + AI-scored news, no AI trader |
| `acct.ai.v1` | the above + `ai.combined.sonnet.v1` | the trader reads verified news and the model score |
| US trading policies | + the BUX Plus fee (€2.99/month) | each deployed US account would pay it |

**2. The owner's total economic outcome.** The trading results of the account the owner actually follows (the rehearsal account), minus the **actual** bills, each counted **once**.

**Reconciliation:** a table shows that the per-component costs add up to the actual bill. Shared components appear once in the total view, and in full in each deployment view that needs them.

**Accrual of operating costs.** Per-token usage is charged on the day of the run that used it. A subscription fee (when the billing basis says it is a deployment cost) and the BUX plan fee accrue **daily, pro rata** over their month. Accruals enter equity daily, so the paired daily differences include them on the days they arise.

**One cost deduction only.** Every policy's money kept is **already net of its own deployment costs**. Comparisons subtract one policy's net result from the other's, so a cost difference is deducted exactly **once**. No hypothesis subtracts a cost again (fixture B.16).

### 5.3 Whole-system budget ceiling

The ceiling covers **every paid component**, not only the AI traders. Spend to date plus committed spend for the month is checked before each paid step.

| Projected month spend | Action |
|---|---|
| ≥ 70% of $250 | Opus work stops (forecaster/Opus trader on event days, research director); Slack note |
| ≥ 85% | AI traders pause (`acct.ai.v1` records missing calls as reliability failures) |
| ≥ 95% | news analyst and claim checker pause. **Registered degraded behaviour:** unscored news gives a zero news shift, so the rule strategies act as model-only that day. The days are flagged `degraded_news` and reported. |
| 100% | only steps that need no paid model run (prices, ranges, model scores, settlement, accounts) |

**Honest limit:** today even deterministic steps run inside an LLM routine session. If that session's own cost is billed per token, the ceiling can be **guaranteed** only after those steps also run as plain scheduled scripts (a B17 item). Until then the guard reports the floor cost that it cannot switch off.

The ceiling tiers and the degraded behaviour are part of every registered policy's definition (Section 8.10).

**Shared-budget disclosure.** The budget is shared by every experiment. A policy can be paused because **other** work used the budget. Its results therefore measure performance **inside the shared research programme**, which may differ from running that policy alone. Every report shows, per policy, the days it was degraded or paused and which components used the budget.

### 5.4 Routine change (owner decision; built by B17 / B3, judged before use)

| Work | Frequency | Model |
|---|---|---|
| Deterministic work: prices, ranges, model scores, rule strategies, accounts, settlement | daily | none |
| News analyst and claim checker | daily, **frozen** during the registered window | Sonnet (unchanged) |
| AI traders | daily | Sonnet |
| Forecaster / Opus combined trader, research director, deep event readers | event days and weekly | Opus |
| Budget guard | Section 5.3 | — |

### 5.5 The 4-week AI cost study

The first 4 weeks after the routine change are a **workflow and cost study**, which is descriptive. It covers:
- measured cost per component;
- missed or failed AI calls;
- how often the AI changes decisions compared with `acct.noai.v1`;
- days in degraded mode.

---

## 6. Data and audit model

Proposed append-only kinds; names are proposals for the builder.

| Kind | One row per | Key fields |
|---|---|---|
| `account_decisions` | candidate considered per account per session | account, policy version, info cut-off, input snapshot ids, decision (order / skip + reason), L, quantity, reservations |
| `account_order_events` | event in an order's life | order id, type (`instruction_issued`, `owner_ack`, `ack_missed`, `assumed_fill_open`, `assumed_fill_intraday`, `unfilled`, `rejected`, `exit_not_executed`), timestamp, provenance |
| `account_fills` | assumed fill | price, quantity, fill type, price source, FX observation id, sensitivity variant |
| `account_cash_ledger` | cash movement | amount, currency, reason (fill, fee, reservation, release, monthly fee, FX conversion, interest, **TDS withheld → credit receivable**, **TDS settlement**), charging unit, tax-deductible flag |
| `account_equity_daily` | account per close | cash, reserved, positions marked, liquidation value, equity, peak, drawdown, brake state |
| `account_tax_periods` | account × tax period | jurisdiction, period, taxable gain, deductible and non-deductible costs, tax scenario, tax, attributed share per window |
| `operating_costs` | component × run | component, run id, model, tokens, list-price cost, billing basis, market, budget tier, timestamp |
| `experiment_registry` | registered evaluation | the fields of Section 8.4, plan SHA-256, Slack receipt timestamp |
| `registered_deviations` | change to a frozen input | file or setting, old/new hash, reason, timestamp, affected policies, decision |
| `evaluation_results` | evaluation report | label (Section 8.9), estimates, intervals, α used, validity-check results, scope note |

**Rules:**
- Append-only. Corrections are new rows. A later event never erases an earlier one.
- Every number carries a provenance tag:
  - **observed**: a published market price;
  - **simulated**: a proxy draw;
  - **assumed**: a fill rule, fee rate, interest rate, attendance, approval or tax scenario;
  - **derived**: computed from the others. Account profit is always derived.
- Every decision references the information that existed at its cut-off. No look-ahead.

---

## 7. Scoreboards

Per market, with sample size and effective sample size on every row.

### 7.1 Forecast scoreboard

Every forecast is scored **on the event it was issued for**, and never re-scored against a fill:

| Forecast | Scored against | Measures |
|---|---|---|
| P(up) | X > O_D (the model's label) | Brier score, log loss, reliability with Wilson intervals; also split by fill type (descriptive) |
| Expected price | the official close of N+k | mean absolute % error and RMSE, paired against no-change |
| 80% range | the close of N+k (close-anchored) | coverage, width, interval score |

Evening and morning revisions are separate forecast records, scored separately.

### 7.2 Decision scoreboard

The net outcome of each buy, skip, hold and exit choice against its alternative. Also: a fill-type breakdown and missed acknowledgements (rehearsal only). Compared with cash and the simple rule.

### 7.3 Account scoreboard

Money kept (EUR / INR):
- before tax;
- after tax per tax period and attributed to the window;
- in both economic views.

Also: return on funded capital, maximum drawdown, exposure, turnover, costs by unit and by deductibility, interest, TDS withheld, unused cash, and degraded days.

**Reported, not tested:** buy-and-hold of the market index in the account currency (Nifty 50 in INR; S&P 500 in EUR), labelled as an index proxy, because an EU retail investor cannot buy US-domiciled ETFs.

### 7.4 Uncertainty

- **Candidates:**
  - a HAC (Newey–West) interval with an **automatic bandwidth** (Andrews), not a fixed lag;
  - a **stationary block bootstrap** with automatic block length (Politis–White).
- The primary method is chosen from a **finite, pre-declared set**, on one set of placebo experiments, and **verified on a separate set** (Section 8.5). If verification fails, the results stay **descriptive**.
- Position-days are never treated as independent observations.

---

## 8. Evaluation protocol

### 8.1 What is fixed now, and what is fixed at registration

**Fixed by this plan (now):**
- the policies and their wrappers (Section 9.3);
- the hypotheses (8.6);
- the success conditions (8.7);
- the label wording (8.9);
- the freeze guard (8.10);
- **the procedure** that sets the numbers below.

**Fixed at registration, after step 3:**
- each hypothesis's window length;
- the primary inference method, **or the finding that no tested method is adequate** (results then stay descriptive);
- the power statement.

The multiplicity procedure is **not** chosen at registration: **Bonferroni at α = 0.01 one-sided per hypothesis is fixed now** for this first registration (Section 8.6).

**Forward data before registration.** Forward results from 12 Oct onwards **will be visible** before registration: the live system already reports them, and the step-3 account report shows the policy accounts from 12 Oct for ledger checking. They cannot be hidden, so the protection is:
- **the choices that matter are fixed now, in this document**: the policies and their wrappers, the comparators, the hypotheses, the multiplicity procedure, the label rules, and the **rules** that set window lengths, the inference method (or "none adequate") and the FX buffer;
- those rules are applied by a **fixed, deterministic procedure using only data dated up to 9 Oct 2026 and simulations**; no registration number takes any forward outcome as input; the code and its inputs are recorded with the latest data date they read;
- **disclosure:** the registration record lists the exploratory forward outcomes already observed at registration time (per policy and market), so a reader can see what was known;
- forward data before the registration time is **never** confirmatory, and each window starts after registration (§8.3).
ChatGPT's and the judge's review of the registration record checks that it follows these rules; it does not choose any number.

### 8.2 Power analysis (step 3, before registration)

For each hypothesis, the quantity that matters is **σ_d, the daily standard deviation of that comparison's paired difference**, together with its dependence:

> Var(A − B) = Var(A) + Var(B) − 2 Cov(A, B)

**Estimation:**
- **H1 (vs cash):** cash has almost no variance, so σ_d ≈ the account's own daily σ.
  - σ_d depends on **how** exposure is spread over time, not only on its average. With daily exposure e_t, and e_t independent of returns, σ_d ≈ σ_portfolio × √E[e_t²]. Constant 10% exposure gives 0.10 × σ; full exposure on 10% of days gives √0.10 ≈ 0.32 × σ.
  - It is estimated from the replay's actual exposure series of `acct.noai.v1` and `acct.simple.v1`, and from the rule strategies' model part. For `acct.rule.v1` itself there is no faithful history, so its figure is a **labelled surrogate scenario**.
- **H2 (vs simple rule):** estimated from the replay of both arms on the same dates, including how often they **pick the same stocks** (likely in a 20-company universe). The disjoint-portfolio figure below is one scenario only.
- **H3 (AI vs no-AI):** there is no historical AI output, so σ_d is set from scenarios. The low end assumes the two arms hold mostly the same stocks; the high end assumes independent selections. The scenarios are stated explicitly.

**Reported per hypothesis:**
1. the power to detect a **true** advantage of 0.5% per month (test against 0);
2. the probability of **establishing** an advantage above 0.5% per month (lower bound ≥ 0.5%) when the true advantage is 1% per month;

each at 126, 189 and 250 sessions, under the dependence measured in the replay.

**Illustrative figures now** (formula MDA = 21 × σ_d ÷ √n × (z₁₋α + z₀.₈), n = 250, **α = 0.01 one-sided, the registered per-hypothesis level** (Section 8.6), independent observations; dependence can raise all figures):

| σ_d | Detectable advantage at 250 sessions (80% power) | Sessions needed to detect a true 0.5% |
|---|---|---|
| 0.10% | 0.42% | 178 |
| 0.127% | 0.53% | 286 |
| 0.20% | 0.84% | 709 |
| 0.40% | 1.68% | 2,833 |
| 0.80% | 3.37% | 11,331 |

**Rough stored-data inputs (Oct 2024 – Oct 2026, 2,000 random draws):**

| | 3-stock equal-weight portfolio, daily σ | Difference of two disjoint 3-stock portfolios, daily σ | Correlation between the two |
|---|---|---|---|
| India | 1.09% | 1.07% | 0.52 |
| US | 1.48% | 1.58% | 0.45 |

**[CHANGED IN v16]** Reconciled and published. **Canonical method:** the market's 20 watchlist companies; `bars` view, 1 Oct 2024 – 9 Oct 2026; the **session panel** = the dates on which every one of the 20 has a stored close; daily simple returns between consecutive panel dates; 2,000 random draws (NumPy seed 0) of two disjoint 3-stock equal-weight portfolios; **mean** over draws. The script and its output are in **Appendix E** (and will be committed as `docs/plan_volatility.py`).

**Why the earlier figures differed:** the stored India `bars` contain **526 dates, of which only 498 have a close for all 20 companies**. The other 28 dates carry bars for only some companies. The judge's script kept them, so returns next to those dates became missing and were dropped, giving India 1.0638% / 1.0507% / 0.517. Dropping the partial dates first (the session panel) gives **1.0866% / 1.0696% / 0.5208**, within 0.002 percentage points of ChatGPT's independent 1.0875% / 1.0668% / 0.5227. For the US (507 dates, 504 complete) the session panel gives 1.4806% / 1.5779% / 0.4495; ChatGPT's US figures (1.4653% / 1.5728% / 0.4484) are close but not identical, and that remaining difference, presumably its session filter, is listed for reconciliation when the reviewers run the published script. The figures are scenarios only, and nothing in the protocol depends on their third decimal. Complete coverage refers to this period only, not to history back to 2011.

**What these suggest, and what they do not:**
- They are **scenarios**, not measurements of the actual policies.
- Under the higher-variability scenarios, one year has poor power for a small advantage. For H1 these scenarios are the relevant ones whenever the account is invested much of the time. Under this section's approximation (250 independent sessions, α = 0.01 one-sided, 80% power, a true 0.5% per month), the largest daily paired σ_d that still detects the advantage is about **0.119%**. With the portfolio σ above and **constant** exposure e (σ_d ≈ e × σ_portfolio), that means e ≤ about **10.9% (India)** and **8.0% (US)** **[CHANGED IN v16]** (0.1188 ÷ 1.0866 and 0.1188 ÷ 1.4806, from the canonical session-panel figures). These are illustrative limits under those assumptions, **not** recommended allocations; irregular exposure and dependence require the actual replay analysis. For H2 the answer depends on how much the arms overlap, which is unknown.
- They say nothing reliable about H3.
- Every hypothesis gets its own power analysis in step 3, from replayed series or from labelled surrogate scenarios.

### 8.3 Windows, registration and proof

- **Policy accounts, once built, are computed forward from the pre-open decisions recorded since 12 Oct 2026.** Data before the registration time is labelled **"pre-registration, exploratory"** and is never part of a confirmatory test.
- **Window length per hypothesis** (rule fixed now, applied at registration):
  - the shortest of 126, 189 or 250 sessions at which the step-3 analysis gives **≥ 80% power** for a true 0.5%/month advantage under the central scenario;
  - if none reaches it, **250 sessions**, with the low power stated in the registration and in every report.
  - Each end date is fixed and never extended.
- **Registration** = the registration record (window lengths, method, α split, power statement), committed to the repository.
  - Its SHA-256 is posted by the project's Slack bot to #market-brief. **The Slack server timestamp is the registration time.**
  - GitHub's server-side push time is a second record. Git commit dates alone are not proof, because they can be set by hand.
- **Window start:** the first session (per market) after the registration time. It is never back-dated.

### 8.4 Registration fields

- candidate policy and version, with its wrapper parameters;
- primary comparator; secondary comparators;
- the before-tax test measure and the after-tax economic measure;
- minimum economic improvement;
- window start rule and **fixed end date**;
- primary inference method and its validity-check results;
- α allocated;
- harm rule;
- frozen inputs and what creates a new version;
- the latest data date the registration analysis read.

### 8.5 Validity check of the inference method (step 3)

Naming a method does not validate it, and tuning a method until it passes does not validate it either. The procedure is:

1. **A finite candidate set, declared now:**
   - (a) HAC, Andrews automatic bandwidth;
   - (b) HAC, bandwidth ⌊4 (n/100)^(2/9)⌋;
   - (c) stationary bootstrap, Politis–White automatic block length;
   - (d) stationary bootstrap, twice that block length;
   - (e) circular block bootstrap, block 10;
   - (f) circular block bootstrap, block 20.

   Nothing outside this set is tried.
2. **Placebo and synthetic experiments, split in two by time:**
   - experiments are assigned by their **full observation span**, not their start date: the **selection set** uses windows lying entirely within 3 Jan 2011 – 29 Jun 2018; the **verification set** uses windows lying entirely within 2 Jan 2019 – 9 Oct 2026. The six-month gap between them means no session, and no position open across the boundary, belongs to both.
   - The two sets use **distinct random seeds** (selection: seeds 1–9,999; verification: 10,001–19,999). The seeds are recorded.
   - Placebo pairs have no edge by construction: two random selections from the same candidates, under the same wrapper, constraints, brake and costs.
   - **Power experiments** add a known edge δ (0.5% and 1% per month) to one arm of a placebo pair.
3. **Selection** (selection set only): among the candidates whose rejection rate at the registered α is ≤ α + 2 Monte Carlo standard errors, pick the one with the **highest power** at δ = 1%/month. A method that rejects almost nothing is therefore not preferred merely for being safe.
4. **Verification** (verification set only, run once): the selected method must again show a rejection rate ≤ α + 2 Monte Carlo standard errors, with its power reported.
5. **Allowed outcome: "no tested method is adequately supported".** If no candidate passes selection, or the selected one fails verification, nothing is enlarged or re-tuned. The registered hypotheses are then reported **descriptively only**, with estimates and intervals, and **no confirmatory label** is given.
6. **Reported in every case:** each candidate's rejection rates and power on both sets, with Monte Carlo standard errors, and the number of experiments.

**Limits stated in advance:**
- Historical random-pair placebos represent comparisons **like** them. They do not automatically validate inference for AI-driven, adaptive policies with different exposure and failure patterns. The registration record says so, and H3's validity rests on the closest available surrogate (pairs whose overlap and exposure match the scenario of 8.2).
- A future process unlike the past is not covered.

### 8.6 Hypotheses (per market) and the test statistic

**The test statistic, defined exactly.** For policies A and B in one market, on session t:

> d_t = (ΔV_A,t − ΔV_B,t) ÷ C₀

- **C₀** = the initial funded capital, the **same constant** for every policy of the market (₹3,00,000; €-value of $3,000 at q₀). Dividing by a constant keeps d_t in money terms: Σ d_t × C₀ is exactly the difference in money kept. It is **not** an average of daily percentage returns, so compounding cannot distort it.
- **ΔV_X,t** = the change in policy X's **before-tax equity** from the close of t − 1 to the close of t.
- **One accounting bridge for tax** (designed so that a tax credit is never counted twice):
  - **Ledger equity** L_t = settled cash + unsettled proceeds + TDS credit receivable + other receivables (refunds, interest; at face value) + open positions at **liquidation value** − accrued unpaid operating costs and plan fees − **tax payable recognised** to date.
  - **Cumulative tax expense** T_t = all tax expense recognised to date under the governing scenario: India, the financial-year-to-date tax on the net realised gains (so a later loss in the year reduces it); Netherlands, the year's attributed Box 3 amount accrued daily pro rata.
  - **After-tax equity** = L_t. Each tax expense reduces it **exactly once**, when recognised.
  - **Before-tax equity** B_t = L_t + T_t. Adding back the cumulative expense makes the before-tax series **independent of every tax flow**: withholding, recognising the liability, applying the credit and receiving the refund all leave B_t unchanged, before and after settlement.
  - **The bridge changes reporting, not trading.** Withholding, temporary blocks and refunds still reduce the cash **available for trading** under §4.2 and §4.8 until released, so they can change which later trades happen and therefore later profits. The simulator keeps those restrictions; only the equity measures above are made independent of tax flows.
  - **Tax flows only move between ledger lines:** withholding moves cash to the credit receivable; recognition creates tax payable (and raises T_t); applying the credit cancels the payable against the receivable; any excess becomes a refund receivable; the refund moves it back to cash.
  - Worked chain (fixture B.35): before-tax assets ₹10,000; ₹1,000 withheld → cash ₹9,000 + credit ₹1,000 (L = B = ₹10,000); liability ₹600 recognised → L = ₹9,400, T = ₹600, B = ₹10,000; credit applied → payable 0, refund receivable ₹400 (L = ₹9,400, B = ₹10,000); refund received → cash ₹9,400, nothing receivable (L = ₹9,400, B = ₹10,000). After-tax: ₹9,400, one ₹600 expense; never ₹10,400 and never ₹8,800.
- **Liquidation value** of an open position = the official close (US: converted at the day's mark rate) − the estimated exit costs it would pay if sold: broker and order fees, STT, exchange fees with GST, DP charge, the date charge if no other sale that date carries it, and for the US the FX markup on conversion back to euros.
- **Monthly advantage** = 21 × mean(d_t) over the window, as a share of C₀.
- **At the fixed end date**, open positions stay at liquidation value; nothing is assumed sold at a better price.
- **Two after-tax end figures, and which governs.**
  - **Marked after-tax wealth** = L_end: open positions at liquidation value, tax only as recognised on realised gains.
  - **Estimated money remaining upon liquidation** = L_end − ΔTax_liq, where ΔTax_liq is the **extra tax that a hypothetical sale of every open position at the end date would cause**. It is computed **at account level**: all open positions sold together on the end date, the date charge counted once, and the hypothetical gains and losses combined with the financial year's realised results in the same tax computation. ΔTax_liq = tax(realised + hypothetical) − tax(realised). It is **not** a percentage applied position by position. Box 3 does not change: a sale on the end date does not alter any 1 January position, so the attribution rule of Section 4.8 is unchanged.
  - **S2 and S3 use the estimated money remaining upon liquidation**, for the candidate and the comparator alike, because the objective is money kept after all deductions. Marked after-tax wealth is reported beside it.
  - The **test statistic** stays before tax: positions at liquidation value net of exit costs, without hypothetical tax.


| # | Hypothesis | Primary comparator | Test measure: daily paired difference **before tax**, each side **net of its own deployment costs** |
|---|---|---|---|
| H1 | `acct.rule.v1` makes more than cash | `acct.cash.v1` | rule − cash > 0 |
| H2 | `acct.rule.v1` beats the simple rule | `acct.simple.v1` | rule − simple > 0 |
| H3 | **the complete AI-assisted pipeline** (AI-scored news + claim checking + the Sonnet trader) beats the **model-only** pipeline after each side's deployment costs | `acct.noai.v1` | ai − noai > 0. No further cost is subtracted: each side's costs are already inside its result |

- **H3 does not isolate the Sonnet trader.** A positive H3 supports only "the complete AI-assisted pipeline outperformed the model-only pipeline after costs". Where the benefit comes from is studied by an **exploratory decomposition** on the same dates and wrapper:
  - `acct.news.v1` − `acct.noai.v1` = the contribution of AI-scored news;
  - `acct.ai.v1` − `acct.news.v1` = the contribution of the Sonnet trader on top of AI-scored news.
  - Both are labelled exploratory. They are never presented as confirmed.
- **Multiplicity: Bonferroni per hypothesis**, replacing Holm. Each hypothesis is tested **once, at its own fixed end**, at **α_h = 0.01 one-sided** (each market's 0.03 split equally over H1–H3). Reasons:
  - the hypotheses may have different window lengths (Section 8.3), so a joint Holm decision would have to wait for the longest window; separate allocation lets each result stand at its own end without that wait;
  - simplicity: one fixed level per hypothesis, also used for its lower bound.
  - **Bonferroni is retained for this first registration; there is no switch to Holm.** The power cost is real: at a family allocation of 0.03, p-values of 0.005, 0.014 and 0.025 would all pass Holm, but only the first passes Bonferroni at 0.01. Step 3 measures and reports that cost **for information only**. Any later registration that adopts Holm must specify its joint decision timing and the confidence-bound procedure used for labels, because changing the rejection rule does not supply the bounds.
- **Lower bounds at the same level.** Every lower confidence bound used for a label is **one-sided at level α_h = 0.01** (a 99% one-sided bound), never an ordinary 95% interval.
- **Stopped hypotheses keep their share.** A hypothesis stopped for harm counts as **not rejected**. Its α share is **not** passed to the others.
- **α budget for the year (one-sided):**
  - **0.03 per market** for this registration (0.06 in total);
  - **0.04 held in reserve** for challengers registered later in the same 12 months, each with a pre-declared share.
  - The total is 0.10.
- **India note, stated in advance:** `acct.noai.v1` India will rarely trade (degenerate model), so H3 India is close to "AI-assisted pipeline vs cash".

### 8.7 Success conditions

At each hypothesis's fixed end:

| # | Condition | Nature |
|---|---|---|
| S1 | the before-tax test rejects at α_h = 0.01 one-sided (Section 8.6) | **statistical evidence**, labelled "before tax" |
| S2 | the **after-tax** advantage over the primary comparator (each side's tax computed per Section 4.8, attributed to the window) is ≥ **0.5% of funded capital per month** | economic, point estimate |
| S3 | the candidate's own money kept **after all deductions and tax is > 0** | absolute |

- **Labels (8.9):**
  - "**Positive before-tax advantage supported; after-tax estimate meets target**" needs S1 + S2 + S3.
  - "**Before-tax minimum supported; after-tax estimate meets target**" additionally needs the before-tax **one-sided 99% lower bound** (level α_h) ≥ 0.5%/month.
  - **No label claims an after-tax minimum is established.** This protocol does not construct an after-tax interval: tax is annual and non-linear, so a suitable interval would need a dedicated method, which is not part of this design. That is a limitation of this protocol, not a mathematical impossibility.
- **Reported beside every label:** a **conditional after-tax lower bound** = the before-tax lower bound − the largest attributed tax difference (candidate − comparator) across the registered tax scenarios. It is labelled "conditional on the realised tax difference; not a full inference". With ChatGPT's example (before-tax lower bound 0.60%, tax difference 0.30%), it shows **0.30%**, and the label is the before-tax one.
- **Promotion of a later challenger:** primary comparator = the incumbent, with the same S1–S3. **The owner approves every promotion.**

### 8.8 Interim reports and harm stops

- **No efficacy decision before the fixed end.** Reports about every 8 weeks are **descriptive**, labelled "**interim, not a conclusion**".
- **Harm stop (risk control, not an efficacy test):** a policy stops if its before-tax paired difference against its primary comparator is below −2% of capital per month with one-sided p < 0.01 at a report, **or** its account drawdown exceeds 20%.
  - A harm stop can only end a policy early. It never declares success, so it does not inflate the false-positive rate of S1.
  - A stopped policy is labelled "Stopped for harm", is not tested at the end, and counts as **not rejected** in its market's family.

### 8.9 Result labels and bounded wording

**Exactly one label per hypothesis, chosen in this order of precedence:** (1) Stopped for harm; (2) Descriptive only; (3) Before-tax minimum supported; after-tax estimate meets target; (4) Positive before-tax advantage supported; after-tax estimate meets target; (5) Inconclusive: insufficient evidence (S1 not met **and** the registered power was below 80%); (6) Failed the success conditions (every other case). Neither (5) nor (6) shows that the policy can never work.

| Label | Condition | Mandatory qualifier |
|---|---|---|
| Before-tax minimum supported; after-tax estimate meets target | Section 8.7 | "before tax only, for this registered comparison, evaluation period and set of assumptions; the after-tax minimum is **not** established (conditional after-tax lower bound shown); not a promise of future returns" |
| Positive before-tax advantage supported; after-tax estimate meets target | S1 + S2 + S3 | "the minimum worthwhile improvement is not established; the statistical evidence is before tax" |
| Failed the success conditions | S1, S2 or S3 not met, with the test valid, and not Inconclusive | "does not show the policy can never work" |
| Inconclusive: insufficient evidence | S1 not met and the registered power was below 80% | "the comparison could not distinguish the policies with this amount of data" |
| Descriptive only | no inference method passed selection and verification (8.5) | "no tested statistical method is adequately supported for this comparison; estimates are shown without a test" |
| Stopped for harm | Section 8.8 | — |

### 8.10 Freeze guard

During a registered window, the following are **frozen inputs** of the registered policies:
A policy is its **complete decision process**. **[CHANGED IN v16]** **The paths below are a starting inventory, not a claim of completeness** (every listed path exists on `origin/main`). Completeness is **enforced** by the rule after the list:
- code, model: `scripts/marketbrief/model/` (whole package);
- code, strategies, picks and their costs: `lab/strategies.py`, `lab/predict_inputs.py`, `lab/picks.py`, `lab/gain.py`, `lab/costs.py`, `lab/cost_views.py`, `lab/sizing.py`, `lab/settle.py`, `lab/scoreboard.py` (its settled results feed the picks' "strongest strategy" ranking);
- code, ranges and their inputs: `analytics/range_math.py`, `range_row.py`, `range_context.py`, `range_publication.py`, `range_switches.py`, `adaptive_conformal.py`, `event_history.py`, `earnings_reaction.py`, `index_cue.py`, `implied_volatility.py`, `relation_flags.py`, `smart_money.py`;
- code, AI trader inputs and gate: `scripts/marketbrief/traders/` (whole package, including `prepare.py` with its section filter, `inputs.py`, `input_parts.py`, `gate.py`, `gate_evidence.py`);
- code, the accounting built in steps 1–3 (ledger, wrappers, evaluation): hashed **at registration**, after the build and its corrections;
- config: `config/model.yaml`, `config/strategies.yaml`, `config/ranges.yaml`, `config/costs.yaml`, `config/news_sources.yaml` (claims section). Cost scenarios added or corrected **before** registration are permitted; the snapshot is taken at registration;
- agent instructions: `.claude/agents/news-analyst.md`, `claim-checker.md`, `trader-combined.md` (prompt_version, model, schedule);
- **[CHANGED IN v16]** further dependencies found on inspection, added to the inventory: `analytics/features.py` and `analytics/regime.py` (indicators and the regime, which drive regime filters and eligibility); `core/calendar.py` (sessions and timing); `config/markets/india.yaml` and `config/markets/us.yaml` (calendar, sectors and sector assignment, regime thresholds); `pipeline/evidence_status.py` and `pipeline/forecast_gate.py`, `analytics/prediction_rules.py`, `model/forecast_rules.py` and `model/news_score.py` (imported by the trader and strategy code); `pipeline/context.py` and the context-pack sections that the trader's input filter keeps; `contracts/` and `portfolio/horizons.py` (imported by the strategy code); `sql/views.sql` (the views the decisions read).
- **[CHANGED IN v16]** **Enforced completeness (required before registration):**
  1. **Functional manifest.** The registration manifest is generated, not hand-written: it is the transitive closure of the Python modules imported by the decision and accounting entry points (pre-open strategy predictions and picks, trader preparation and gate, features and regime, model scores, ranges, the context pack, the account ledger and wrappers), **plus** every config, SQL view and agent-instruction file those modules read at run time (recorded by tracing file reads during a full replay of one session). Each entry is hashed.
  2. **Detection test.** Before registration it is demonstrated that a change to an **upstream regime threshold**, a **sector assignment** and a **calendar rule** each (a) changes at least one decision or account figure in a replayed session and (b) is caught by the freeze guard. A change the guard does not catch is a manifest gap and blocks registration.
  3. The judge checks the generated manifest and the detection test as part of the registration review. File existence alone is never accepted as evidence of completeness.
- the budget-guard tiers and degraded behaviour (Section 5.3).

Rules:
- A test records the hashes at registration and fails when one changes without a `registered_deviations` row.
- A deviation is allowed only for a correctness bug, recorded with its reason; the report shows results before and after it.
- A deliberate change creates a **new version** with its own window.
- **Update rules are part of the policy and keep running:** the monthly model refit, the pick's "strongest strategy" ranking, and `model_news_update` if it is applied.
- **Not applied during the window:** weekly-review or research-director proposals that touch frozen inputs.
- **Unaffected:** the Opus schedule change, the evening run and morning revisions, because no registered policy reads them.
- **Before registration** (from 12 Oct until the registration time), the same inputs are kept unchanged as far as possible. Any change is logged, so the exploratory period is interpretable.

---

## 9. The baseline and the account policies

### 9.1 `baseline.v1`

The live upstream system as switched on for 12 Oct 2026 (go-live content commit `d5eb82c`, merged by `d5c8a27e`), **unchanged**, including the quantities of Section 2.3 exactly as computed.

### 9.2 Withdrawn: the v6 "reference fix"

Changing a reference inside a calculation does not turn P(X > O_D) into P(X > L), and every honest remedy is a forecasting change. The coherent quantity, the value of an order, is built in step 4a (Section 11.1).

The "honest no-signal" rule is split in two:
- **display only, any time:** when a market × horizon Platt slope is ≈ 0, the owner sees "**No clear signal**" instead of a constant percentage;
- **decision change:** registered later as a **challenger** (`acct.rule.v1_1`) with its own window.

### 9.3 Account policies (wrappers)

**Shared elements of every trading policy:**

| Element | Rule |
|---|---|
| Limit | L = previous close × 1.005 |
| Duplicates | one position per ticker; a ticker already held, or with an open order, is skipped (`already_held`) |
| Allocation | free slots = 3 − open positions − open orders; candidates in ranking order; sector cap 2; results blackout; loss brake; free cash (TDS withheld after a sale reduces it) |
| Ties | higher score, then shorter horizon, then ticker alphabetical |
| Exit | the chosen horizon's N+k session, with the chains of Section 4.4 |
| Budget | the tiers and degraded behaviour of Section 5.3 |

**Per policy:**

| Policy | Candidate source | Horizon | Cost gate | Ranking |
|---|---|---|---|---|
| `acct.rule.v1` | `head_to_head_picks` with family = rule, pick_rule = best expected gain, status `picked` | the pick's `horizon_days` | g = p × move − (1 − p) × loss − c_new > 0, with the pick's stored `prob_up`, `move_pct`, `loss_pct`; c_new = the round-trip cost under the new cost scenario at quantity and L | g ÷ k |
| `acct.ai.v1` | qualifying `strategy_predictions` of `ai.combined.sonnet.v1` only; per ticker, the horizon in {1, 3, 5} with the highest g ÷ k (same formula as the pick's horizon table) | chosen as described | same gate | g ÷ k |
| `acct.noai.v1` | qualifying `strategy_predictions` of `base.model_only`, horizons restricted to {1, 3, 5} | as for `acct.ai.v1` | same gate | g ÷ k |
| `acct.news.v1` (exploratory) | qualifying `strategy_predictions` of `rule.model_news.v1` (model + AI-scored news, weight 1.0), horizons restricted to {1, 3, 5} | as for `acct.ai.v1` | same gate | g ÷ k |
| `acct.simple.v1` | active companies with 20-session momentum > 0, top 3 | N+5 | none | momentum |
| `acct.cash.v1` | none | — | — | — |

**`acct.cash.v1`, the cash comparator:** money left in **the same broker account, uninvested, under that account's real conditions**.
- **US:** BUX Plus cash at the Plus rate (dated parameter, default 1.50%) **minus the €2.99 monthly fee**. At €2,727 that fee is about 1.3% a year, so this comparator earns little. That is the real cost of keeping the money in the same account.
- **India:** the broker account's idle-cash rate (owner parameter, default 0%).
- **Exploratory alternatives (reported, not tested):** BUX Basic cash (0% interest, no fee), and a named savings account with its real terms once the owner provides them.

The `acct.simple.v1` horizon is N+5 because costs are paid per round trip, so the longest horizon gives the lowest cost drag; that makes it the harder comparator to beat. The 15-year backtest file, which includes momentum baselines, has been seen, so N+1 and N+3 are reported as exploratory.

**AI arm specifics:**
- **AI says "no trade"** (`abstained`, `earnings_window`, `blocked_quality`): **no trade**. It is never replaced.
- **Missing or failed AI call** (no row; `gate_failed`, `timeout`, `killed`, budget pause): **no trade**, counted as a **reliability failure**.
- Exploratory variant "fill the gap with `acct.noai.v1`": reported, never tested.

**Labels shown with results:**
- `acct.rule.v1` = "rule family (uses AI-scored news)";
- `acct.ai.v1` = "AI decision layer (Sonnet combined trader)";
- `acct.noai.v1` = "model only, no AI";
- `acct.news.v1` = "model + AI-scored news, no AI trader (exploratory)".

### 9.4 Retrospective replay

- From 2011 to 9 Oct 2026, labelled **development / retrospective**. Only policies whose inputs exist historically are replayed: `acct.simple.v1`, `acct.noai.v1`, the model part of the rule strategies, and the placebo pairs. There is no news archive, so `acct.rule.v1` and `acct.ai.v1` have no faithful history.
- US exits are approximate (Section 4.4).
- Reported with all execution, cost, interest and tax variants.
- **Its roles:**
  - test the accounting at scale;
  - supply σ_d and the dependence for the power analysis (8.2);
  - run the validity check (8.5).
- **It is never confirmatory.**

---

## 10. Build plan for steps 1–3 (starts only after design approval)

Nothing in this section starts until Claude and ChatGPT agree on this design and the owner approves it. Until then the live system keeps running unchanged, recording its pre-open decisions from 12 Oct 2026, which the policy accounts later replay.

### Step 1: accounting core

**Components:**
- account types, funding and interest (4.1, 4.2);
- the entry fill engine with variants (4.3);
- the exit chains, with time-zone and exchange-calendar deadlines and the post-close 5-minute fetch (4.4);
- costs per charging unit with deductibility flags, and named cost scenarios (4.5);
- live instructions and Done acknowledgements for the rehearsal account (4.6);
- FX timestamp rules, with EURUSD=X added to the intraday collection (4.7);
- tax per period with the funding-origin counterfactual and both Box 3 regimes; TDS as a credit receivable under scenarios W1, W2 and W3 (4.8); the tax bridge L_t / T_t / B_t and the account-level hypothetical liquidation (8.6);
- risk rules and the loss brake with the approval scenarios (4.9);
- the audit model (Section 6);
- the operating-cost tracker and the whole-system budget guard (Section 5).

**Acceptance:**
- all worked trades (Appendix A) and failure fixtures (Appendix B) implemented and passing, each with expected outcome, actual output and reconciliation to the full ledger;
- no event is ever overwritten.

### Step 2: scoreboards and protocol machinery

**Components:**
- the three scoreboards (Section 7);
- paired comparisons;
- the HAC interval with automatic bandwidth and the stationary bootstrap;
- the Bonferroni allocation with one-sided lower bounds at α_h;
- the placebo validity harness (8.5);
- the power calculator (8.2);
- the registry, deviations log and freeze guard (8.10);
- the result labels.

**Acceptance:**
- independent recomputation on a fixture matches to the cent;
- the placebo harness reproduces a known false-positive rate on a synthetic independent series (a check of the harness, not of the trading test);
- the harness enforces the selection/verification split and the finite candidate set: a test fails if a method outside the set, or the verification set, is used during selection;
- the freeze-guard test fails on an unrecorded change and passes with a deviation row.

### Step 3: policies, power, validity, registration and report

**Components:**
- the six account wrappers (9.3: five registered policies plus the exploratory `acct.news.v1`), computed over the decisions recorded since 12 Oct (exploratory) and over history (development);
- the rehearsal account from its own start;
- the power analysis (8.2) and the validity check (8.5), using data up to 9 Oct 2026 only; the outcome may be "no adequate method", in which case the record registers descriptive reporting only;
- the **registration record** (8.3–8.4), posted with its Slack receipt;
- the **account report**.

**The account report contains:**
- the full equity curve per account;
- every decision with its information cut-off;
- every order event;
- fills with type and provenance;
- cash, reservations, interest and TDS;
- costs by unit and deductibility;
- missed acknowledgements (rehearsal);
- unused cash;
- tax per period and attributed to windows;
- both economic views with their reconciliation;
- results against each comparator, including the index buy-and-hold;
- degraded days;
- the robustness table across execution, cost, interest, tax, approval and proxy variants;
- every number tagged observed / simulated / assumed / derived.

**Acceptance:**
- an independent recomputation of the full equity curve reproduces it;
- a reviewer can inspect the information at each decision, the assumption behind each fill, each deduction, and how conclusions change under each sensitivity;
- **the registration record is reviewed by ChatGPT and judged before it is posted.**

**Not in steps 1–3:** any new forecasting model, event engine, ranking change, early exit, adaptation, or change to the frozen inputs.

---

## 11. Deferred design for steps 4–6

**Status: a research outline, not a recipe.** Quantiles, tails, event clustering and adaptive weights describe machinery; they do not identify information that predicts profitable trades. Each item must show, on unseen outcomes and before it is used: (1) forecasts better than simple alternatives; (2) predicted order values that agree with realised outcomes well enough to guide decisions; (3) decisions that improve account profit after their own extra costs. Nothing here claims that accurate N+1, N+3 or N+5 predictions will result.

Built only after the step-3 report is reviewed. Each item enters as a registered challenger with its own window, and its primary comparator is the incumbent.

### 11.1 Step 4a: order-level value model

- **Decision:** "place a day limit at L, or not".
- **Target, estimated directly:** E[net outcome | information at submission, order], from realised order-level outcomes:
  - open fill;
  - intraday fill at L;
  - no fill: **value 0** in the order model. No opportunity cost is deducted in the order model. What the slot could have done instead depends on the account's actual alternatives, so it is measured only in the **account replay**, where the slot's real use is already counted. It is never deducted twice.
  
  Each outcome is followed to the executable exit, **in the account currency, after costs** (for the US: the 15:45 ET exit in EUR).
- **Also:** P(net > 0 | fill, fill type), conditional on the fill type.
- **Forbidden:** an unconditional expected return × a fill probability, because it misses adverse selection (lower limits tend to fill on days when the stock keeps falling).
- **Training labels:** 15 years of daily bars, the fill rule (4.3), and the executable exit.
- **Leakage controls:**
  - pre-submission information only;
  - all candidate limits of one stock and day form one group in time-based validation;
  - **purge and embargo follow each label's actual information-to-outcome span**: from the submission cut-off to the **last** session the outcome can reach, including the fallback exits (next-open fallback, re-attempts after "exit not executed"). The purge length = the longest such span in the training labels + 1 session; the embargo is the same length. A fixed 5 sessions is not used;
  - the limit grid is fixed in development;
  - quantity is fixed at submission;
  - order value ranks candidates only, and the account replay decides.
- **Evidence before registration:**
  1. an adverse-selection table on held-out data (intraday-filled vs open-filled outcomes);
  2. calibration of predicted order value by decile on held-out data. **This** is the evidence about the learned model;
  3. a synthetic fixture in which fill and later return are correlated by construction. It shows that the implementation handles that **known case** correctly, and that the product construction is biased there. It does **not** prove the learned model is unbiased in general.
- **No claim** that a lower L is better.

### 11.2 Step 4b: return distribution

- Log-returns. Central quantiles 5–95% in 5% steps, with monotone interpolation.
- **Tails:** exponential beyond the 5% and 95% quantiles, each with exactly 5% mass and a continuous CDF.
  - **Upper rate β > 2 required**, so E[e^R] and E[e^{2R}] are finite.
  - Fits with β ≤ 2 are rejected.
  - Fitted β is reported with confidence intervals, plus a β-sensitivity table.
- **Benchmark:** a mixture of 2–3 normals.
- **Validation:** exceedance rates at 1 / 2.5 / 97.5 / 99%; PIT histograms; a closed-form vs Monte Carlo moment check.
- **What the close-price distribution can and cannot give.** It gives two numbers: the **chance of the official close rising** (event named) and the **expected close price**, each checked against its own definition (fixture: a 90% chance of −1% and a 10% chance of +20% gives a 10% chance of rise and an expected return of +1.1%).
- It **cannot** give the chance of profit after costs. That depends on the entry (fill or not, at which price), the price at the **executable** exit (US: 15:45 ET, not the close), EUR/USD and fees. The **chance of profit after costs** comes only from step 4a's conditional model of the executable net outcome, or from a joint model of those quantities registered with it.
- **Hurdle:** parameter uncertainty + cost-scenario band + execution-sensitivity band.

### 11.3 Step 4c: structured events

- AI extraction from results releases, filings and calls, behind verbatim-quote gates.
- News counted once per event cluster, with freshness decay.
- "Priced in" is held as an uncertain estimate.
- Results days get no preferential treatment.

### 11.4 Step 5

- **Ranking:** the heuristic is compared with two pre-declared simpler rules (top 3 by expected net return; random among the candidates that pass the hurdle).
- **Early exits:** sell at the next executable opportunity vs hold to plan, with the same cut-off, differential costs, the freed slot valued by the trades actually taken, and every eligible revision scored.

### 11.5 Step 6: adaptation

- Combination weights learned with a proper scoring rule, with shrinkage toward equal weights.
- **Primary test = money kept against the frozen equal-weight policy.**
- No automatic adaptation of decision rules in the first phase.

### 11.6 AI research loop

- The research director proposes versioned changes. They are tested in development, registered with a share of the α reserve, and evaluated forward.
- **At most 3 live challengers per market.**
- **The owner approves every promotion.**

---

## 12. What the owner sees

**Per company and day:**
- chance of rising, with its event in plain words ("closing higher on <exit day> than today's opening price, before costs");
- expected price and likely range;
- **chance of profit after costs**: "**not measured yet**" until step 4a;
- "**buy (limit ₹X) / hold / sell / no trade**", with a plain reason.

"No clear signal" (instead of a constant 47%) and "no trade" are normal.

**Per account (shown first)** : the account's money kept before and after the tax estimate, against cash and the index, as below.

**Per trade:** buy and sell price, every cost by name (broker, STT, stamp duty, exchange and SEBI fees with GST, DP, NRI reporting; or BUX order fees and currency conversion), and the **net profit after all trading costs**, in ₹ or €. Example (Appendix A.1): price gain ₹3,016, costs ₹661.62, **net profit ₹2,354.38**.

**Per account:**
- money now vs cash in the same account, and vs simply holding the index;
- before and after the tax estimate (both Box 3 regimes for the US account);
- drawdown;
- this month's costs (trading and AI) in both views, and the budget tier;
- open positions with their exit day and time in Amsterdam time.

**Plain status line on every report:**
> "Paper only. No proven edge: the current system has shown no forecasting skill so far. Whether a year of data can confirm a small advantage depends on the comparison; each report shows the numbers."

**Slack:** timed reminders with "Done" buttons at the right Amsterdam time (rehearsal account).

Everything technical is one tap away, never on the main page.

---

## 13. Open items and verification status

| Item | Status |
|---|---|
| India broker name, NRI charges, CAS and post-close support, TDS mechanics | default: zero-brokerage scenario, labelled "broker scenario"; TDS scenarios W1, W2 and W3 (W3 a custom stress); **confirmed only before real money** |
| Funding origin of the capital and the counterfactual | default: a savings account (modelling assumption); **confirmed only before real money** |
| Whether the household uses the Box 3 counter-evidence regime | known only at filing; both regimes reported |
| BUX Plus cash interest | **two official BUX sources disagree** (pricing page 1.75%; fee-schedule PDF 1.50%); default 1.50%; **confirmed only before real money** |
| India idle-cash interest | default 0%; **confirmed only before real money** |
| Billing basis of AI usage (API vs subscription) | both views shown until confirmed |
| SEBI 16 Jan 2026 circular (timetable) | consistent summaries; ChatGPT reports checking the primary text; Claude has not read it |
| NSE CAS circular NSE/CMTR/73362 | **read directly** |
| BUX Plus fees | official fee schedule plus the pricing page |
| BUX handling of pre-open limit orders | owner confirmed in the app; fill mechanics unverified |
| Yahoo 5-minute history (about 60 days) | third-party; not confirmed |
| Box 3 2026 rates, counter-evidence, anti-arbitrage | secondary sources; law text not read |
| Box 3 2027 rate | **not settled** |
| India STCG deductibility, TDS refunds | secondary sources; to confirm with the broker and the tax adviser |
| India–Netherlands treaty interaction | **not verified** |
| σ_d per hypothesis | **unknown until step 3**; rough inputs in 8.2 |

---

## 14. Governance, sessions and timeline

**Rules (from CLAUDE.md):**
- every batch is judged by the independent judge before merge;
- append-only data;
- fast test tier while iterating, full suite before review;
- pasted test numbers only;
- self-merge to main after a judge PASS.

**Sessions** (the orchestrator coordinates):

| Session | Owns | Depends on |
|---|---|---|
| **S1: accounting core** (new) | Step 1 (Sections 4, 6), cost scenarios with deductibility, interest series, tax periods and TDS, EURUSD=X intraday | — |
| **S2: scoreboards and protocol machinery** (new) | Step 2: inference methods, placebo harness, power calculator, registry, deviations, freeze guard, labels | S1's ledger schema |
| **S3: policies, power, registration and report** (new) | the wrappers, replay, power and validity analyses, registration record, account report | S1, S2 |
| **B6** (existing, Slack) | the Done reminders and buttons; the registration receipt post | S1 event schema |
| **B17** (existing, routines; **on hold until design approval**) | the evening run as additive records; the whole-system budget guard (5.3); moving deterministic steps to plain scheduled scripts; must not touch frozen inputs | S1 operating-cost tracker |
| **B3** (existing, AI traders) | the Sonnet/Opus split; `trader-combined.md` (Sonnet) stays frozen | B17 |

**Timeline** (working days **from the day the design is approved**, including judge rounds):
- Step 1: about 5–6 days (tax periods and TDS added).
- Step 2: about 3 days, partly in parallel.
- Step 3: about 4 days, including the placebo runs.
- **First account report and the draft registration record:** about 10–12 working days after approval.
- **Registration:** after ChatGPT's review and the judge's PASS of the registration record. The window starts on the next session.
- **Interim reports:** about every 8 weeks, descriptive.
- **Final results:** at each hypothesis's registered end (126–250 sessions after the start).

---

## Appendix A: worked trades

Illustrative prices; arithmetic computed with the stated rates. These are unit-test fixtures.

**A.1 India: ADANIPORTS, N+3, equity ₹3,00,000, no open positions**

1. **Slot:** ₹1,00,000.
2. **Reserves at submission:** buy fees ₹318.74 (STT, stamp, exchange + SEBI fees with GST, ₹200 date charge); sale fees ₹343.74 (DP reserve 0.04% of the slot = ₹40). No TDS reserve (Section 4.2).
3. **Quantity (fees only):** floor((1,00,000 − 318.74 − 343.74) ÷ 1,700) = **58**. Limit ₹1,700.
4. **Fill:** opens at ₹1,690 ≤ L, so **assumed fill at the open**: ₹98,020; buy fees ₹316.39.
5. **Exit (N+3):** CAS market sell at 15:22 IST. Auction close ₹1,742 → ₹1,01,036; sale fees ₹345.23 (actual DP 0.04% of proceeds = ₹40.41).
6. **Money kept before tax:** **+₹2,354.38**.
7. **Taxable gain (scenario):** the economic gain plus the non-deductible items added back: STT ₹98.02 + ₹101.04, the two ₹200 date charges, DP ₹40.41 → **₹2,993.85**. Indian tax at 20.8% = **₹622.72**; remaining after Indian tax **₹1,731.66** (independently confirmed by ChatGPT). This still excludes the account's operating costs and the unverified Dutch and treaty effects. The fixture also computes the TDS withheld, the credit receivable and the year's single tax expense.

**A.2 US: COST, N+5, $3,000 at q₀ = 1.10 USD per EUR = €2,727.27**

1. **Slot:** €909.09.
2. **USD available** : (909.09 − 0.99 − 0.99) × 1.10 × (1 − 0.02) × 0.9975 = **$975.42** (default buffer b = 2%).
3. **Quantity:** floor(975.42 ÷ 940) = **1**. Limit $940. (A stock nearer a whole-share boundary could change quantity with or without the buffer, which is why a single formula matters.)
4. **Fill:** opens at $935. € paid = 935 ÷ (1.10 × 0.9975) + 0.99 = **€853.12**.
5. **Exit:** the 15:45 ET price, $960; EUR/USD 1.08 at exit. € received = 960 ÷ 1.08 × 0.9975 − 0.99 = **€885.68**.
6. **Money kept before tax:** **+€32.56** (+3.82% in EUR vs +2.67% in USD).
7. **Unused cash:** about €56, earning the Plus rate. The account also pays €2.99 per month.

## Appendix B: failure fixtures (must pass in step 1)

1. **Losing India trade:** the auction exit is below entry; fees and the date charge deepen the loss.
2. **USD gain → EUR loss:** stock +1%, EUR/USD +2.04% → about −1.02% in EUR before fees. Mirror case: EUR/USD −2% → +3.06%.
3. **Unfilled order blocking cash:** a second candidate is skipped with `insufficient_free_cash`; the reservation is released at the close.
4. **Two orders on one date:** the ₹200 NRI charge is applied once, split by rule.
5. **Exit never acknowledged (rehearsal):** "exit not executed"; the position stays marked to market, counts in the brake, and is re-attempted.
6. **Operating costs exceed trading profit:** a month with a trading result of +₹1,500 and a larger deployment AI cost → the deployment result is negative; the total view counts the bill once.
7. **CAS band:** a sell limit outside ±3% is rejected; a market order is accepted.
8. **No equilibrium in the CAS:** close = reference price; the order is unfilled; the fallback chain runs.
9. **Loss brake:** −10% from peak → new orders blocked; open exits continue; restart only after an approval event (rehearsal) or the assumed 5-session scenario (policy account, labelled).
10. **Whole-share limit:** a stock priced above the slot → `price_above_slot`.
11. **FX look-ahead:** a later EUR/USD value present in the data is never used.
12. **AI abstention vs failure:** `abstained` → no trade, not a failure; `timeout` or a missing row → no trade, counted as a failure; neither is replaced.
13. **Cash interest with its plan:** €1,000 idle for 30 days at 1.50% gives €1.23 interest, and the same 30 days carry the €2.99 fee; the cash comparator gets both. A test fails if interest is credited without the plan's fee.
14. **Freeze guard:** changing `lab/gain.py` without a deviation row fails.
15. **Anti-arbitrage, straddle:** sale on 15 Dec, repurchase on 10 Jan → flagged.
16. **H3 single deduction:** AI arm extra trading benefit $80, extra AI cost $60 → the paired difference is +$20, not −$40.
17. **Anti-arbitrage, gap too long:** sale on 1 Oct, repurchase on 15 Jan (straddles 1 Jan but more than 3 months apart) → **not** flagged. Sale on 5 Oct, repurchase on 20 Oct → not flagged.
18. **STT not deductible:** the taxable gain of A.1 adds back STT; a test fails if 20.8% is applied to the economic profit.
19. **Tax periods:** a window from 14 Oct 2026 to 13 Oct 2027 is split into India FY 2026-27 (14 Oct – 31 Mar) and FY 2027-28 (1 Apr – 13 Oct), and NL 2026 (marginal tax €0) and 2027 (pro rata 286/365 of the 1 Jan 2027-based tax).
20. **TDS cash drag:** a profitable India sale withholds TDS from its proceeds; that cash is unavailable for the next order; under W2 an earlier loss in the same financial year reduces the withholding.
21. **Budget tiers:** at a projected 95% the news analyst pauses; the next rule decision uses a zero news shift and is flagged `degraded_news`.
22. **Absolute condition:** a candidate that beats cash after tax while its own after-tax money kept is negative → fails S3.
23. **TDS is not a second tax:** ₹1,000 withheld, final liability ₹600 → available cash −₹1,000 at withholding; tax expense ₹600; refund receivable ₹400; equity reduced by ₹600 only. A test fails if any tax total exceeds the liability.
24. **Label honesty:** before-tax estimate 1.00%, before-tax lower bound 0.60%, tax difference 0.30% → label "Before-tax minimum supported; after-tax estimate meets target", conditional after-tax lower bound 0.30%; a test fails if any label claims an after-tax minimum is established.
25. **No adequate method:** a synthetic case in which every candidate's placebo rejection rate exceeds α + 2 Monte Carlo standard errors → the record registers "descriptive only"; nothing is enlarged.
26. **Box 3 counterfactual:** two policies with the same 1 Jan 2026 position → 2026 tax difference €0, while the absolute view still shows the counterfactual's 2026 tax on the capital; a 1 Jan 2027 shares-vs-cash difference changes the 2027 marginal tax.
27. **Exposure timing:** constant 10% exposure vs full exposure on 10% of days on the same return series → σ_d ratio ≈ 0.10 vs 0.32 of the portfolio σ.

28. **Test statistic is money, not averaged returns:** an account that gains 100% of C₀ and then loses half its equity has Σ d_t × C₀ = 0 (equity back to C₀), while the mean of its daily percentage returns is +25%; the statistic reports 0.
29. **Liquidation value at the end date:** an open US position at the end date is valued at the close minus the €0.99 order fee and the 0.25% FX markup; an open India position at the close minus STT, exchange fees with GST, DP and the date charge.
30. **FX rejection at fill:** slot €1,000, limit $99, q_sub 1.10, no other free cash. With b = 0: 11 shares, reservation €993.47 + the €0.99 sale-fee reserve = €994.46 ; the fill at q 1.08 costs €1,011.85 → rejected `insufficient_cash_at_fill` (never resized). With b = 2%: 10 shares, reservation ≤ the slot; the fill at q 1.08 costs €919.95 → filled. The quantity is fixed at submission in both cases.
31. **Settlement and buying power:** an exit at the close of E does not fund an entry at the open of E+1 under the default; it does under the sensitivity.
32. **Counter-evidence boundary** : **C0 household** (deemed-return tax €1,000, actual-return tax €1,500): a policy gain of +€100 raises the actual figure to €1,536; the deemed €1,000 stays the lower and applies, so the marginal Box 3 tax is **€0**. **C1 household** (deemed-return tax €1,500, actual-return tax €1,000): the same +€100 raises the actual figure to €1,036, which stays the lower and applies, so the marginal tax is **€36**. The household always pays the lower applicable calculation.
33. **Bonferroni and stopped hypothesis:** H2 stopped for harm → counted not rejected; H1 and H3 are still tested at 0.01 each.
34. **W3 proceeds block:** a sale of ₹1,01,036 blocks 25% (₹25,259) until release; the next order sees the reduced available cash.

35. **Tax bridge:** the worked chain of Section 8.6 (₹1,000 withheld, ₹600 liability, credit applied, ₹400 refunded): B_t stays ₹10,000 at every step; after-tax ends at ₹9,400 with exactly one ₹600 expense. A test fails if B_t changes at any tax event or if any tax total differs from ₹600.
36. **Account-level hypothetical liquidation:** two open India positions at the end date, one with a ₹1,000 taxable gain and one with a ₹400 taxable loss, sold together → one date charge; ΔTax_liq = 20.8% × ₹600 = ₹124.80 (with no other realised results in the year), not ₹208 for the gain alone.
37. **Box 3 negative actual return:** a household actual return of −€500 is floored at €0 for that year and not carried forward.
38. **Both-direction tax flag:** a candidate passing S2 under the governing scenario (C0) and failing under the C1 counter-evidence sensitivity → headline "Meets the economic target under the registered tax assumption; fails under the C1 sensitivity."
39. **[CHANGED IN v16]** **Historical fill-time FX (replaces the superseded open/close fixture):** (a) a historical US fill on date D uses the latest EUR/USD close dated **before** D, and its recorded age is the event time minus that close's 23:59 London time (e.g. Friday's close for a Monday fill); (b) **adding or changing any later observation**, including D's own close, leaves the main-case fill, rejection decision and conversion **unchanged**; (c) a predefined adverse stress (95th or 99th percentile one-day move against the account) can **independently** turn a fill into a rejection, and is reported as a stress; (d) D's same-day close appears **only** in the labelled diagnostic and never changes a decision.
40. **[NEW IN v16]** **Blocked money across settlement:** a sale of ₹1,01,036 under W3 blocks ₹25,259. **Before settlement:** unsettled proceeds ₹1,01,036 (₹25,259 of it blocked); total assets from the sale = ₹1,01,036, **never** ₹1,26,295; under the default buying-power rule none of it is available yet, under the immediate-reuse sensitivity ₹75,777 is. **After settlement:** settled cash ₹1,01,036, of which ₹75,777 is available and ₹25,259 stays blocked until release (end of T+1 in W3). Equity is the same at every step; only availability changes.
41. **[NEW IN v16]** **Freeze-guard detection:** changing a regime threshold in `config/markets/india.yaml`, a sector assignment, or a calendar rule changes at least one replayed decision or account figure **and** fails the freeze guard; a test fails if the guard misses any of the three.

## Appendix C: sources

- **NSE CAS circular NSE/CMTR/73362 (18 Mar 2026), read directly:** https://nsearchives.nseindia.com/content/circulars/CMTR73362.pdf
- **SEBI CAS circular (16 Jan 2026) summaries:**
  - https://www.mondaq.com/india/securities/1746562/sebi-introduces-closing-auction-session-in-the-equity-cash-segment-and-certain-modifications-in-the-pre-open-auction-session
  - https://www.venturasecurities.com/news/daily-market-updates/sebi-changes-closing-price-calculation-auction-based-closing-to-begin-from-august-2026-know-how-it-will-work/
  - https://zerodha.com/cas/
- **NSE pre-open:** https://www.nseindia.com/static/products-services/equity-market-pre-open
- **Post-close session:** https://support.zerodha.com/category/trading-and-markets/trading-faqs/articles/what-are-pre-market-and-post-market-sessions-and-orders
- **BUX:**
  - fee schedule (NL): https://getbux.com/documents/Fee%20schedule%20PDF%20-%20NL.pdf
  - pricing: https://getbux.com/?p=39
  - fractional shares: https://getbux.com/?p=12211
  - rate comparison: https://www.actuelerentestanden.nl/sparen/spaarrente/bux.asp
- **Box 3:**
  - https://www.rabobank.nl/en/personal/service/savings/tax-and-box-3
  - https://www.belastingdienst.nl/wps/wcm/connect/fisin/fisin2025/Box_3_Werkelijk_rendement
  - https://www.belastingdienst.nl/wps/wcm/connect/fisin/fisin2025/regels_voor_het_tijdelijk_verplaatsen_van_bezittingen_en_schulden
  - https://www.vanlanschotkempen.com/nl-nl/private-banking/inspiratie/vermogensregie/box-3-welke-antimisbruikregelingen-zijn-er
  - https://www.sra.nl/nieuws/004501/2022/10/let-op-de-peildatumarbitragebepaling-box-3-stelsel-2023
  - https://financialfocus.abnamro.nl/fiscaliteiten/pas-op-met-vermogensverschuivingen-in-box-3-rond-1-januari-2026/
  - 2027 rate uncertainty: https://www.financieelonafhankelijkblog.nl/vermogensbelasting-2027-omhoog/ and https://berthub.eu/tkconv/getraw/2025D43267
- **India NRI capital gains and TDS:**
  - https://cleartax.in/s/short-term-capital-gain-on-shares
  - https://www.finnovate.in/learn/blog/nri-capital-gains-tax-india
  - https://arthgyaan.com/blog/what-are-the-tds-rates-applicable-to-nris.html
- **India TDS broker mechanics:** HDFC PIS and Zerodha Non-PIS descriptions as reported by ChatGPT's review (not read by Claude; to confirm once the broker is named).
- **Box 3 reference date and counter-evidence:** Belastingdienst pages listed above.
- **Inference methods (standard references):**
  - Newey & West (1987) and Andrews (1991) for HAC with automatic bandwidth;
  - Politis & Romano (1994) for the stationary bootstrap;
  - Politis & White (2004) for automatic block length.
- **Repository evidence (`origin/main` 82ff0f5):** `model/labels.py`, `lab/gain.py`, `lab/picks.py`, `lab/strategies.py`, `config/strategies.yaml`, `config/model.yaml`, `config/costs.yaml`, `data/<market>/lab_backtests/2026/10/2026-10-10.jsonl`.
- **Stored-data figures in 8.2:** `bars` view, 2024-10-01 to 2026-10-09; DuckDB + NumPy, seed 0, 2,000 draws.

---

## Appendix D: Review record

### D.1 ChatGPT's review of v13 and Claude's reply

**ChatGPT's verdict on v13:** it agrees with v13 as the complete, phased design for paper research. The previous blocking points are resolved, and the owner can now decide whether to approve the build.

**My review of ChatGPT's response.** I re-checked each claim it made before accepting it:
- its tax-bridge table (₹10,000 before tax throughout; ₹9,400 after tax; one ₹600 expense) matches fixture B.35;
- its liquidation example (20.8% × ₹600 = ₹124.80) matches fixture B.36;
- its power figures (0.534%; 286 sessions) match §8.2;
- its arithmetic on operating costs is right: 0.5% of about $6,500 is $32.50 a month, against a ceiling of $250 (3.85% of capital).

I found nothing to push back on. Its remaining remarks are not new requirements; they are three clarifications of what the design already intends. **v14 applies only those three, as wording**, and changes nothing else:

| # | ChatGPT remark | Verdict | Where and what |
|---|---|---|---|
| 1 | The tax bridge keeps before-tax equity unchanged, but tax-related cash restrictions must still limit later trading in the simulation | **Accept** | §8.6: the bridge changes only how equity is reported. Withholding, blocks and refunds still reduce the cash available for trading under §4.2 and §4.8, and so can change later trades and profits. |
| 2 | If a joint Holm decision is chosen instead of Bonferroni, its timing, allocations and bounds must be specified before forward confirmatory outcomes are examined | **Accept** | §8.6: if chosen, the registration record must state the decision date (after the longest window), the family allocation per market, and the Holm-consistent lower bounds used for labels. |
| 3 | "No valid after-tax interval" is a limitation of this protocol, not a mathematical impossibility | **Accept** | §8.7 wording: "this protocol does not construct an after-tax interval; doing so would need a dedicated method. No label claims an after-tax minimum is established." |
| 4 | The trading logic remains unproven (degenerate India model, no-change price centre, coin-level AUC, fixed news weights, heuristic ranking score); a probability is not a payoff (70% × +1% and 30% × −4% gives −0.5% before costs) | **Agree; already stated** | §1.3, §2.4 and §11 already say this. The corrected ledger measures; it does not repair the forecasts. |
| 5 | Operating costs are a serious constraint; the measured bill must decide | **Agree; already in the design** | §5.1 and §5.2: the actual billing basis decides; token valuations are not treated as bills. |
| 6 | The broker, fill, FX-timing and tax assumptions must stay labelled and never become facts through repetition | **Agree; already in the design** | §4, §13 and the labels in §8.9. |

### D.2 Independent judge review of v14

**Verdict: FAIL.**
- **What passed:** all arithmetic (both worked trades, every numeric fixture, the power table, the time zones, the Holm example and the cost ratio) and every code and config claim checked.
- **What failed:** 6 blockers and 13 cosmetic findings:
  - **B1:** the India coverage figures 84.3% / 87.8% are not reproducible;
  - **B2:** the stored-data volatility table is wrong, and "only 8 India tickers" is false;
  - **B3:** there are two inconsistent US quantity formulas (with and without the FX buffer);
  - **B4:** the historical FX fallbacks use the 23:59-London daily close for earlier US-session events, which is a look-ahead;
  - **B5:** the design promised that no forward outcome would be looked at before registration, yet forward account reports are reviewed before it;
  - **B6:** the freeze-guard list is incomplete.

Claude verified each finding and agreed with all of them, narrowing B6 (cost edits before registration are permitted).

### D.3 ChatGPT's review of the judge's findings, and Claude's reply

ChatGPT accepted all six blockers, changed several fixes, and **rejected cosmetic finding #11**. It also said Claude's blanket agreement was too uncritical. **Claude re-checked each point against the code and data before deciding.**

| # | ChatGPT's position | Claude's verdict and evidence | In v15 |
|---|---|---|---|
| B1 | Agree with the correction, but reject the retained "reasonably calibrated" conclusion. The same replay shows engine bands **wider** than the naive baseline with **worse** interval scores. | **Accept; my wording was overstated.** I re-read the replay output: N+1 width 5.728% vs 5.192%, score 7.777 vs 7.745; N+5 10.883% vs 8.989%, score 13.697 vs 13.277; I also checked N+3 (8.637% vs 7.340%, 11.077 vs 10.856). Every coverage interval excludes 80%. Engine/naive width ratio: 1.10 (N+1), 1.21 (N+5). | §2.4 item 5: ChatGPT's wording, with an N+1/N+3/N+5 table. |
| B2 | Agree the old table is wrong; the exact new figures are not independently certified (its own reconstruction: India 1.0875 / 1.0668 / 0.5227, US 1.4653 / 1.5728 / 0.4484); "full history" must name the period; the exposure limits should be 11.2% / 8.0%, not 12% / 9%. | **Accept all three.** My 12% / 9% used σ_d 0.127%, which is the 80%-power limit at the **old** α 0.0167. At α = 0.01 the limit is 0.005 ÷ (21 × 3.168 ÷ √250) = **0.1188%**, so 0.1188 / 1.0638 = **11.2%** and 0.1188 / 1.4785 = **8.0%**. My error. | §8.2: period stated; method and script named; both reconstructions shown; marked "not certified until reconciled"; limits 11.2% / 8.0%, labelled illustrative and not allocations. |
| B3 | Agree. | Agree ($975.42 vs $995.33, recomputed). | One formula everywhere (§4.2, A.2). |
| B4 | Agree, but it is not "small": an FX difference can flip a rejection and change later holdings. Verify the vendor timestamp of the daily open; a stale rate is not conservative; use predefined adverse stresses; show the later close only as a diagnostic. | **Accept, with one change of method.** Rather than relying on an **unverified** timestamp for the daily open, v15 uses the **previous day's daily close**, whose declared time (23:59 London, `config/markets/us.yaml`) is certainly earlier than any US-session event. This removes the timestamp question instead of assuming an answer. I also withdraw "small": the account-level effect is measured. | §4.7 timing rules and table: previous-day close; 95th/99th-percentile adverse stresses; account-level effect reported; same-day close as diagnostic only. |
| B5 | Agree on the contradiction. Protect **all** choices that matter, not just power inputs. Prefer **Bonferroni at α = 0.01 for this first registration**; a "switch if +10 points" rule is another arbitrary design choice. Disclose observed exploratory outcomes. | **Accept.** The 10-point threshold was indeed my choice, not a statistical requirement. Bonferroni is now fixed for this registration with no switch, and the Holm power cost is reported for information only. Every choice that matters (policies, comparators, hypotheses, multiplicity, label rules, and the rules for windows, method and FX buffer) is fixed in this document. | §8.1 and §8.6. |
| B6 | Agree, including Claude's narrowing. | Agree. | §8.10: complete manifest; pre-registration cost changes permitted; snapshot at registration. |
| #11 | **Reject:** the combined trader does **not** read the results-analyst's "Results digests" section. | **Accept the rejection; the judge and I were wrong.** `traders/prepare.py` `SECTION_INPUTS` (lines 22–44) maps "Latest quarterly results", "Fundamentals" and "Earnings estimates" to `results`, but has **no** entry for "Results digests" (the title in `results/context_section.py` line 18). `category()` returns None for unmapped titles, and such sections are left out for every trader. | The v15 draft's results-analyst additions are **not** made. The results-analyst is **not** a deployment cost of `acct.ai.v1` and is not in the freeze list. If the digests are ever fed to the trader, that is a **policy change** with its own costs and freeze entry. Actual analyst bills still appear in the owner's total-cost view. |
| #1–3 | Editorial. | Agree. | Contents, opening line and version references cleaned up. |
| #4 | A protocol ambiguity, resolved with B5. | Agree. | §8.1. |
| #5 | Substantive: without it, the text suggests news is counted twice. | Agree. | §2.3. |
| #6 | Agree; name the label and horizon. | Agree. | §2.4.4. |
| #7 | A small correction. | Agree. | §2.4.1. |
| #8 | A real cash-accounting omission (€994.46). | Agree (recomputed). | B.30. |
| #9 | A real tax-fixture error; the household pays the lower applicable calculation. | Agree. | B.32: separate C0 and C1 households. |
| #10 | A real accounting ambiguity; count blocked money once. | Agree. | §4.2 cash-state table. |
| #12 | A reporting ambiguity. | Agree. | §8.9: one explicit order of precedence. |
| #13 | Harmless. | Agree. | §2.2 and §9.1. |

**Where I push back on ChatGPT:** nowhere on substance. On B4 I adopt a different method from the one it suggested (the previous-day close instead of a verified daily-open timestamp). It reaches the same goal, never using an observation later than the event, without depending on a timestamp convention that neither of us has verified.

**ChatGPT's point about my previous reply was fair.** I agreed with the judge too quickly on #11 and on the exposure limits, without re-checking them against the code and the current α. This time every acceptance above was checked against the code, the replay output or a recomputation.

### D.4 ChatGPT's check of v15, and Claude's reply

ChatGPT accepted the v15 architecture and most corrections. It confirmed:
- the arithmetic: $975.42; €853.12 / €885.68 / +€32.56; €994.46; €0 and €36; 0.1188%;
- that B1, B3 and B5 are resolved, and that the results-analyst rejection is correct.

It asked for three bounded corrections and the volatility reconciliation. It also said "every acceptance was checked" overstated the result. **Claude re-checked each point against the document and the code.**

| # | ChatGPT's point | Claude's verdict and evidence | In v16 |
|---|---|---|---|
| 1 | Fixture B.39 still tests the superseded open/close rule and contradicts §4.7 | **Accept; my error.** v15 changed §4.7 but left B.39 unchanged (v15 Appendix B line 39 still said "open passes and close fails"). A builder following Appendix B would implement the rule §4.7 forbids. | B.39 replaced: the earlier close governs; later observations cannot change the main case; adverse stresses can reject independently; the same-day close is diagnostic only. |
| 1b | "Stale by up to one day" is wrong across weekends and holidays; record the actual age | **Accept.** Friday's close serves a Monday event (about three days old). | §4.7: the actual age is recorded with every use. |
| 2 | "Every dependency" is overstated; unlisted logic includes features and regime, the calendar, market config, and evidence-status and context preparation outside the trader package | **Accept, confirmed in the code.** Imports by `traders/` and the strategy and pick code include `pipeline.evidence_status`, `pipeline.forecast_gate`, `analytics.prediction_rules`, `model.forecast_rules`, `model.news_score`, `core.calendar`, `contracts.*` and `portfolio.horizons`, none of which v15 listed. A hand-written list will always lag the code. | §8.10: the list becomes a "starting inventory" with the found dependencies added (plus `sql/views.sql`). Completeness is **enforced**: a generated manifest (the import closure of the decision and accounting entry points, plus the config, SQL and instruction files read at run time, traced in a replay), and a **detection test** that changes to a regime threshold, a sector assignment and a calendar rule alter a decision **and** are caught (fixture B.41). |
| 3 | "Blocked money inside settled cash" is too categorical: the block starts on the sale date, before settlement | **Accept.** ChatGPT's ₹1,26,295 double-counting example shows exactly the risk. | §4.2 uses ChatGPT's wording: counted once in the underlying balance (unsettled proceeds, then settled cash); the block restricts availability only. Fixture B.40 walks the ₹1,01,036 sale through both stages. |
| 4 | B2: naming a script is not evidence; publish it, reproduce, explain the discrepancy | **Accept, and done.** The script and its output are now in **Appendix E**, so reviewers can read and run them. **Discrepancy explained for India:** 526 stored dates, only 498 with all 20 closes. The judge's script let the 28 partial dates break returns. The canonical session-panel method gives 1.0866% / 1.0696% / 0.5208, matching ChatGPT's 1.0875% / 1.0668% / 0.5227 within 0.002 points. **US:** session panel 1.4806% vs ChatGPT 1.4653%, close but not identical; the remaining difference is listed for reconciliation and is not claimed resolved. | §8.2 table updated to the canonical figures; exposure limit for India corrected to **10.9%** (0.1188 ÷ 1.0866); US stays 8.0%. |
| 5 | "Every acceptance was checked" overstated the result | **Accept.** An obsolete fixture survived and the manifest was incomplete. Checking each accepted point did not check the whole document for knock-on effects. | v16 was checked for knock-on effects: I searched the whole document for every rule changed (FX timing, blocked cash, the manifest, the volatility figures and their thresholds) and updated each occurrence. |

**Pushback:** none on substance. One clarification on point 4: the US figure is not yet reconciled to ChatGPT's, and v16 says so. The figures are illustrative scenarios; no protocol rule depends on their third decimal.

### D.5 Status and next steps

1. ChatGPT performs a targeted check of the v16 changes (every edit is marked **[CHANGED IN v16]** or **[NEW IN v16]**).
2. The judge re-checks the six original blockers and the v14 → v16 changes.
3. The owner decides whether to approve the build. **Nothing is built before that.**
4. After approval: commit the design and `docs/plan_volatility.py`, record the judge PASS, and build steps 1–3. The generated freeze manifest and its detection test are registration prerequisites.
5. **Still true:** the current forecasting and decision logic is unproven. Implementation and forward results, not another review, will show whether it makes money after all deductions.

## Appendix E: volatility script and output (for §8.2)

Run from `scripts/` with `PYTHONPATH=. python plan_volatility.py` on `origin/main` 82ff0f5 data.

```python
"""Illustrative portfolio-volatility scenarios for design section 8.2 (run from scripts/: PYTHONPATH=. python plan_volatility.py).

Method (canonical, v16): the market's watchlist companies; `bars` view, 1 Oct 2024 - 9 Oct 2026; the SESSION PANEL =
the dates on which every one of those companies has a stored close (dates where only some have a bar are dropped,
not treated as gaps); daily simple returns from consecutive panel dates; 2,000 random draws (NumPy default_rng seed 0)
of 6 distinct companies split into two disjoint 3-stock equal-weight portfolios A and B; report the mean over draws of
sd(A), sd(A - B) and corr(A, B), in percent."""
import numpy as np
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market

for market in ("india", "us"):
    con = connect(market)
    tickers = list(load_market(market)["tickers"])
    df = con.execute("select ticker, date, close from bars where date >= '2024-10-01' and date <= '2026-10-09'").df()
    panel = df.pivot(index="date", columns="ticker", values="close").sort_index()[tickers]
    sessions = panel.dropna()
    returns = sessions.pct_change().iloc[1:]
    rng = np.random.default_rng(0)
    sd_a, sd_diff, corr = [], [], []
    for _ in range(2000):
        pick = rng.choice(len(tickers), 6, replace=False)
        a = returns.iloc[:, pick[:3]].mean(axis=1)
        b = returns.iloc[:, pick[3:]].mean(axis=1)
        sd_a.append(a.std()); sd_diff.append((a - b).std()); corr.append(np.corrcoef(a, b)[0, 1])
    print(market, "dates", len(panel), "session panel", len(sessions),
          "sd(A) %.4f%%  sd(A-B) %.4f%%  corr %.4f" % (np.mean(sd_a) * 100, np.mean(sd_diff) * 100, np.mean(corr)))
```

Output (11 Oct 2026):

```
india dates 526 session panel 498 sd(A) 1.0866%  sd(A-B) 1.0696%  corr 0.5208
us dates 507 session panel 504 sd(A) 1.4806%  sd(A-B) 1.5779%  corr 0.4495
```

Research only. The system never places real trades and never connects to a broker.
