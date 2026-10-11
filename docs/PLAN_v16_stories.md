# Implementation stories for the final design v16 (revision 11)

Prepared 11 October 2026 by Claude, for the owner and for ChatGPT's review. This document replaces revisions 1 to 10 in full.

**Source:** `FINAL_Design_v16.md`, SHA-256 `a19e3405530b691423f68ffb21a272482554fbee5ce0d875a578a50159d3e19b` (ChatGPT confirmed the hash). Section numbers (§) refer to that document. B.n are its Appendix B fixtures; A.1 and A.2 are its worked trades; I-n are the integrated fixtures added in this revision (ST-55).

**What this document is.** It is a **plan**: the stories an implementing agent picks up. Each story states **what** to build and the **observable properties** its tests must show. **How** to build it (formulas, estimators, data structures) is the implementing agent's choice, judged by those properties and reviewed per batch by the judge. Revisions 5 to 8 had drifted into implementation (estimator formulas, degrees of freedom, simulation code). Revision 9 removes that detail, because each prescribed formula became a new thing to dispute rather than a better plan.

**What changed in revision 11** (ChatGPT's review of revision 10: two targeted points, each reasoned through before acting on it; reply in Appendix 4, section 4j). Only ST-12, ST-38, DC-6 and DC-12 change.
- **Unconfirmed dividend cash can no longer be spent (ST-12, DC-12).** Revision 10 released an unconfirmed dividend's cash at a "declared latest payment date" (for example ex-date + 30 days), and claimed that this errs only late. **That claim was wrong, by my own check.** India's 30-day rule runs from the dividend's *declaration*, and a final dividend is declared at the annual meeting, which can come after the ex-date. US dividends have no such limit at all. So the money that money-actually-available accounts can spend now requires a verified payment date or a recorded receipt. Historical replays may use an assumed date only as a labelled assumption, with a timing sensitivity. A missing amount or an unknown share basis makes the result **incomplete**; it never counts as zero income.
- **One definition decides which scenarios enter the power calculation (ST-38, DC-6).** Revision 10 still had two: "neither arm submits an order" in ST-38 and "zero variance" in DC-6, which disagree when orders are placed but never filled. Both cases are now named, treated the same way (excluded from the envelope, and the reason reported), and tested.

**Owner decisions in force:**
- v16 is final; the owner overrode the judge's v16 FAIL;
- the judge's four open points are handled during implementation. This revision gives two of them owning stories (DC-1, DC-2) and records the other two as errata (DC-5). **The owner can reject any DC before implementation starts.**

---

## How to read a story

Each story has:
- **heading** (ID and title);
- **subject** (one line);
- **description** (what to build, with § references);
- **acceptance criteria** (what must be true and tested);
- **refs**;
- **depends on** (stories that must exist first);
- **owner** (the session that builds it, as in §14);
- **phase**: Step 1, 2 or 3 of §10; Routine (§5.4); or Deferred (§11).

**Rules for every story** (§14 and CLAUDE.md, not repeated in each story):
- append-only data;
- no look-ahead;
- provenance tags on every number (§6);
- the fast test tier while iterating and the full suite before review;
- numbers pasted from command output;
- a judge review per batch;
- research only: never trade, never connect to a broker.

---

## Gates (phase completion; enforceable)

Gates are **cumulative**: each one requires every earlier gate to have passed, and the gate check refuses to run otherwise.

| Gate | Passes only when |
|---|---|
| **G1, end of Step 1** | ST-01 (committed design and errata as the reference), ST-02 to ST-19, ST-20 (budget guard, with the floor-cost disclosure), ST-46, ST-55, ST-56 (cost and producer contract) and ST-57 are done; ST-09 is integrated with ST-46's measured values (fixture defaults replaced); every Step-1 fixture in Appendix 3 passes (checked by ST-47); the judge PASSes the batch |
| **G2, end of Step 2** | G1 passed; ST-32 to ST-41 are done and pass on **synthetic and fixture data** (no Step-3 data needed); ST-47 coverage passes for the Step-2 fixtures; judge PASS |
| **G3, end of Step 3 (before registration and before any account report is delivered to the owner)** | G2 passed; ST-25 to ST-31, ST-42 (including the graph-builder producer coverage), ST-44, ST-45 (the owner-facing wording checks) and ST-58 are done; ST-47 shows **all** fixtures (A, B, I) passing; ST-39 is tested on every label branch; judge PASS. Only then may ST-43 (registration) run, and only then are account reports delivered to the owner |
| **G4, deferred work** | G3 passed; ST-44's account report has been reviewed by ChatGPT and the owner (§11) |

The budget ceiling is a **target**, not a guarantee (DC-10): v16 §5.3's check runs before each paid step, so the last admitted step can cross it. Any excess is recorded and reported. ST-21 removes the floor cost of deterministic work (§5.3's "honest limit"); it does not bound variable paid calls. The four-week cost study (ST-24) keeps its own descriptive timetable and does not block registration.

---

## Epic E0: Foundations

### ST-01: Commit the final design, its script and its errata
- **Subject:** put v16 into the repository unchanged, with the clarification register beside it.
- **Description:**
  - **Design files:** commit `FINAL_Design_v16.md` unchanged as `docs/PLAN_v16.md`, and the Appendix E script as `docs/plan_volatility.py`. The script is run from the repository root as `MB_NOW=2026-10-09T23:59:00Z PYTHONPATH=scripts python docs/plan_volatility.py` (the clock is pinned so that later watchlist events cannot change the company list or its order); the script itself is unchanged, only the documented run command reflects its new location.
  - **Errata:** commit Appendix 2 of this document (**every** clarification in it, currently DC-1 to DC-12) as `docs/PLAN_v16_errata.md`, so v16 is never edited.
  - **Judgments log:** record in `judgments/log.jsonl` the judge's v16 FAIL and the owner's override of 11 Oct 2026, with the reference to the owner's message.
  - **CLAUDE.md:** add a pointer to both files.
- **Acceptance criteria:**
  - `sha256sum docs/PLAN_v16.md` = `a19e3405…3e19b`;
  - the documented command prints the Appendix E output (India 1.0866% / 1.0696% / 0.5208; US 1.4806% / 1.5779% / 0.4495);
  - the errata file lists every DC of Appendix 2 and nothing else (a test compares the two lists of identifiers, so a later DC cannot be left out);
  - `tests/test_judgments.py` passes.
- **Refs:** whole document; Appendix E; Appendix 2 here. **Depends on:** none. **Owner:** orchestrator. **Phase:** Step 1.

### ST-02: Append-only data kinds for accounts and evaluation
- **Subject:** the ten new record types of §6, with schemas and provenance tags.
- **Description:** add these kinds to `core/schemas`, with their key fields as listed in §6: `account_decisions`, `account_order_events`, `account_fills`, `account_cash_ledger`, `account_equity_daily`, `account_tax_periods`, `operating_costs`, `experiment_registry`, `registered_deviations` and `evaluation_results`. Storage follows the data rules.
- **Acceptance criteria:**
  - each kind validates its schema;
  - a correction is a new row and no row is ever rewritten (test);
  - each numeric field rejects a missing provenance tag;
  - DuckDB views read each kind.
- **Refs:** §6. **Depends on:** none. **Owner:** S1. **Phase:** Step 1.

---

## Epic E1: Accounting core (Step 1)

### ST-03: Account model and funding
- **Subject:** policy accounts and rehearsal accounts, with the same starting capital.
- **Description:**
  - **Account types:** policy accounts (assumed attendance, assumed approval scenario) and owner rehearsal accounts (recorded attendance), per §4.1.
  - **Starting cash:** ₹3,00,000 (India); $3,000 converted to EUR at q₀, the latest EUR/USD observation ≤ the first decision's cut-off.
  - **C₀:** stored once per market and **shared by every policy account of that market**, with the same funding conversion.
  - **Slot:** S = marked equity ÷ 3 at submission.
- **Acceptance criteria:**
  - q₀ never uses a later observation (test with a later value present);
  - all policy accounts of a market have an identical C₀ and q₀ (I-5);
  - the 15 research strategies are never summed into an account return.
- **Refs:** §4.1, §4.2, §8.6 (C₀). **Depends on:** ST-02, ST-09. **Owner:** S1. **Phase:** Step 1.

### ST-04: Named cost scenarios in config
- **Subject:** add the zero-brokerage India and BUX Plus US scenarios without rewriting the old ones.
- **Description:**
  - **Scenarios:** named scenarios in `config/costs.yaml` with every rate, charging unit and India deductibility flag (default and sensitivity) of §4.5.
  - **Slippage stress view:** +0.05% per side on **market-order** fills only.
  - **History:** the Axis Direct and BUX Basic views stay unchanged.
- **Acceptance criteria:**
  - every §4.5 rate, unit and flag is loaded;
  - the old cost views are byte-identical before and after;
  - the stress view never applies to limit fills.
- **Refs:** §4.5. **Depends on:** none. **Owner:** S1. **Phase:** Step 1.

### ST-05: Cost engine per charging unit
- **Subject:** every trading cost at its real unit.
- **Description:**
  - **India:** STT, stamp duty, exchange and SEBI fees with GST; the ₹200 NRI charge **once per trade date**, split by rule across that date's orders, including hypothetical liquidation sales; DP per scrip sold.
  - **US:** €0.99 per order; 0.25% per conversion; the €2.99 plan fee per month, **charged once** per account and month, whichever story books it.
- **Acceptance criteria:**
  - A.1 exact (buy fees ₹316.39, sale fees ₹345.23, net +₹2,354.38);
  - B.1 and B.4 pass;
  - I-1 (one shared date charge when several India positions are liquidated together) and I-2 (the plan fee deducted exactly once per month across the cost, interest and accrual paths) pass.
- **Refs:** §4.5, A.1, B.1, B.4. **Depends on:** ST-04, ST-02. **Owner:** S1. **Phase:** Step 1.

### ST-06: Sizing, quantity and reservations
- **Subject:** turn a slot into a whole-share quantity and reserve cash for it.
- **Description:**
  - **Reservations:** the order value at L, the buy fees, the sale fees on the slot base, and any unreserved date charge. No tax reserve.
  - **India quantity:** floor((S − reserved fees) ÷ L).
  - **US quantity:** the single buffered formula, USD available = (S − €0.99 − €0.99) × q_sub × (1 − b) × (1 − 0.25%); the reservation is taken at the buffered rate.
  - **Skips:** `insufficient_free_cash` and `price_above_slot`.
  - **Release:** reservations are released or adjusted at the fill or at expiry.
  - **Market-order sensitivity (DC-3):** sized at L with the same formula, the quantity is **fixed at submission**. The fill may be above L, and the affordability rule of ST-08 applies at the fill.
- **Acceptance criteria:**
  - A.1 gives 58 shares;
  - A.2 gives $975.42 and 1 share;
  - B.3, B.10 and B.30 pass;
  - only one US quantity function exists.
- **Refs:** §4.2, §4.3, A.1, A.2, B.3, B.10, B.30, DC-3. **Depends on:** ST-03, ST-05, ST-09. **Owner:** S1. **Phase:** Step 1.

### ST-07: Cash states and buying power
- **Subject:** separate settled cash, unsettled proceeds, available cash, blocks and receivables.
- **Description:**
  - **Cash states:** as in §4.2.
  - **Buying power:** default T+1 settlement; immediate reuse as a sensitivity; a result that holds under only one is labelled "depends on the broker's buying-power rule".
  - **W3 block:** counted once inside its underlying balance (unsettled proceeds, then settled cash). It restricts availability only. It is released at the end of T+1; then the actual TDS is applied, with losses offset within the financial year (§4.8).
- **Acceptance criteria:**
  - B.31, B.34 and B.40 pass;
  - I-3 passes: a W3 sale's block is released at the end of T+1; the actual TDS is booked at that time as a credit; buying power from T+2 equals the proceeds minus the TDS, under both the default and the immediate-reuse sensitivity.
- **Refs:** §4.2, §4.8 (W3), B.31, B.34, B.40. **Depends on:** ST-02, ST-03. **Owner:** S1. **Phase:** Step 1.

### ST-08: Entry fill engine with execution variants
- **Subject:** simulate day orders from daily bars, with every sensitivity variant.
- **Description:**
  - **Limit buy (main case):** L = previous close × 1.005. Open ≤ L → filled at the open; else Low < L by at least one tick → filled at L; else unfilled.
  - **Limit-level sensitivity:** L = previous close × 1.000.
  - **Market-at-open sensitivity (DC-3):** fills at the open price even above L, **subject to affordability**. Rules:
    - the quantity stays as submitted;
    - at the open, the orders of one account are processed in the policy's ranking order;
    - each order's cost (quantity × open + fees; for the US, in euros at the fill rate) must not exceed its own reservation **plus** the free cash available at that moment;
    - otherwise the order is **rejected** (`insufficient_cash_at_fill`) and counted as unfilled;
    - **reservation release timing:** a rejected order's reservation is **not** released while the account's orders at that open are still being processed. All releases from rejections happen **after** the whole batch, so a rejection never makes a later order in the same batch affordable;
    - **no resizing and never negative cash**;
    - this applies to India and the US alike.
  - **Execution variants:** trade-through of 1 tick, 0.1% or 0.25%; open-only; intraday fills only when Low ≤ L − 0.25%.
  - **US FX rejection at the fill** (`insufficient_cash_at_fill`); a fill is never resized.
  - **Labels:** every fill is "assumed"; a result that holds only under the most optimistic variant is "not robust".
- **Acceptance criteria:**
  - **a buy-limit fill is never above its limit;**
  - a fixture with previous close 100, L 100.50 and open 102: the limit order is unfilled, or filled intraday at L if Low < L; the market-at-open sensitivity fills at **102** (DC-3);
  - **affordable gap:** one market order at 102 within its reservation plus free cash fills;
  - **unaffordable gap with competing reservations:** 3,000 available, three orders of 10 shares sized at 100 (reserved 1,000 each), all opening at 102 (fees ignored in the fixture), free cash 0. Each order costs 1,020 against its reservation of 1,000 and free cash 0, so **all three are rejected** (`insufficient_cash_at_fill`). **No cash goes negative and no quantity is resized.** Variant with 50 of extra free cash: orders 1 and 2 fill (using 20 + 20), and order 3 is rejected (10 left, 20 needed), in ranking order. Under the release rule, order 3 is still rejected even though no earlier order's reservation was released during the batch; after the batch, order 3's 1,000 reservation is released;
  - each variant is reproducible on a fixture;
  - B.30 passes; A.2 fill = €853.12.
- **Refs:** §4.3, §4.2, A.2, B.30, DC-3. **Depends on:** ST-06, ST-09. **Owner:** S1. **Phase:** Step 1.

### ST-09: EUR/USD observations and timing rule
- **Subject:** every currency conversion uses only observations available at the event.
- **Description:**
  - **Collection:** add EURUSD=X to `config/intraday.yaml`, plus the post-close 5-minute fetch.
  - **Rule:** the latest observation with timestamp ≤ the event, for every row of the §4.7 table.
  - **History fallback:** the latest **daily** close dated before the event's date, with its actual age recorded.
  - **Adverse stresses:** the 95th and 99th percentiles of the **absolute one-day** EUR/USD move, measured by ST-46. Each is applied **against the account**: a lower EUR/USD for a euro-funded buy (more euros per dollar spent), and the side that lowers euros received for a sale.
  - **Same-day close:** diagnostic only.
  - **Buffer b:** the 99.9th percentile of the **absolute overnight** move (ST-46); 2% default until measured.
  - **Reporting:** the account-level effect of these choices is reported.
- **Acceptance criteria:**
  - B.2, B.11 and B.39 pass;
  - every historical use records its age;
  - a test proves that percentiles are taken over absolute moves, not signed moves;
  - a test proves the stress direction is adverse for both buys and sales.
- **Refs:** §4.7, §4.2 (b), B.2, B.11, B.39. **Depends on:** ST-02. **Owner:** S1. **Phase:** Step 1. *Note: the engine is built and tested with fixture values for b and the stresses. The measured values come later from the story that measures them, and their integration is checked at gate G1, so this story has no dependency on it.*

### ST-10: India exit chain
- **Subject:** sell India positions through the closing auction, with ordered fallbacks.
- **Description:**
  - **Primary:** a CAS market sell at 15:20–15:24 IST, at the auction price. A sell limit outside the ±3% band is rejected. With no equilibrium, the close is the reference price and the order is unfilled.
  - **Fallbacks:** the post-close session (15:50–16:00), then the next opening auction.
  - **None carried out:** "exit not executed": the position stays open and marked, counts in the brake, and the chain is re-attempted the next session.
  - **History:** before 3 Aug 2026, the 15:00–15:30 VWAP close convention.
  - **Times:** IANA time zones.
- **Acceptance criteria:**
  - B.5, B.7 and B.8 pass;
  - A.1 exit = ₹1,01,036;
  - 15:20 IST = 11:50 Amsterdam on 12 Oct 2026 and 10:50 on 3 Nov 2026.
- **Refs:** §4.4 (India), A.1, B.5, B.7, B.8. **Depends on:** ST-05, ST-12, ST-57. **Owner:** S1. **Phase:** Step 1.

### ST-11: US exit chain and historical exit proxy
- **Subject:** sell US positions 15 minutes before the scheduled close, with a fallback and a historical proxy.
- **Description:**
  - **Exit time:** the scheduled close − 15 minutes, from the exchange calendar (15:45 ET; 12:45 ET on early-close days).
  - **Fill price:** the 5-minute bar ending at the exit time (post-close fetch); the proxy is used, and labelled, if the bar is missing.
  - **Fallback:** the next open; otherwise "exit not executed".
  - **Historical proxy:** close × a factor drawn from the **measured 15:45-to-close distribution produced by ST-46**, with common random numbers across policies and repeated simulations with their spread. A difference smaller than the spread is "advantage not established".
- **Acceptance criteria:**
  - A.2 exit = €885.68;
  - 15:45 ET = 21:45 / **20:45** / 21:45 Amsterdam on 12 Oct / 27 Oct / 3 Nov 2026; 12:45 ET on 27 Nov 2026;
  - competing policies receive identical proxy draws;
  - the proxy refuses to run without an ST-46 distribution record.
- **Refs:** §4.4 (US), A.2. **Depends on:** ST-09, ST-12, ST-46. **Owner:** S1. **Phase:** Step 1.

### ST-12: Marking, liquidation value and daily equity
- **Subject:** value each account at every close, including the exit costs of open positions.
- **Description:**
  - **Mark:** at the official close (US: at the §4.7 mark rate). Open orders are not equity.
  - **Liquidation value:** close − estimated exit costs, computed **at account level**: one date charge for all positions sold together, DP per scrip, and the US FX markup.
  - **Output:** `account_equity_daily` (cash, reserved, positions, liquidation value, equity, peak, drawdown, brake state).
  - **Dividends (DC-12),** in every account (forward, rehearsal and replay). Stored prices are not dividend-adjusted (`collectors/prices.py`, `auto_adjust=False`), so without this every ex-date price drop would be a loss with no dividend.
    - **Eligibility (ordinary cash dividends, India and US):** a holding earns the dividend if it was **bought before the ex-date** and still held when the market opens on the ex-date. A buy that fills **on** the ex-date earns nothing; a sale **on** the ex-date (CAS, post-close or the US 15:45 exit) keeps the entitlement.
    - **Amount basis:** the dividend per share must be on the same share basis as the holding (as-traded shares, ST-30). A per-share amount that the source has adjusted for a later split or bonus is converted back to as-traded before use.
    - **Payment:** the entitlement is booked on the ex-date as a receivable; it counts in equity (B_t and L_t) from then on.
      - **Forward and rehearsal accounts (money actually available):** the cash becomes **spendable only on a verified payment date** from an allowlisted source (an exchange or regulator announcement, or a company filing that states the payment date), **or on a recorded receipt**. Until then it stays a receivable that cannot fund any order, however much time has passed. Unresolved receivables are listed in every account report.
      - **Historical replay:** where no payment date is recorded, the replay may release the cash on an **assumed** payment date (a dated parameter per market). Every result that depends on it is labelled "assumed dividend timing", and a sensitivity reports whether a later assumed date, or never spendable within the window, changes the result. The assumption is never described as a guaranteed latest date.
      - **Missing amount or unknown share basis:** the affected account result is marked **incomplete** for that period and listed. It never silently becomes zero income.
    - **Tax:** withholding is the dividend's tax, recognised **once** through the tax bridge (ST-15 to ST-17). Rates are dated, owner-confirmable parameters, with labelled defaults in the tax stories.
- **Acceptance criteria:**
  - B.29 and I-1 pass;
  - an independent recomputation of a fixture equity curve matches to the cent;
  - the dividend chain passes integrated fixture I-7 (ST-55);
  - **eligibility fixtures:**
    - a buy that fills at the open on the ex-date gets no entitlement;
    - a holding bought before the ex-date and sold at the close on the ex-date keeps it;
  - **unconfirmed dividend cannot fund a purchase:** in a forward account, a dividend with no verified payment date and no recorded receipt cannot fund an order on day 31 after the ex-date, or on any later day; the order is skipped for `insufficient_free_cash` while equity still includes the receivable (test);
  - **replay timing sensitivity:** a replay with an assumed payment date labels the dependent results and reports the alternative-timing result beside them (test);
  - **incomplete, not zero:** a dividend event with no amount, or with an unknown share basis, marks that account period "incomplete" and lists it; the ledger does not book zero income (test);
  - **amount basis:** a dividend whose source amount was adjusted for a later 1:1 bonus is credited at the as-traded per-share amount (twice the adjusted figure) on the as-traded holding (test).
- **Refs:** §4.2, §8.6 (liquidation value), B.29. **Depends on:** ST-05, ST-07, ST-09. **Owner:** S1. **Phase:** Step 1.

### ST-13: Cash interest tied to the account plan
- **Subject:** interest on idle cash only with the plan that pays it.
- **Description:**
  - **Rates:** dated parameters. US BUX Plus: 1.50% default, 1.75% sensitivity, with the €2.99 monthly fee. India: 0% default, 3% sensitivity.
  - **Accrual:** daily, actual/365; credited monthly.
  - **Plan fee:** booked through ST-05, never twice.
- **Acceptance criteria:**
  - B.13 and I-2 pass;
  - a test fails if interest is credited without the fee;
  - a rate change applies from its date.
- **Refs:** §4.2 (interest). **Depends on:** ST-05, ST-07. **Owner:** S1. **Phase:** Step 1.

### ST-14: Risk rules and the loss brake
- **Subject:** position limits, sector cap, results blackout and the 10% drawdown pause.
- **Description:**
  - **Limits:** at most 3 positions **counting open orders**, at most 2 per sector, and one per ticker (`already_held`, including a pending order).
  - **Results blackout:** from the day before a company's results until the day after.
  - **Loss brake:** at ≥ 10% below the peak, new entries pause; exits continue. Restart: a real approval (rehearsal); otherwise the 5-session assumption, with 10 sessions and "never" as sensitivities, labelled.
  - **Gap risk:** reported per position.
- **Acceptance criteria:**
  - B.9 passes;
  - a fixture with 2 positions + 1 pending order blocks a fourth candidate;
  - a pending order in a sector counts toward the sector cap;
  - every skip has a reason.
- **Refs:** §4.9, §9.3. **Depends on:** ST-12. **Owner:** S1. **Phase:** Step 1.

### ST-15: India tax: short-term gains, deductibility and TDS scenarios
- **Subject:** India tax per financial year, with TDS as a credit, never a second tax.
- **Description:**
  - **Tax:** STCG at 20% + 4% cess per financial year (1 Apr – 31 Mar), on taxable gain = sale value − cost (including stamp duty) − transfer expenses.
  - **Deductibility:** STT is never deducted; DP and NRI charges are not deducted by default (sensitivity: deducted).
  - **Losses:** offset within the year; carried forward at 0 (sensitivity: at the full rate).
  - **TDS as four amounts:** available cash, credit receivable, the **single** tax expense, and settlement.
  - **Withholding scenarios:** W1 per sale; W2 year-to-date netting; W3 proceeds-block stress (25%, released at the end of T+1, TDS applied after release, losses offset).
  - **Dividends (DC-12):** India dividend income and its withholding are a declared scenario: the default treats the withholding as the final tax on the dividend, at a dated rate (default 20% + 4% cess, owner-confirmable); a sensitivity uses another rate. Dividend tax is never mixed into the STCG computation and never expensed twice.
  - **Refund:** 31 Dec after the year end (sensitivity: 6 months later); face value (sensitivity: discounted).
- **Acceptance criteria:**
  - A.1 tax passes (₹2,993.85; ₹622.72; ₹1,731.66);
  - B.18, B.20, B.23, B.34 and I-3 pass;
  - **DC-4:** a test fails if the **tax expense** recognised for a year differs from that year's computed liability, or if any tax amount is expensed twice. Gross withholding above the liability (₹1,000 against ₹600) is valid and becomes a refund receivable.
- **Refs:** §4.8 (India), A.1, B.18, B.20, B.23, B.34, DC-4. **Depends on:** ST-05, ST-07. **Owner:** S1. **Phase:** Step 1.

### ST-16: Netherlands Box 3 scenarios
- **Subject:** the marginal Box 3 effect per calendar year, against a savings counterfactual.
- **Description:**
  - **Deemed regime:** 2026 rates for 2026 only (6.00% / 1.28%, at 36%) on 1 January holdings. Later years are "unknown" (sensitivity 6.00–7.78%; the governing case uses 7.78%).
  - **Funding origin:** the default is a savings counterfactual. The 2026 difference between policies is €0, while the absolute view shows the counterfactual's tax.
  - **Counter-evidence:** min(deemed, actual) with the floor at zero and no carry-forward, under scenarios C0, C1 and C2. Costs are not deductible.
  - **Anti-arbitrage:** flagged only when the shift straddles 1 January **and** is reversed within ≤ 3 months.
  - **Other scenarios:** the 2028 system as its own scenario; Box 3 on the India account's value.
  - **Dividends (DC-12):** under the deemed regime (the governing C0), a dividend affects Box 3 only through the cash it adds to a later 1 January balance; under the counter-evidence scenarios C1 and C2 and the 2028 system, the gross dividend is part of the actual return. Foreign withholding (US default 15%) is a declared scenario: a final cost by default, credited as a sensitivity.
- **Acceptance criteria:**
  - B.15, B.17, B.26, B.32 (€0 / €36) and B.37 pass;
  - the scenario name appears on every figure.
- **Refs:** §4.8 (Netherlands). **Depends on:** ST-12. **Owner:** S1. **Phase:** Step 1.

### ST-17: Tax bridge, period attribution and liquidation tax
- **Subject:** keep before-tax equity independent of tax flows, and count every tax exactly once.
- **Description:**
  - **Bridge:** L_t, T_t, and B_t = L_t + T_t. Tax flows only move value between ledger lines; withholding and blocks still limit trading cash. **Dividend withholding** (DC-12) enters T_t exactly once, as the dividend's tax; the payment itself creates no income.
  - **Attribution:** NL pro rata by days (sensitivity: full year); India by financial year.
  - **Liquidation tax:** the account-level ΔTax_liq, with one date charge.
  - **End figures:** marked after-tax wealth, and money remaining upon liquidation (this one governs S2 and S3).
  - **Governing scenarios:** exactly as registered in §4.8, with both-direction headline flags.
  - **Labels:** India figures carry "after Indian tax only" unless the governing scenario adds Dutch tax.
- **Acceptance criteria:**
  - B.19, B.35, B.36 and B.38 pass;
  - I-6 passes: a full year of mixed trades with W1 withholding, recognition, credit application and refund keeps B_t equal to the before-tax ledger at every step, and after-tax equity reflects each year's tax expense exactly once;
  - a test fails if a non-governing scenario is used for S2 or S3.
- **Refs:** §4.8, §8.6. **Depends on:** ST-12, ST-15, ST-16. **Owner:** S1. **Phase:** Step 1.

### ST-18: Decision and order-event audit trail
- **Subject:** record every decision, order event, fill and cash movement with its provenance.
- **Description:** `account_decisions` (cut-off, input snapshot ids, decision and reason, L, quantity, reservations), `account_order_events` (the §6 types), `account_fills` (FX observation id and variant) and `account_cash_ledger` (reason, unit and deductibility; reasons include `dividend_receivable`, `dividend_paid` and `dividend_withholding`).
- **Acceptance criteria:**
  - every account figure can be traced to its rows;
  - a later event never erases an earlier one;
  - a look-ahead test proves every decision references only data available at its cut-off.
- **Refs:** §6. **Depends on:** ST-02. **Owner:** S1. **Phase:** Step 1.

### ST-19: Operating-cost tracker and the two economic views
- **Subject:** measure what each AI component costs, and charge it correctly.
- **Description:**
  - **Tracker:** `operating_costs` per component per run, for the §5.1 components **plus the graph-builder and the judge's monthly check of its edges** (DC-1, ST-56). Tokens, list-price value and billing basis are recorded; results are shown under each of the three billing arrangements of DC-10 until the arrangement in force is recorded. A monthly report per market and component.
  - **Deployment economics:** each policy is charged the full cost of every component it needs (§5.2 table, plus DC-1: the graph-builder and its check are charged to `acct.ai.v1`). US policies also carry the plan fee.
  - **Owner's total view:** actual bills, each counted once.
  - **Reconciliation:** a table showing the components add up to the bill.
  - **Accruals:** per-token cost on the day of the run; fees daily pro rata.
- **Acceptance criteria:**
  - B.6 and B.16 pass;
  - I-4 passes: a shared component (the news analyst) appears **in full** in each deployment view that needs it (rule, news and AI) and **once** in the owner's total view, and the reconciliation balances;
  - token value is never treated as a bill unless the basis says so.
- **Refs:** §5.1, §5.2, DC-1. **Depends on:** ST-02. **Owner:** S1. **Phase:** Step 1.

### ST-57: Live instruction and acknowledgement infrastructure
- **Subject:** the Slack reminders and "Done" buttons the rehearsal account needs (§10 lists them in Step 1).
- **Description:**
  - **Reminders:** a Slack reminder with a "Done" button for each required action type (the morning order; India auction, post-close and next open; US exit and next open), via `/slack/interactions`, at the correct Amsterdam time from IANA time zones.
  - **Events:** each tap or miss is stored as an append-only `account_order_events` row (`owner_ack`, `ack_missed`).
  - **Restart:** an owner restart-approval event for the loss brake.
- **Acceptance criteria:**
  - reminders fire at the correct Amsterdam times on the time-zone fixtures;
  - a tap and a miss are each recorded;
  - a missed action does not imply the next one;
  - a tap is labelled a paper instruction.
- **Refs:** §4.6, §10 (Step 1 components). **Depends on:** ST-18. **Owner:** B6. **Phase:** Step 1.

### ST-55: Integrated accounting fixtures
- **Subject:** prove that the accounting pieces work together, not only one by one.
- **Description:** seven end-to-end fixtures, each run through the full ledger:
  - **I-1:** two open India positions liquidated hypothetically on the same date incur **one** ₹200 date charge.
  - **I-2:** the BUX €2.99 plan fee is deducted **exactly once** per account and month across the cost, interest, operating-accrual and cash-comparator paths.
  - **I-3:** the W3 block is released at the end of T+1; the actual TDS is booked as a credit at release; buying power from T+2 is correct under both buying-power rules.
  - **I-4:** a shared operating component appears in full in every standalone deployment view that needs it and once in the owner's actual-bill view.
  - **I-5:** every policy account of a market starts with the same C₀ and the same funding conversion.
  - **I-6:** a year of mixed trades through withholding, recognition, credit application and refund preserves the before-tax bridge, and expenses each year's tax once.
  - **I-7 (DC-12), dividend chain** (illustrative fixture values: 58 shares, ₹10 per share, a ₹10 price drop, 20.8% withholding):
    - on the ex-date, before-tax equity B_t is unchanged (the ₹580 price drop is offset by the ₹580 gross entitlement), and the ₹120.64 withholding enters T_t once (L_t −₹120.64);
    - on the pay date, ₹459.36 of cash arrives and B_t, L_t and T_t do not change: no income is recognised again;
    - buying power rises only from the pay date.
- **Acceptance criteria:**
  - all seven pass, each with its expected outcome, actual output and a reconciliation to the ledger.
- **Refs:** §4.2, §4.5, §4.8, §5.2, §8.6; ChatGPT review point 9. **Depends on:** ST-03 to ST-19. **Owner:** S1. **Phase:** Step 1.

---

## Epic E2: Routine changes

### ST-20: Whole-system budget guard
- **Subject:** hold total spend to a $250-a-month target with tiered pauses, and report any excess.
- **Description:**
  - **Check:** the spend to date plus committed spend, before each paid step (v16 §5.3).
  - **Committed spend (DC-10):** the month's fees already due (a subscription or plan fee billed for the month) plus the cost of any paid step already started. Future scheduled runs are **not** committed, because the guard itself can cancel them. v16's tier table calls this total the "projected month spend"; the text's definition governs.
  - **v16's check, unchanged:** before each paid step, the spend to date plus committed spend is compared with the tiers. The step that is admitted can still cross a threshold by its own cost; that **excess is recorded** (step, amount) and reported monthly. The builder may add a tighter admission rule only as a registered change.
  - **Scope:** one guard for the whole system, both markets, with steps taken in UTC order across the two market calendars.
  - **Day-by-day simulation:** the guard runs as a pure function of (the cost schedule, the step order, the calendar), so that replays and forward runs apply it identically.
  - **Tiers:**
    - ≥ 70%: Opus work stops, **including the graph-builder's monthly refresh and the judge's check of its edges** (DC-1). When the refresh pauses, the stored connection map stays in use with its age shown;
    - ≥ 85%: the AI traders pause, and missing calls count as failures;
    - ≥ 95%: the news analyst and claim checker pause. Degraded behaviour: a zero news shift, flagged `degraded_news`;
    - 100%: only unpaid steps run.
  - **Notices:** a Slack note at each tier.
  - **Disclosure:** each policy's degraded or paused days are disclosed, as are the floor cost and every recorded excess. The ceiling is described as "a target", never "guaranteed".
- **Acceptance criteria:**
  - B.21 passes;
  - each tier triggers on a fixture month;
  - **guard simulation fixture (fixture costs, not a claim about real costs):** one paid step a day costing $16, a $250 ceiling and 21 sessions, with the fixture's rule that a step's cost is unchanged when a tier pauses part of it. Under v16's check (spend to date before the step): Opus stops from day 12 ($176 ≥ $175), the traders from day 15 ($224 ≥ $212.50), news from day 16 ($240 ≥ $237.50), and only unpaid steps run from day 17 ($256 ≥ $250). Day 16's admitted step takes the month to $256, so an **excess of $6 is recorded and reported** (test);
  - a fee due for the month counts as committed from the month's first day (test).
  - the graph-builder pauses at 70%;
  - the tested tier configuration and behaviour are stored as a versioned configuration (their inclusion in the freeze manifest is checked by **ST-42** in Step 3, not here, so that this story can finish at G1).
- **Refs:** §5.3, B.21, DC-1, DC-10. **Depends on:** ST-19. **Owner:** B17. **Phase:** Step 1 (§10 lists the budget guard in Step 1; required at G1).

### ST-21: Deterministic steps as plain scheduled scripts
- **Subject:** run the non-AI steps without an AI session, so that deterministic work adds no paid floor cost.
- **Description:** move prices, ranges, model scores, rule strategies, accounts and settlement into scheduled scripts (§5.3, "honest limit"), with identical behaviour.
- **Acceptance criteria:**
  - one replayed session gives byte-identical outputs;
  - the guard reports a zero floor for these steps.
- **Refs:** §5.3, §5.2. **Depends on:** ST-20. **Owner:** B17. **Phase:** Routine.

### ST-22: AI model schedule split
- **Subject:** Sonnet traders daily; Opus only on event days and weekly.
- **Description:**
  - **Schedule:** the §5.4 table.
  - **Frozen:** the news analyst, the claim checker and `trader-combined.md` (Sonnet) stay unchanged.
  - **Graph-builder:** keeps its monthly schedule (DC-1).
- **Acceptance criteria:**
  - a replayed week matches §5.4;
  - the hashes of the frozen agent files are unchanged;
  - a judge review before use.
- **Refs:** §5.4. **Depends on:** ST-20. **Owner:** B3 with B17. **Phase:** Routine.

### ST-23: Evening run, morning revision, Friday weekly and dashboard retirement
- **Subject:** release the routine items held on 11 Oct, as additive records.
- **Description:**
  - **Evening forecast run:** 21:30 UTC for India and 18:30 New York time for the US, Mon–Fri.
  - **Morning revision:** stored as separate additive records.
  - **Weekly run:** moved to Friday.
  - **Old page:** `dashboard.html` is retired.
  - **Isolation:** registered policies read only the frozen pre-open rows.
  - **Stage field:** every forecast record carries `forecast_stage` = `pre_open`, `evening` or `morning_revision`; a revision also carries the id of the record it revises (v16 §7.1: "separate forecast records, scored separately").
- **Acceptance criteria:**
  - revisions never replace pre-open rows;
  - every forecast record written by the routine has a valid `forecast_stage`, and every revision names the record it revises (test);
  - no registered policy reads them (freeze-guard check).
- **Refs:** §3, §7.1, §8.10. **Depends on:** ST-02. **Owner:** B17. **Phase:** Routine.

### ST-24: Four-week AI cost study
- **Subject:** a descriptive study of AI cost and behaviour after the routine change.
- **Description:** for 4 weeks after ST-22: measured cost per component (including the graph-builder if it runs), missed or failed AI calls, how often the AI changes decisions compared with `acct.noai.v1`, and degraded days.
- **Acceptance criteria:**
  - the study is built from stored records only;
  - it is labelled descriptive.
- **Refs:** §5.5. **Depends on:** ST-19, ST-22, ST-30. **Owner:** S3. **Phase:** Routine.

---

## Epic E3: Account policies (Step 3)

### ST-25: Shared execution and risk wrapper
- **Subject:** the execution and risk rules **every** trading policy shares. Selection rules are per policy.
- **Description:**
  - **Shared by all trading policies:** the entry order (L and its variants, ST-08); duplicates; allocation into free slots (3 − positions − open orders); the sector cap; the results blackout; the loss brake; free cash; the exit chains; the budget tiers; the tie order **within** a policy's own ranking (then shorter horizon, then ticker).
  - **Not shared:** the candidate source, cost gate, ranking and horizon are **policy-specific** (ST-26 to ST-29). A policy with no cost gate (`acct.simple.v1`) is never filtered or ranked by the model heuristic.
- **Acceptance criteria:**
  - on a fixture day, the wrapper places exactly the expected orders for a given ranked candidate list;
  - every skip has a reason;
  - a test proves the wrapper never applies a cost gate or g ÷ k ranking itself.
- **Refs:** §9.3 (shared elements). **Depends on:** ST-06, ST-08, ST-10, ST-11, ST-14, ST-20. **Owner:** S3. **Phase:** Step 3.

### ST-26: Policy `acct.rule.v1`
- **Subject:** the rule family's picks as an account.
- **Description:**
  - **Candidates:** `head_to_head_picks` with family = rule, pick_rule = best expected gain, status `picked`, at the pick's horizon.
  - **Cost gate:** g = p × move − (1 − p) × loss − c_new > 0, from the stored `prob_up`, `move_pct` and `loss_pct`; c_new = the round-trip cost under the new scenario at quantity and L.
  - **Ranking:** g ÷ k.
  - **Label:** "rule family (uses AI-scored news)".
  - **Deployment cost:** the news analyst and claim checker.
- **Acceptance criteria:**
  - candidates are taken only from rows recorded before the open;
  - the gate and ranking reproduce on a fixture;
  - the label is shown.
- **Refs:** §9.3, §5.2. **Depends on:** ST-25. **Owner:** S3. **Phase:** Step 3.

### ST-27: Policy `acct.ai.v1`, with abstention and failure handling
- **Subject:** the Sonnet combined trader as an account.
- **Description:**
  - **Candidates:** qualifying `strategy_predictions` of `ai.combined.sonnet.v1`; per ticker, the horizon in {1, 3, 5} with the highest g ÷ k (same formula as the pick's horizon table); same cost gate.
  - **AI "no trade":** no trade, never replaced.
  - **Missing or failed call:** no trade, counted as a reliability failure.
  - **Exploratory variant:** "fill the gap with `acct.noai.v1`", reported only.
  - **Label:** "AI decision layer (Sonnet combined trader)".
  - **Deployment cost:** the news analyst, claim checker, the trader, and (DC-1) the graph-builder and its check.
- **Acceptance criteria:**
  - B.12 passes;
  - the failure count is reported;
  - the deployment cost includes the DC-1 items.
- **Refs:** §9.3, §5.2, B.12, DC-1. **Depends on:** ST-25, ST-56. **Owner:** S3. **Phase:** Step 3.

### ST-28: Policies `acct.noai.v1` and `acct.news.v1`
- **Subject:** the model-only policy and the exploratory model-plus-news policy.
- **Description:**
  - **`acct.noai.v1`:** `base.model_only`, horizons {1, 3, 5}, same gate and g ÷ k ranking, no AI cost.
  - **`acct.news.v1`** (exploratory): `rule.model_news.v1` (news weight 1.0), horizons {1, 3, 5}, same gate and ranking, charged the news-analyst and claim-checker costs.
  - **Decomposition:** news − noai and ai − news, labelled exploratory.
  - **India note:** shown.
- **Acceptance criteria:**
  - horizons are restricted to {1, 3, 5};
  - the decomposition is never presented as confirmed.
- **Refs:** §9.3, §8.6. **Depends on:** ST-25. **Owner:** S3. **Phase:** Step 3.

### ST-29: Policies `acct.simple.v1` and `acct.cash.v1`
- **Subject:** the momentum comparator and the cash comparator.
- **Description:**
  - **`acct.simple.v1`:** active companies with 20-session momentum > 0, ranked by momentum, the top 3, held to N+5, **with no model cost gate and no model ranking**. N+1 and N+3 are exploratory.
  - **`acct.cash.v1`:** no trading selection; the same account kept uninvested under its real plan (US: the Plus rate minus €2.99 a month; India: the idle rate).
  - **Exploratory cash alternatives:** BUX Basic and a savings account.
- **Acceptance criteria:**
  - a candidate with positive momentum and a **negative** model heuristic score is still selected by `acct.simple.v1` if its momentum ranks in the top 3;
  - B.13 passes for the cash comparator;
  - the momentum ranking reproduces on a fixture.
- **Refs:** §9.3. **Depends on:** ST-25, ST-13. **Owner:** S3. **Phase:** Step 3.

### ST-30: Forward policy accounts and historical replay
- **Subject:** run the six policy accounts forward from 12 Oct, and replay what history allows over 2011–2026 on a declared retrospective universe.
- **Description:**
  - **Forward:** from the pre-open decisions recorded since 12 Oct 2026, labelled "pre-registration, exploratory" until registration. From registration onwards, the registered policies use the **deployment state snapshot** of ST-42.
  - **Historical replay:** 2011 to 9 Oct 2026, labelled development, only for policies whose inputs exist historically. Run with all execution, cost, interest and tax variants, and the US exit proxy. The replayed accounts:
    - `acct.simple.v1`;
    - `acct.noai.v1`;
    - the rule surrogate `acct.rule.v1|model-part` (`acct.rule.v1`'s pick logic and wrapper with a zero news shift, i.e. "the model part of the rule strategies", §8.2, §9.4), labelled a surrogate;
    - the H3 surrogate arm of DC-6 at w = 0.10, and the H3 scenario paths of DC-6 (ST-38);
    - the symmetric placebo pairs (ST-37).
  - **Retrospective research universe (DC-8); not a point-in-time universe.**
    - **Why:** the stored `watchlist_events` cannot supply a historical universe. All 40 events (20 per market) are `seed` events recorded on 7 Oct 2026 and effective from 7 Oct 2024. The lifecycle loader returns 0 companies per market on 3 Jan 2011, 29 Jun 2018 and 6 Oct 2024, and 20 from 7 Oct 2024 (checked on 11 Oct 2026 with `contracts.watchlist.watchlist(market, date, "collected")`).
    - **What is used:** a frozen file listing, per market, the companies whose events were recorded by 9 Oct 2026, with the sector recorded in those events. It applies to **every** replayed date.
    - **Entry:** a company enters on the first session on which every input its policy needs exists: its first bar in the stored or long-history data, plus the warm-up of the indicators and of the walk-forward model score. It never trades before that.
    - **No backdating:** nothing is written to `watchlist_events`, and the lifecycle loader is not used for the replay.
    - **Label on every replay output:** "retrospective research universe: today's 20 companies, chosen in 2024–2026 with hindsight (survivorship bias); not a historical watchlist".
    - **Known consequences, reported with every replay result:**
      - survivorship raises absolute long-only results (the H1 type); paired comparisons on the same universe are affected less, but not zero;
      - India has fewer than 20 companies in much of the selection period. The long-history cache's row counts (in the stored 15-year backtest's splice record) are 3,382 for most India companies but 1,693 for HDFCLIFE, 1,724 for SBILIFE and 2,190 for INDIGO; for the US, 3,115 for META against 3,462 for the others. These counts fit their later listings. **This story measures the exact first dates** and reports, per set and date, how many companies were eligible;
      - sectors are the 2026 classification, applied to every date.
  - **Deployment costs of replayed arms (DC-6):** each replayed arm that stands for a costed policy carries that policy's §5.2 deployment cost schedule as accruals (per-run costs on the run day, fees daily pro rata). The rule surrogate carries `acct.rule.v1`'s components; the H3 surrogate arm carries `acct.ai.v1`'s, including the DC-1 items; US arms carry the BUX Plus fee. These accruals reduce cash and equity, so they can change later sizing, as in §4.2. Each of the three billing arrangements of DC-10 is run, with ST-20's guard simulated day by day on that arrangement's cost schedule.
  - **Replay realism (DC-12):**
    - **Corporate-action inputs (DC-12):** the long-history cache holds only OHLCV (`HISTORY_COLUMNS`: ticker, date, open, high, low, close, volume), and the stored dividend events carry an ex-date and an amount but no payment date. So the replay needs a **corporate-actions record** per company and date, collected from allowlisted sources and frozen and hashed with the cache. It holds dividends (ex-date, amount, payment date where available, and the share basis of the amount) and splits and bonuses (ex-date, ratio, and whether each price source already applied it). Gaps are listed and reported, never filled by guesswork.
    - **As-traded basis (corrected):** positions are held in as-traded shares and priced as they traded.
      - **No stored view can be assumed to be as-traded.** `ohlc_raw` / `bars_raw` show prices **as stored**, and the source (Yahoo) can already have applied later splits and bonuses. HDFCBANK on 22 Aug 2025 is stored at ₹982.30, but traded at ₹1,964.60 on NSE before its 1:1 bonus (`collectors/prices.py` documents this pair), and India has no stored adjustment records.
      - **Reconstruction:** each price source's as-traded price is rebuilt from **that source's own adjustment basis**: the cumulative factor of the splits and bonuses after the date **that the source has applied**, from the corporate-actions record. Where an as-traded source exists (NSE's bhavcopy), it is used to verify.
      - An adjustment the source has not applied is never applied, and none is applied twice.
      - Quantity, `price_above_slot`, L and tick tests all use the as-traded basis, so that no later split or bonus makes an earlier trade affordable.
      - A split or bonus changes quantity and price by its ratio, with no cash flow and no tax event.
    - **Results blackout before Oct 2023:** stored earnings dates begin on 11 Oct 2023 (India) and 12 Oct 2023 (US). Earlier dates are backfilled from allowlisted sources (SEC 8-K item 2.02 and 10-Q/10-K for the US; NSE results filings for India) where they exist. Every replayed session without a known results calendar is flagged `blackout_unknown`, and its count is reported per set. On those sessions **no blackout is applied** (labelled); a sensitivity excludes them from the experiments.
    - **Tax years:** the replay applies v16's current tax rules to every year, labelled "2026 rules applied to all years".
    - **Exposure:** the replayed comparison paths keep v16's slot = equity ÷ 3 (§8.2: "the replay's actual exposure series"). How the power analysis handles equity drift over a set is the builder's choice, judged by ST-38's properties. Placebo windows start at C₀ (ST-37).
    - **Mark rate:** every conversion, the India USD/INR or US EUR/USD alike, uses the §4.7 rule (the latest observation ≤ the event; historically, the previous day's close with its age), never the same day's close.
    - **Frozen inputs:** the long-history cache (`work/model_history/`, gitignored and re-fetchable) is frozen into a dated copy whose manifest SHA-256, one hash per file, is stored with every replay, ST-58 and ST-43 record. A re-run verifies the hashes and refuses on a mismatch.
  - **Hashes:** the universe file's hash, the cost schedule's hash and the frozen-cache manifest hash are stored with each replay run. This is the **historical analysis state**; it is never the deployment snapshot.
- **Acceptance criteria:**
  - the replay is never labelled confirmatory;
  - the forward accounts read only rows recorded before each open;
  - the full ledger reconciles;
  - the tax bridge (ST-17) and the measured distributions (ST-46) are used, not defaults;
  - the universe file lists exactly the companies whose events were recorded by 9 Oct 2026, and equals the lifecycle loader's `collected` list on every date from 7 Oct 2024 to 9 Oct 2026 (test);
  - a fixture company whose first bar is a given date D₀ is never a candidate before D₀ plus its warm-up (test);
  - the replay writes nothing to `watchlist_events` (the file set and hashes are unchanged; test);
  - the label is present on every replay output, and the eligible-company count per date is reported;
  - **dividend in replay:** a replayed position held across a stored ex-date is credited through ST-12's rule (test);
  - **real price-basis fixture (repository data):** HDFCBANK on 22 Aug 2025 reconstructs to an as-traded close of ₹1,964.60 from the stored ₹982.30 (the 1:1 bonus applied by the source). With a ₹1,500 slot and fees ignored, the as-traded basis gives `price_above_slot` (0 shares), where the stored price would have allowed 1 share (test);
  - **no double adjustment:** a fixture where the source has **not** applied a later bonus leaves the price unchanged (test);
  - **as-traded and split fixtures:**
    - a stock trading at $1,000 before a 10-for-1 split (stored adjusted price $100) is `price_above_slot` with a $975 slot on a pre-split date;
    - a held position of 10 shares at $1,000 becomes 100 shares at $100 on the effective date. Value is preserved exactly (q × P before = q × P after), with no cash flow and no tax event (test);
  - every session without a known results calendar is flagged `blackout_unknown`, and the counts are reported;
  - a re-run with one altered cache file is refused (hash mismatch);
  - **cost accrual fixture:** on a 3-session fixture history, an arm charged a fixture cost c per session ends exactly 3c (each at the §4.7 rate) below the same arm uncharged. The charge appears once in its own deployment view and is never subtracted again in a comparison (the B.16 rule);
  - the universe and cost-schedule hashes are stored with each run.
- **Refs:** §5.2, §5.3, §8.3, §9.4, DC-6, DC-8. **Depends on:** ST-26 to ST-29, ST-17, ST-19, ST-46. **Owner:** S3. **Phase:** Step 3.

### ST-31: Owner rehearsal account
- **Subject:** the account the owner actually follows, with recorded attendance.
- **Description:**
  - **Follows** `acct.rule.v1`, using the ST-57 infrastructure.
  - **Start:** the first session after deployment; never back-dated.
  - **Restart:** the loss brake restarts only on a real approval.
  - **Reported:** its difference from the `acct.rule.v1` policy account, labelled "attendance and approvals".
- **Acceptance criteria:**
  - B.5 passes in rehearsal mode;
  - acknowledgements and misses appear in the report;
  - the difference label is shown.
- **Refs:** §4.1, §4.6, §4.9. **Depends on:** ST-26, ST-57. **Owner:** S3 with B6. **Phase:** Step 3.

---

## Epic E4: Scoreboards and statistics: machinery (Step 2, on synthetic and fixture data)

### ST-32: Forecast scoreboard
- **Subject:** score each forecast on the event it was issued for.
- **Description:**
  - **P(up)** against X > O_D: Brier, log loss and reliability with Wilson intervals; by fill type (descriptive).
  - **Expected price:** MAE% and RMSE, paired against no-change.
  - **80% range:** coverage, width and interval score.
  - **Sample sizes:** the sample size and the effective sample size on every row.
  - **Revisions:** scored separately, grouped by `forecast_stage` (`pre_open`, `evening`, `morning_revision`; the field is defined in this document and written by the routine story).
- **Acceptance criteria:**
  - a forecast is never re-scored against a fill;
  - on fixture records of all three stages, each stage is scored in its own rows and never pooled (test);
  - on the rule-based replay output of `python scripts/replay.py --market india --end 2026-10-09` (2 Jan 2025 – 9 Oct 2026) it reproduces §2.4 item 5:
    - N+1 coverage 83.6% (82.1–85.2%), widths 5.73% / 5.19%, scores 7.777 / 7.745;
    - N+3 84.3% (82.4–86.3%), 8.64% / 7.34%, 11.077 / 10.856;
    - N+5 85.4% (83.1–87.6%), 10.88% / 8.99%, 13.697 / 13.277.
- **Refs:** §7.1, §2.4. **Depends on:** ST-02. **Owner:** S2. **Phase:** Step 2.

### ST-33: Decision scoreboard
- **Subject:** the net outcome of each buy, skip, hold and exit choice.
- **Description:** each decision's outcome against its alternative; the fill-type breakdown; missed acknowledgements; compared with cash and the simple rule.
- **Acceptance criteria:**
  - on fixture ledgers, every decision links to its outcome and the totals reconcile.
- **Refs:** §7.2. **Depends on:** ST-18. **Owner:** S2. **Phase:** Step 2.

### ST-34: Account scoreboard and the two economic views
- **Subject:** money kept, before and after tax, in both economic views.
- **Description:**
  - **Money kept:** before tax; after tax per period and attributed; in both views.
  - **Other measures:** return on funded capital, drawdown, exposure, turnover, costs by unit and deductibility, interest, TDS, unused cash and degraded days.
  - **Index proxy:** Nifty 50 in INR and S&P 500 in EUR, labelled, reported but not tested.
- **Acceptance criteria:**
  - on fixture ledgers, the scoreboard reconciles to the cent;
  - the index proxy is labelled.
- **Refs:** §7.3. **Depends on:** ST-17, ST-19. **Owner:** S2. **Phase:** Step 2.

### ST-35: Test statistic, monthly advantage and harm stops
- **Subject:** the exact paired statistic and the risk stop.
- **Description:**
  - **Statistic:** d_t = (ΔV_A − ΔV_B) ÷ C₀ on before-tax equity, each side net of its own costs.
  - **Monthly advantage:** 21 × mean(d_t), with liquidation value at the end date.
  - **Harm stop:** below −2% a month with one-sided p < 0.01, or drawdown > 20%. A stopped hypothesis counts as not rejected.
  - **Harm test, defined (DC-7):**
    - null hypothesis: mean monthly advantage ≥ −2%; alternative: below −2%. That is, a one-sided test of mean(d_t) < −2% ÷ 21 per session, at each interim report on the sessions so far;
    - the methods are validated at 126, 189 and 250 sessions only, so a p-value at an interim length is reported as "precautionary at this length";
    - a constant d_t over the sessions so far fires the stop if it is below −2% ÷ 21 (no randomness to test), and never fires it otherwise;
    - the drawdown prong is account-level;
    - **one stop, all hypotheses:** a policy is one account. If it is stopped under any of its hypotheses (`acct.rule.v1` under H1 or H2), every hypothesis in which it is the candidate is labelled "Stopped for harm", and the rehearsal account that follows it stops too. Each stopped hypothesis keeps its α share (B.33).
  - **Which p-value (DC-7):** the registered method's. When no method is adequate (DC-7), the p-value prong fires if **any** of the six candidate methods gives p < 0.01 with an estimate below −2% a month. This is a **precautionary stopping rule**, not validated statistical evidence: a harm stop is risk control (§8.8); a false stop only ends a policy early, while a missed one costs money. The stop report names the method or methods that triggered it and states "triggered by an unvalidated method".
- **Acceptance criteria:**
  - B.16 and B.28 pass;
  - a harm stop never declares success;
  - a constant d_t equal to −2.5% ÷ 21 per session fires the stop; a constant −1.5% ÷ 21 does not;
  - a stop of `acct.rule.v1` under H2 labels H1 "Stopped for harm" too, and stops the rehearsal account (test);
  - with no adequate method, a fixture in which exactly one candidate gives p = 0.005 at −2.5% a month fires the stop, and the report names that method with the "unvalidated" statement; one in which all give p ≥ 0.01 does not, unless the drawdown prong fires.
- **Refs:** §8.6, §8.8, DC-7. **Depends on:** ST-17, ST-36. **Owner:** S2. **Phase:** Step 2.

### ST-36: The six inference candidates
- **Subject:** the finite set of inference methods.
- **Description:**
  - (a) HAC with the Andrews bandwidth;
  - (b) HAC with bandwidth ⌊4 (n/100)^(2/9)⌋;
  - (c) stationary bootstrap with the Politis–White block length;
  - (d) the same with twice that length;
  - (e) circular block bootstrap, block 10;
  - (f) circular block bootstrap, block 20.
  
  Each returns a one-sided p-value and a one-sided lower bound at a given α. **Exact specification (no implementation choice left):**
  - **(a), (b):** Newey–West Bartlett kernel; (a) uses the Andrews (1991) AR(1) plug-in bandwidth; the statistic is mean ÷ HAC SE against the standard normal; the bound is mean − z₁₋α × SE.
  - **(c), (d):** stationary bootstrap, expected block length from Politis and White (2004) with the Patton, Politis and White (2009) correction ((d) doubles it); B = 1,999 replicates.
  - **(e), (f):** circular block bootstrap, B = 1,999.
  - **Bootstrap p-value and bound:** for (c) to (f), the p-value is the share of bootstrap means of the centred series (d − d̄) that are ≥ d̄, and the bound is d̄ − the (1 − α) quantile of (bootstrap mean − d̄). These are percentile forms, not studentised.
  - **Harm test (lower tail, DC-7):** with μ₀ = −2% ÷ 21 per session, (a) and (b) use z = (d̄ − μ₀) ÷ SE with p = Φ(z); (c) to (f) use p = the share of centred bootstrap means (bootstrap mean − d̄) that are ≤ d̄ − μ₀.
  - **Seeds:** each bootstrap's seed is derived from (the experiment's stream, the method letter).
  - **Zero-variance input:** any method returns "undefined".
- **Acceptance criteria:**
  - each matches a published or textbook example, and a fixed-seed fixture reproduces its p-value to 4 decimals;
  - nothing outside the set can be selected.
- **Refs:** §7.4, §8.5. **Depends on:** none. **Owner:** S2. **Phase:** Step 2.

### ST-37: Placebo validity harness (machinery)
- **Subject:** select and verify an inference method on placebo pairs exactly as v16 §8.5 describes, with every outcome branch defined.
- **Description:**
  - **Placebo pairs (v16 §8.5).** One family per declared scenario of DC-6: two arms that pick at random from the same eligible candidates (DC-8 universe, inputs present, outside blackout), under the same wrapper, execution, allocation, constraints, brake and costs, starting at C₀.
  - **How many orders, and when (DC-9).** v16 says "random selections" but not how many or when. Each placebo arm submits, on each decision day, one pre-open order per pre-open order of the scenario's **more active arm** (the arm with more orders in the set), with that order's horizon and gate decision. "Order" always means a pre-open submitted order, never a fill. For H3, overlap is set by the scenario's ρ through a shared random draw.
  - **Informative families:** a family whose arms trade too rarely to give usable windows is reported as uninformative and takes no part. The threshold is set by the builder and stated in the record.
  - **Windows:** 126, 189 and 250 sessions (v16 §8.2's lengths), each entirely inside its set.
  - **Sets and seeds (v16 §8.5):** selection windows within 3 Jan 2011 – 29 Jun 2018 and seeds 1–9,999; verification windows within 2 Jan 2019 – 9 Oct 2026 and seeds 10,001–19,999.
  - **Power experiments (v16 §8.5):** a null experiment plus a known edge δ on one arm, at **δ = 0.5% and 1%** a month, on **both** sets.
  - **Tolerance (v16 §8.5, literal):** a method's null rejection rate must be ≤ α + 2 Monte Carlo SE in every informative family, at every length. Windows with no variation cannot be tested and are reported as such; they never lower a rejection rate.
  - **Selection and verification (v16 §8.5 steps 3 to 5):**
    - among qualifying methods, the highest power at δ = 1% (the length used for this choice is fixed in code before any run and stated);
    - verification runs once and needs **at least one informative family**: an empty set never counts as a pass;
    - no substitution, no retuning, no second run.
  - **Structured outcome, passed unchanged to ST-38 and ST-39:**
    - `adequate` with the method; or
    - `none_adequate` with its reason: `no_informative_family`, `no_informative_family_verification`, `failed_qualification` or `failed_verification`.
  - **Inputs:** set-local (computed from the set's own sessions); point-in-time (walk-forward model scores, built only from earlier data, in both sets); fixed nuisance inputs, the only exception (ST-46's FX values, the US exit proxy, DC-10's historical cost schedule). Validation is **conditional on these frozen execution assumptions**, and every report says so.
  - **Reported (v16 §8.5 item 6):**
    - every candidate's rejection rates and powers at both δ, per family, length and set, with Monte Carlo SE and experiment counts;
    - the share of untestable windows;
    - **the cost of the literal tolerance:** the number of checks per hypothesis, and the simulated probability that an exactly sized test fails at least one of them, on the real window and family layout;
    - the limitation statement: "These placebos represent comparisons like them; they do not automatically validate inference for AI-driven, adaptive policies with different exposure and failure patterns."
- **Acceptance criteria (properties; synthetic data and a fixture wrapper stub; no Step-3 policy code needed):**
  - **Zero edge by construction:** swapping a pair's labels with the same seed gives exactly −d_t, and on a synthetic history drifting +2% a month in one half and 0% in the other, the mean null statistic is 0 within 2 Monte Carlo SE **in each half**.
  - **Known edge:** the mean power-experiment statistic equals δ within 2 Monte Carlo SE.
  - **Tolerance works:** a synthetic exactly sized test passes at the stated rate; a deliberately oversized one (for example, rejecting 3% at α = 1%) fails.
  - **Untestable windows:** a method that rejects 2.5% of testable windows, with 60% untestable, reports 2.5%, not 1.0%.
  - **Order meaning:** placebo orders follow the driver's pre-open orders only, never its fills (test).
  - **Branches:** each `none_adequate` reason comes from its own fixture; an empty verification set never yields `adequate`; a second verification run or a substitution is refused.
  - **Isolation:** perturbing every verification-period price and re-running the whole chain changes selection outputs only through the listed nuisance inputs.
  - **Determinism, scope and fixtures:**
    - two runs are byte-identical;
    - every window and seed lies in its set and range;
    - the limitation and "conditional" statements are present;
    - B.25 passes.
- **Refs:** §8.2, §8.5, B.25, DC-6, DC-7, DC-8, DC-9. **Depends on:** ST-36, ST-46. **Owner:** S2. **Phase:** Step 2.

### ST-38: Power and the window rule (machinery)
- **Subject:** v16 §8.2's power analysis under the replay's measured dependence, and v16 §8.3's window rule.
- **Description:**
  - **Declared scenarios (DC-6),** fixed before any run, each a replayed pair (arm A against arm B, with deployment costs, under each billing arrangement of DC-10):
    - **H1:** A ∈ {rule surrogate `acct.rule.v1|model-part`, `acct.noai.v1`, `acct.simple.v1`} against cash;
    - **H2:** A ∈ {rule surrogate, `acct.noai.v1`} against `acct.simple.v1`;
    - **H3:** the model-only account against an AI-like account whose orders follow an exposure source (the DC-6 surrogate at w = 0.10, or `acct.simple.v1`), copying the model-only account's orders with probability ρ ∈ {0.8, 0}, v16 §8.2's two ends; many replayed paths per scenario.
  - **The series:** each scenario's daily paired difference d_t, net of everything that varies with activity: fees, cash interest and per-run operating costs. Only fixed, pre-declared calendar fees may be set aside.
  - **Power (v16 §8.2):** for each hypothesis, the power to detect a true 0.5% a month, and the probability of establishing more than 0.5% when the truth is 1%, at 126, 189 and 250 sessions, **under the dependence measured in the replay**.
    - Because about seven years per set give only an imprecise estimate of that dependence, the power that sets the window must rest on a **cautious (upper) estimate** of the variance of an L-session mean.
    - The builder chooses the method; it must meet the coverage property below.
    - The paths of one H3 scenario share one market history, so they must not be counted as independent histories.
  - **The selected method's own placebo power** (ST-37) is reported beside this figure (v16 §8.5 item 6). It does not enter the window rule.
  - **Labels on every power figure:** "analytical planning approximation (v16 §8.2)" for the figure that sets the window, and "demonstrated for the selected test (placebo construction)" for the method's placebo power. The report never presents the first as a property of the selected test.
  - **Governing scenario (DC-6):** the lowest power at each length among the **usable** scenarios (the lower envelope).
  - **Which scenarios are usable (one rule, DC-6):** a scenario is **excluded** from the power calculation, with its reason recorded, in either of two cases:
    - `no_orders`: neither arm submits an order in the set;
    - `zero_variance`: orders are submitted, but the paired series d_t has zero sample variance in the set (for example, orders that never fill, leaving only a constant difference).

    Both are excluded because no comparison variability can be estimated from them. All other scenarios are usable.
  - **Window rule (v16 §8.3, unchanged):** the shortest of 126, 189 or 250 sessions at which the governing power for a true 0.5% is ≥ 80%; if none, 250, with the low power stated.
  - **Billing arrangement (DC-10):** computed for each arrangement; the arrangement in force, recorded with evidence at registration, governs.
  - **Branches:**
    - `none_adequate` from ST-37 → power `not_computed`, window 250;
    - no usable scenario (every scenario `no_orders` or `zero_variance`) → power `not_established`, window 250, with the reasons listed.

    One structured record per hypothesis and arrangement.
  - **Expected outcome, stated for the owner:** with a cautious estimate and about seven years of data, power for a 0.5%-a-month edge will usually stay below 80% even at 250 sessions. So the window will usually be 250, and a non-rejection will usually be labelled "Inconclusive", not "Failed".
- **Acceptance criteria (properties; synthetic series; no policy code needed):**
  - the §8.2 illustrative table reproduces (0.42 / 0.53 / 0.84 / 1.68 / 3.37%; 178 / 286 / 709 / 2,833 / 11,331). This is a calculator check only;
  - **coverage of the cautious estimate,** with about 1,850 sessions per simulated series and at least 1,000 series per process: the cautious variance of the L-session mean is at or above the true value in **≥ 95%** of series, at each of 126, 189 and 250 sessions, for four processes:
    - independent standard normal days;
    - AR(1) with coefficient 0.8 and unit variance;
    - an equal-weight MA(62) of standard normal shocks (long dependence, ChatGPT's example);
    - **GARCH(1,1) with ω = 0.02, α = 0.10, β = 0.88 (unit unconditional variance) and standardised Student-t shocks with 6 degrees of freedom,** like real daily trading P&L (volatility clustering, fat tails).

    These four processes, their parameters and their seeds are declared before any run.

    If the builder finds no method that reaches 95% on the fourth process, the story **stops and reports the achieved coverage** to the owner and ChatGPT before ST-58 runs. It never ships a lower coverage silently;
  - **width is reported too (a cautious estimate must still be useful):** for each process and length, the median and 90th percentile of (cautious estimate ÷ true value), and the power the window rule would compute from the cautious estimate against that computed from the true value. The judge reviews these at G2. A method that reaches coverage only by being so wide that every hypothesis becomes "Inconclusive" regardless of the data is reported as such, and does not pass review silently;
  - **accuracy check:** with the true variance supplied, the power calculation reproduces v16 §8.2's formula exactly (the table above);
  - **series content:** a fixture whose gross trading results are constant but whose per-order fees vary keeps non-zero variance; a fixed monthly plan fee does not change the variance (test);
  - **active against cash:** with arm B never trading, the series is arm A's own net daily result minus B's cash interest and fees (test);
  - **window rule:** governing powers of 0.70 / 0.83 / 0.94 give 189 sessions; 0.60 / 0.70 / 0.79 give 250 with the low-power statement (test);
  - **branch fixtures:** `not_computed`; `not_established`; a `no_orders` scenario (neither arm orders); a **`zero_variance` scenario whose arms submit orders that never fill**. Both are excluded, with their reasons, and neither enters the envelope (test);
  - B.27 passes;
  - no forward outcome is read (test).
- **Refs:** §8.2, §8.3, §8.5, §8.6, B.27, Appendix E, DC-6, DC-9, DC-10. **Depends on:** ST-37. **Owner:** S2. **Phase:** Step 2.

### ST-39: Success conditions, Bonferroni, lower bounds and labels
- **Subject:** each hypothesis's single label, with bounded wording.
- **Description:**
  - **Tests:** H1–H3 per market, each tested once at its own end at α_h = 0.01 one-sided (0.03 per market; 0.04 reserve). One-sided lower bounds at 0.01.
  - **S1:** before-tax rejection. **S2:** after-tax advantage ≥ 0.5% a month (money remaining upon liquidation, governing scenario). **S3:** own after-tax money > 0.
  - **Labels:** exactly one per hypothesis, in the §8.9 precedence, with the mandatory qualifiers. The "Inconclusive" branch uses the **registered** power from ST-43. It reads ST-38's structured record: `power_status` `not_established` counts as below 80%, and `method_status` "none_adequate", for any reason, goes to the no-adequate-method branch below.
  - **Money conditions and billing (DC-10):** S2 and S3 use the **actual dated costs** of the window (the operating costs and bills recorded by ST-19, including any billing change on its date), because they are about money actually kept. The figure computed under the arrangement recorded at registration is shown beside them, labelled "registered assumption", and never decides the label. Power and the window remain those registered.
  - **Constant difference:** a window whose d_t is constant gives S1 "not met" (no method result exists).
  - **No adequate method (DC-7):** the §8.9 precedence still applies: (1) "Stopped for harm" when a harm stop fired, otherwise (2) "Descriptive only". The report shows the point estimate with the intervals of all six candidate methods, each labelled "unvalidated".
  - **Beside each label:** the conditional after-tax lower bound; no label claims an after-tax minimum.
- **Acceptance criteria:**
  - B.22, B.24 and B.33 pass;
  - **one fixture per label branch** (all six labels) produces exactly that label;
  - **precedence with no adequate method:** "none adequate" together with a 21% drawdown gives "Stopped for harm"; "none adequate" with no harm stop gives "Descriptive only";
  - **integrated path fixture (ST-37 → ST-38 → ST-39, run through the real code of those three stories on injected synthetic series; no policy code needed):**
    - (i) every method fails qualification → "Descriptive only", or "Stopped for harm" when a 21% drawdown also occurred;
    - (ii) method adequate, no usable scenario (all `no_orders` or `zero_variance`), S1 not met → "Inconclusive" (`not_established` counts as below 80%);
    - (iii) method adequate, registered power ≥ 80% at the registered window, S1 not met → "Failed the success conditions";
    - (iv) method adequate, registered power below 80% at 250, S1 not met → "Inconclusive";
    - (v) method adequate, S1, S2 and S3 met, the 99% lower bound below 0.5% a month → "Positive before-tax advantage supported; after-tax estimate meets target";
    - (vi) `none_adequate` (any reason) and **no harm stop** → "Descriptive only", whatever the estimate shows;
    - (vii) `none_adequate` **with** a 21% drawdown → "Stopped for harm" (precedence);
  - **billing-change fixture:** trading earns €100 over the window; a billing change on day 40 adds €150 of actual operating costs to the candidate. The actual-money result is −€50, so S3 is not met and no profitability label is given. The "registered assumption" figure (+€100) is shown, labelled, and does not change the label (test);
  - the qualifier texts match §8.9 word for word.
- **Refs:** §5.1, §8.6, §8.7, §8.9, DC-6, DC-7, DC-9, DC-10. **Depends on:** ST-35, ST-36, ST-17, ST-38. **Owner:** S2. **Phase:** Step 2.

### ST-40: Interim reports
- **Subject:** descriptive reports about every 8 weeks.
- **Description:** estimates, intervals and the harm-stop check, labelled "interim, not a conclusion". No efficacy decision.
- **Acceptance criteria:**
  - no interim report contains a success label;
  - harm stops appear with their reasons.
- **Refs:** §8.8. **Depends on:** ST-35, ST-39. **Owner:** S2. **Phase:** Step 2.

---

## Epic E5: Registration and freeze guard

### ST-41: Freeze guard and validated deviations
- **Subject:** detect any change to a registered policy's inputs, and accept only a valid correction.
- **Description:**
  - **Hashes:** taken at registration for every manifest entry (ST-42) and every protected state snapshot.
  - **Valid deviation:** must name the changed entry, its **old and new hashes matching the actual change**, the affected policies, and the category "correctness bug" with a description. It must be accompanied by the before-and-after results for the affected policies.
  - **Deliberate change:** creates a new version with its own window. The old window ends **only for the registered policy that is actually altered**. Registering a separate challenger does **not** end the window of its unchanged incumbent or comparator.
  - **Update rules keep running:** the monthly refit, the strongest-strategy ranking, `model_news_update` if applied, and the graph-builder's monthly refresh as its registered update rule (DC-1).
  - **Not applied:** weekly-review or research-director proposals that touch frozen inputs.
  - **Before registration:** changes are logged.
- **Acceptance criteria:**
  - B.14 passes;
  - the guard passes again **only** with a valid deviation row;
  - it stays failed for a row with wrong hashes, a missing affected policy, a non-correctness category, or missing before/after results;
  - a deliberate change is refused as a deviation and creates a new version;
  - registering a challenger leaves the incumbent's window running (a test).
- **Refs:** §8.10 (rules). **Depends on:** ST-02. **Owner:** S2. **Phase:** Step 2.

### ST-42: Generated functional manifest, protected state and detection test
- **Subject:** prove the guard covers everything a decision depends on, including stored state.
- **Description:**
  - **Manifest:** generated as the transitive import closure of the decision and accounting entry points, plus every config, SQL view and agent-instruction file read at run time, traced during a full replay of one session. This includes the **producers of agent outputs the decisions read**: the graph-builder's instructions and its refresh rule (DC-1).
  - **Deployment state snapshot (DC-2):** the **effective company universe and each company's sector as reconstructed from `watchlist_events`** (via the lifecycle loader), using only events recorded before the snapshot time. This is the **deployment** state, distinct from the retrospective **historical analysis state** of ST-30 (DC-8), and never used as an input to historical analysis. The snapshot is **fixed and hashed before the registration record is posted**, its hash goes into the record, and the registered policies use that protected state **from their first session**. Lifecycle events recorded after the snapshot (add, deactivate, reactivate, delete, sector change) are each either a registered deviation or excluded from the registered policies.
  - **Not frozen:** incoming observations the policy needs (prices, news, filings, quotes).
  - **Detection test:** changing (a) an upstream regime threshold, (b) a company's **sector through a watchlist event** (the source the application actually uses), and (c) a calendar rule each changes at least one replayed decision or account figure **and** is caught by the guard.
  - **Inventory check:** the §8.10 inventory must be a subset of the manifest.
- **Acceptance criteria:**
  - B.41 passes (with the sector change made through a watchlist event, DC-2);
  - a lifecycle event during a window is caught;
  - a new price or news row is **not** flagged;
  - the judge reviews the manifest and the detection test at registration;
  - any miss blocks registration.
- **Producer coverage (DC-1, moved here from ST-56):** the manifest lists `.claude/agents/graph-builder.md`, the graph-builder's monthly refresh rule and the edge-validation rule as the producer of the "Connections: second-order news" section.
- **Additional acceptance:**
  - the manifest contains the graph-builder producer entries;
  - the manifest contains the budget-guard tier configuration and degraded behaviour of ST-20 (moved here from ST-20);
  - the deployment snapshot's timestamp precedes the registration time and its hash is in the record;
  - a test proves the deployment snapshot is not read by the replay, power or validity runs.
- **Refs:** §8.10, B.41, DC-1, DC-2. **Depends on:** ST-41, ST-30, ST-56, ST-20. **Owner:** S2. **Phase:** Step 3.

### ST-43: Registration record and proof of timing
- **Subject:** fix each hypothesis's window, method and power statement before the window starts.
- **Description:**
  - **Fields:** the §8.4 fields, produced by the deterministic procedure from data ≤ 9 Oct 2026 and simulations only (the ST-58 outputs). The record names **two** states:
    - **analysis inputs:** the historical analysis state of ST-30 (the retrospective universe file of DC-8 and the cost schedule, by hash) and every derived input, all traced to data ≤ 9 Oct 2026;
    - **deployment metadata:** the manifest hash and the deployment state snapshot hash of ST-42, which **may** include events and code later than 9 Oct (logged development changes). They are metadata about what is deployed, not analysis inputs.

    It also includes the declared scenarios with each one's exclusion reason (`no_orders`, `zero_variance` or none), realised overlap and exposure, the lower-envelope power per length per hypothesis (DC-6), the procedure of DC-9 (v16's tolerance and its reported cost, the selection rule, the informative threshold), each scenario's power at 126, 189 and 250 sessions with the method's placebo power beside it, the window from v16 §8.3's rule, the frozen-cache manifest hash (DC-12), **the billing arrangement in force with its evidence (DC-10)** and the results of all three arrangements, the list of fixed nuisance inputs with their values, the statement that validation is conditional on those frozen execution assumptions, the inference outcome per hypothesis (a method, or "none adequate" with DC-7's consequences), the retrospective-universe label (DC-8), and the disclosure of exploratory forward outcomes already observed.
  - **Review and posting:** reviewed by ChatGPT and the judge (rule compliance only). Committed; its SHA-256 is posted by the Slack bot (the registration time), with the GitHub push time as the second record.
  - **Window start:** the next session; never back-dated.
- **Acceptance criteria:**
  - **runs only after gate G3;**
  - re-running the procedure reproduces the record;
  - the Slack receipt exists;
  - **Selection inputs vs disclosure vs deployment metadata:** a test proves that no **registration choice** (window lengths, inference method, scenario envelope, exclusion and informative flags, governing arrangement, FX buffer) takes a forward outcome, or the deployment snapshot, as input. Every derived input, including ST-46's FX percentiles and the intraday exit-proxy distribution, is traced through its provenance to data dated ≤ 9 Oct 2026. The only possible exception is DC-10's measured per-token cost schedule, if O-5 accepts it; it is then recorded with its dates and shown to contain no trading outcome. The frozen-cache hashes are verified before the procedure runs;
  - **registration is refused without the billing arrangement in force and its evidence**, and the governing results are those of that arrangement (test);
  - the **disclosure field** does contain the exploratory forward outcomes observed at registration time, as v16 requires;
  - a test proves that changing the disclosure field changes no registration choice.
- **Refs:** §8.1, §8.3, §8.4. **Depends on:** ST-58, ST-42, ST-39, ST-47. **Owner:** S3 with B6. **Phase:** Step 3.

### ST-56: Graph-builder as an upstream dependency of the AI pipeline
- **Subject:** the cost and producer contract for the connection-map producer that the Sonnet trader's inputs depend on (DC-1). **Step 1 only; its manifest coverage is in ST-42.**
- **Description:** "Connections: second-order news" is built from the graph-builder's connection map (`pipeline/context.py` via `graph.news_hits`). That section is accepted by the trader input filter as `news` (`traders/prepare.py`), and the Sonnet combined trader receives `news`. The graph-builder is an Opus agent refreshed monthly; the judge verifies its edges. The rule and news-only strategies do not read this section (their news shift comes from `model/news_score.py`). This story:
  - adds the graph-builder and the judge's edge check to cost tracking (ST-19) and to `acct.ai.v1`'s deployment cost;
  - places the monthly refresh in the ≥ 70% Opus budget tier (ST-20), with the stored map used with its age when paused;
  - defines the **producer contract** used later by ST-42: the instruction file, the monthly refresh rule, the edge-validation rule, and the use of the stored map with its age when a refresh is paused;
  - **keeps the section unchanged** in the trader's input: removing it would change the baseline.
- **Acceptance criteria:**
  - a cost record exists per refresh and per edge check;
  - `acct.ai.v1`'s deployment view includes both;
  - the producer contract is written down and referenced by ST-42;
  - the section is still present in the trader input on a replayed day.
- **Refs:** §5.1, §5.2, §5.3, DC-1. **Depends on:** ST-19. **Owner:** S1. **Phase:** Step 1.

---

## Epic E6: Reports and owner views (Step 3)

### ST-58: Step 3 evaluation runs
- **Subject:** run the Step-2 machinery on the Step-3 data.
- **Description:** on the outputs of ST-30 (data ≤ 9 Oct 2026 for everything that feeds registration):
  - the scoreboards (ST-32 to ST-34);
  - the placebo selection and verification (ST-37, run once);
  - the power analysis and v16 §8.3's window rule under the governing scenario (ST-38);
  - the measured Holm cost.
  
  Store the results with their code commit and the latest data date read. The ≤ 9 Oct 2026 restriction is enforced through the **complete input provenance**, with **one exception only**, the same as ST-43's: DC-10's measured per-token cost schedule, if O-5 accepts it, recorded with its dates and shown to contain no trading outcome. The provenance covers the ST-46 percentiles and intraday proxy distribution, the **historical analysis state** of ST-30 (the retrospective universe of DC-8 and the cost schedule), and the replayed surrogates and scenario paths. ST-58 consumes the historical analysis state from ST-30 and **never** the deployment snapshot of ST-42.
- **Acceptance criteria:**
  - every output records its inputs and data cut-off;
  - the verification set is used once;
  - the results feed ST-43 unchanged;
  - **integrated fixtures that need the policy code (moved here from Step 2, because they use ST-25 to ST-30):**
    - **order fixture (5 days, T+1 default):** the source submits X (horizon 3, gate passed) and Y (horizon 1) on day 1, and B submits X. With ρ = 1, A's first order copies X with B's horizon; its second takes a seeded random stock Z with Y's horizon 1. Z exits at the close of day 2. On day 2, A has one free slot and enters the source's one order. On day 3, Z's proceeds are not yet settled under T+1, so A's order is skipped with `insufficient_free_cash`; under the immediate-reuse sensitivity it is filled. X exits at N+3;
    - **arrangement fixtures:** one fixture scenario replayed under the three billing arrangements gives three records, and changing only the recorded arrangement changes which governs;
    - **guard in replay:** under the per-token fixture schedule, A records missing calls as reliability failures from the pause day onwards;
    - **DC-6 surrogate fixtures (3-day history):**
      - (a) w = 0.10, prob_model 0.47, threshold 0.55, u = +0.09 → the surrogate submits X and B stays in cash;
      - (b) prob_model 0.60 for X only, u = −0.02 → both submit X;
      - (c) B blocked by its cost gate while u lifts A's gate above 0 → only A submits;
      - (d) B's slots full, A's not → only A submits.
- **Refs:** §8.2, §8.5, §10 Step 3, DC-6, DC-10. **Depends on:** ST-30, ST-32 to ST-38. **Owner:** S3. **Phase:** Step 3.

### ST-44: Account report with independent recomputation
- **Subject:** the full, reproducible account report.
- **Description:** every item listed in §10 Step 3:
  - the equity curves;
  - decisions with their cut-offs;
  - order events;
  - fills with type and provenance;
  - cash, reservations, interest and TDS;
  - costs by unit and deductibility;
  - **missed acknowledgements from the rehearsal account**;
  - unused cash;
  - tax per period;
  - both economic views with their reconciliation;
  - comparators and the index;
  - degraded days;
  - the robustness table;
  - every number tagged.
- **Acceptance criteria:**
  - an independent recomputation of the full equity curve reproduces it;
  - every deduction traces to its assumption;
  - the rehearsal section is present once ST-31 runs.
- **Refs:** §10 Step 3. **Depends on:** ST-30, ST-31, ST-34, ST-39, ST-58. **Owner:** S3. **Phase:** Step 3.

### ST-45: Owner views in the app, Slack and reports
- **Subject:** the plain-language views of §12.
- **Description:**
  - **Per company:** the chance of rising, with its event in words; the expected price and range; "chance of profit after costs: not measured yet"; buy (limit) / hold / sell / no trade, with a reason.
  - **"No clear signal":** shown when the Platt slope ≈ 0. Display only (§9.2).
  - **Per account, shown first:** money kept against cash and the index, before and after tax; drawdown; costs in both views; the budget tier; Amsterdam exit times.
  - **Per trade:** every cost by name and the net profit.
  - **Status line:** word for word on every report.
- **Acceptance criteria:**
  - A.1 shown as ₹3,016 / ₹661.62 / ₹2,354.38;
  - the status line is present on every report;
  - "No clear signal" never changes a decision.
- **Refs:** §12, §9.2. **Depends on:** ST-34, ST-44. **Owner:** existing web and Slack sessions, coordinated by the orchestrator. **Phase:** Step 3.

---

## Epic E7: Retrospective inputs and coverage

### ST-46: Measured inputs from history (FX and the US exit proxy)
- **Subject:** the measured distributions the design needs, each from its correct source and data range.
- **Description:**
  - **From the daily long-history cache** (`work/model_history/`, data ≤ 9 Oct 2026):
    - the 99.9th percentile of the **absolute overnight** EUR/USD move (buffer b);
    - the 95th and 99th percentiles of the **absolute one-day** move (stresses).
  - **From the available 5-minute stock history** (a different source; the daily cache holds no intraday data): the 15:45-to-close price-ratio distribution for the US exit proxy, **using only bars dated ≤ 9 Oct 2026 for any version that feeds registration analysis**. Later bars may only refine post-registration reporting, stored as a separate, dated version. The sample range and size are recorded. If the ≤ 9 Oct sample is too small for a stable distribution, that is reported, and the proxy's spread reflects it (open item O-2).
  - **Storage:** each value is stored with its source, date range and sample size.
- **Acceptance criteria:**
  - each value reproduces from its script;
  - the percentiles are of **absolute** moves;
  - b replaces 2% only once recorded;
  - the intraday sample size is reported with the proxy.
- **Refs:** §4.2, §4.4, §4.7. **Depends on:** ST-09. **Owner:** S1. **Phase:** Step 1.

### ST-47: Fixture suite and coverage check
- **Subject:** prove that every worked trade, fixture and integrated fixture is implemented and passing.
- **Description:** one test module maps A.1, A.2, B.1–B.41 and I-1–I-7 to their tests, each with its expected outcome, actual output and ledger reconciliation. Each item is tagged with its phase (Appendix 3). A coverage check fails if any item lacks a test.
- **Acceptance criteria:**
  - all 50 items are present;
  - Step-1 items pass at G1, Step-2 items at G2, and all items at G3;
  - the map matches Appendix 3.
- **Refs:** Appendices A and B; §10. **Depends on:** the owning stories. **Owner:** S1, then S2 and S3. **Phase:** Steps 1–3.

---

## Epic E8: Deferred research (§11)

**Common gates for every deferred story (§11, inherited by ST-48 to ST-54):**
- built only after gate G4;
- before use, each must show on **unseen outcomes**:
  1. forecasts better than simple alternatives;
  2. predicted order values that agree with realised outcomes well enough to guide decisions;
  3. decisions that improve account profit after their own extra costs;
- each enters as a **registered challenger** (its own registration record and window, a share of the 0.04 α reserve, the incumbent as primary comparator);
- **the owner approves every promotion**;
- no claim of accurate N+k predictions.

### ST-48: Step 4a, the order-level value model
- **Subject:** estimate the net value of placing a day limit order.
- **Description:**
  - **Target:** E[net outcome | information, order], estimated directly from realised order outcomes (open fill, intraday fill, no fill = 0), followed to the executable exit in the account currency after costs.
  - **Also:** P(net > 0 | fill, fill type).
  - **Forbidden:** unconditional return × fill probability.
  - **Leakage controls:** grouped validation; purge and embargo = the longest information-to-outcome span + 1 session; a fixed limit grid; quantity fixed.
- **Acceptance criteria:**
  - **held-out empirical evidence:** (1) an adverse-selection table and (2) calibration of order value by decile, both on held-out data;
  - **implementation check (constructed, not held-out):** (3) a synthetic fixture with fill and return correlated by construction, showing the product construction is biased and the direct model is not, **for that known case only**;
  - plus the common gates.
- **Refs:** §11.1. **Depends on:** G4. **Owner:** to be assigned. **Phase:** Deferred.

### ST-49: Step 4b, the return distribution
- **Subject:** a calibrated distribution of the official close.
- **Description:** log-return quantiles from 5% to 95% in 5% steps with monotone interpolation; exponential tails beyond 5% and 95%, each with exactly 5% mass and a **continuous CDF**; a normal-mixture benchmark; hurdle bands. It gives only the chance of the close rising and the expected close, never a chance of profit.
- **Acceptance criteria:**
  - the quantile grid is exactly 5–95% in 5% steps, and monotone;
  - the CDF is continuous at both tail joins, with each tail at exactly 5%;
  - the **upper-tail rate β > 2** is enforced (fits with β ≤ 2 are rejected), with β's confidence interval and a β-sensitivity table reported;
  - exceedance rates are tested at **1%, 2.5%, 97.5% and 99%**; PIT histograms;
  - a **closed-form versus Monte Carlo moment check**;
  - the "90% −1% / 10% +20%" fixture gives a 10% chance of rising and +1.1% expected;
  - plus the common gates.
- **Refs:** §11.2. **Depends on:** G4. **Owner:** to be assigned. **Phase:** Deferred.

### ST-50: Step 4c, structured events
- **Subject:** AI extraction of results, filings and calls behind quote gates.
- **Description:** verbatim-quote-gated extraction; news counted once per event cluster, with freshness decay; "priced in" held as an uncertain estimate; no preferential treatment of results days.
- **Acceptance criteria:**
  - every extracted item cites a verbatim quote that passes its gate;
  - plus the common gates.
- **Refs:** §11.3. **Depends on:** G4. **Owner:** to be assigned. **Phase:** Deferred.

### ST-51: Step 5, ranking comparison and early exits
- **Subject:** test the ranking heuristic against simpler rules, and test early exits.
- **Description:**
  - **Ranking:** the heuristic against the top 3 by expected net return, and against a random choice among candidates that pass the hurdle (pre-declared).
  - **Early exits:** against holding to plan, with the same cut-off, differential costs, the freed slot valued by the trades actually taken, and every eligible revision scored.
- **Acceptance criteria:**
  - the comparators are declared before any run;
  - plus the common gates.
- **Refs:** §11.4. **Depends on:** ST-48. **Owner:** to be assigned. **Phase:** Deferred.

### ST-52: Step 6, adaptation
- **Subject:** learned combination weights with shrinkage.
- **Description:** a proper scoring rule, shrinkage toward equal weights, and the primary test against the frozen equal-weight policy. No automatic adaptation of decision rules.
- **Acceptance criteria:**
  - the equal-weight comparator is frozen before the run;
  - plus the common gates.
- **Refs:** §11.5. **Depends on:** ST-49. **Owner:** to be assigned. **Phase:** Deferred.

### ST-53: AI research loop and the challenger cap
- **Subject:** research-director proposals as registered challengers.
- **Description:** proposals are tested in development, registered with a share of the reserve, and evaluated forward. At most 3 live challengers per market.
- **Acceptance criteria:**
  - the cap is enforced;
  - every challenger has a registration record;
  - plus the common gates.
- **Refs:** §11.6, §8.6. **Depends on:** ST-43. **Owner:** to be assigned. **Phase:** Deferred.

### ST-54: Challenger `acct.rule.v1_1` (the "no clear signal" decision change)
- **Subject:** suppress candidates that rely only on a flat-signal probability, as a registered challenger.
- **Description:** the decision-changing half of §9.2, registered with its own window against the incumbent `acct.rule.v1`.
- **Acceptance criteria:**
  - a registration record exists before its window;
  - `acct.rule.v1` is unchanged;
  - plus the common gates.
- **Refs:** §9.2. **Depends on:** ST-43. **Owner:** to be assigned. **Phase:** Deferred.

---

## Appendix 1: Requirement → story → test map

"Test" names the fixture or acceptance criterion that proves the requirement. **Open** marks anything unresolved.

| # | v16 requirement | Story | Test |
|---|---|---|---|
| R1 | Policy and rehearsal accounts; assumed and recorded attendance (§4.1) | ST-03, ST-31, ST-57 | B.5; ST-57 tap/miss test |
| R2 | ₹3,00,000 / $3,000 at q₀ ≤ cut-off; same C₀ for every policy (§4.2, §8.6) | ST-03 | I-5; q₀ look-ahead test |
| R3 | Slot = equity ÷ 3; reservations; no tax reserve (§4.2) | ST-06 | A.1; A.2; B.3 |
| R4 | One buffered US quantity formula (§4.2) | ST-06 | A.2; B.30; single-function test |
| R5 | Cash states; T+1 default and immediate sensitivity (§4.2) | ST-07 | B.31; B.40; I-3 |
| R6 | FX buffer b = 99.9th pct of absolute overnight move, 2% default (§4.2) | ST-09, ST-46 | absolute-move test; ST-46 record |
| R7 | Rejection at fill; never resized (§4.2) | ST-08 | B.30 |
| R8 | Plan-linked interest; dated rates (§4.2) | ST-13 | B.13; I-2 |
| R9 | L = prev close × 1.005; fill rule; buy-limit fill ≤ L (§4.3) | ST-08 | limit-fill test; A.2 |
| R10 | Sensitivities: L × 1.000, market at open (may fill above L, fixed quantity, affordability) (§4.3, DC-3) | ST-06, ST-08 | open-102 fixture; affordable and unaffordable gap fixtures |
| R11 | Execution variants; "not robust" label (§4.3) | ST-08 | variant fixtures |
| R12 | India exit chain, CAS band and no-equilibrium rule, VWAP history (§4.4) | ST-10 | B.5; B.7; B.8; A.1 |
| R13 | US exit at close − 15 min; 5-minute bar; proxy with common random numbers (§4.4) | ST-11, ST-46 | A.2; time-zone fixtures; same-draw test |
| R14 | IANA time zones (§4.4) | ST-10, ST-11, ST-57 | 20:45 on 27 Oct; 12:45 ET on 27 Nov; 10:50 on 3 Nov |
| R15 | Cost scenarios, units and deductibility (§4.5) | ST-04, ST-05 | A.1; B.1; B.4; I-1; I-2 |
| R16 | Slippage stress on market fills only (§4.5) | ST-04 | stress-scope test |
| R17 | Done buttons; paper instruction; separate fallback acknowledgements (§4.6) | ST-57, ST-31 | B.5; ST-57 tests |
| R18 | FX rule: latest ≤ event; previous-day close; age; absolute-move stresses against the account; same-day close diagnostic only (§4.7) | ST-09, ST-46 | B.2; B.11; B.39; direction test |
| R19 | India STCG, deductibility, losses, TDS as four amounts, W1–W3, refund assumptions (§4.8) | ST-15, ST-07 | A.1 tax; B.18; B.20; B.23; B.34; I-3; DC-4 |
| R20 | Box 3 deemed, counterfactual, C0–C2 with floor, anti-arbitrage, 2028, India account (§4.8) | ST-16 | B.15; B.17; B.26; B.32; B.37 |
| R21 | Governing tax scenarios; both-direction flags (§4.8) | ST-17 | B.38; governing-only test |
| R22 | Risk rules, open orders counted, brake and restart scenarios, gap risk (§4.9) | ST-14 | B.9; pending-order tests |
| R23 | Cost tracking, billing basis, two economic views, reconciliation, accruals (§5.1–5.2) | ST-19, ST-56 | B.6; B.16; I-4 |
| R24 | Budget tiers and degraded behaviour; disclosure; floor (§5.3) | ST-20, ST-21 | B.21; tier tests |
| R25 | Routine model split (§5.4) | ST-22 | schedule replay |
| R26 | Four-week cost study (§5.5) | ST-24 | descriptive report |
| R27 | Ten data kinds; provenance; append-only (§6) | ST-02, ST-18 | schema and append-only tests |
| R28 | Forecast, decision and account scoreboards; index proxy (§7.1–7.3) | ST-32, ST-33, ST-34 | replay-table reproduction; reconciliation |
| R29 | Six inference candidates (§7.4, §8.5) | ST-36 | reference examples |
| R30 | What is fixed now vs at registration; forward data disclosed; deterministic procedure (§8.1) | ST-43, ST-58 | no-forward-input test; reproducibility |
| R31 | Power per hypothesis under measured dependence; central (governing) scenario; window rule (§8.2–8.3; DC-9) | ST-37, ST-38, ST-58 | §8.2 calculator check; B.27; coverage property on four processes; window-rule fixture |
| R32 | Registration fields; Slack receipt; window start (§8.3–8.4) | ST-43 | Slack receipt; G3 gate |
| R33 | Placebo construction (same candidates, full wrapper, costs, brake); full-span sets; selection and verification; no retuning; "descriptive only"; limitation statement (§8.5) | ST-37, ST-58 | B.25; selection-then-fail fixture; construction test; statement present |
| R34 | d_t, monthly advantage, liquidation value, tax bridge, two end figures (§8.6) | ST-35, ST-12, ST-17 | B.28; B.29; B.35; B.36; I-6 |
| R35 | H1–H3, Bonferroni 0.01, bounds, stopped hypotheses keep their share (§8.6) | ST-39, ST-35 | B.33 |
| R36 | S1–S3; conditional after-tax bound (§8.7) | ST-39 | B.22; B.24 |
| R37 | Interim reports; harm stops (§8.8) | ST-35, ST-40 | harm-stop tests |
| R38 | Labels, precedence and qualifiers (§8.9) | ST-39 | one fixture per label |
| R39 | Freeze guard; validated deviations; update rules (§8.10) | ST-41 | B.14; invalid-deviation tests |
| R40 | Generated manifest and detection test (§8.10) | ST-42 | B.41 (via watchlist event, DC-2) |
| R41 | Protected universe and sectors from stored events (DC-2) | ST-42 | lifecycle-event test |
| R42 | Graph-builder dependency: cost, budget, manifest (DC-1) | ST-56, ST-19, ST-20, ST-42 | ST-56 tests |
| R43 | `baseline.v1` frozen; display-only "No clear signal" (§9.1–9.2) | ST-41, ST-45 | decision-unchanged test |
| R44 | Shared execution wrapper; policy-specific selection (§9.3) | ST-25 to ST-29 | negative-heuristic momentum test |
| R45 | Policies rule / ai / noai / news / simple / cash, labels and costs (§9.3) | ST-26 to ST-29 | B.12; B.13; gate fixtures |
| R46 | Forward accounts from 12 Oct; replay 2011–2026 as development (§8.3, §9.4) | ST-30 | labelling and reconciliation tests |
| R47 | Account report items; independent recomputation (§10) | ST-44 | recomputation test |
| R48 | Owner views; status line; per-trade net profit (§12) | ST-45 | A.1 display; status-line test |
| R49 | Evening run and revisions as additive records (§3, §7.1) | ST-23 | no-replacement test |
| R50 | Deferred steps with common gates (§11) | ST-48 to ST-54 | common gates |
| R51 | Every fixture implemented (§10, Appendices A and B; I-1 to I-7) | ST-47 | coverage check |
| R52 | Retrospective replay only where inputs exist historically, labelled development (§9.4); its universe declared (DC-8) | ST-30 | universe-file tests; no-backdating test; label check |
| R53 | Each policy charged its own deployment costs, accrued as §5.2 says, inside budget tiers (§5.2–5.3), including the replayed surrogates (DC-6); committed spend and billing arrangements (DC-10) | ST-19, ST-20, ST-30, ST-38, ST-43 | cost accrual fixtures; guard simulation fixture; arrangement fixtures |
| R54 | Dividends in every account; replay realism: as-traded sizing, results-blackout gap, frozen inputs, tax years, FX timing (DC-12) | ST-12, ST-15, ST-16, ST-17, ST-18, ST-30, ST-55 | I-7; split, as-traded, blackout-flag and hash fixtures |

**Open items** (revision 2's "none" is withdrawn):
- **O-1:** the owner's acceptance of DC-1 to DC-12 (DC-11 withdrawn), before implementation starts.
- **O-2:** whether the stored 5-minute US history dated ≤ 9 Oct 2026 is large enough for a stable exit-proxy distribution (ST-46). It is measured in Step 1. If it is insufficient, the limitation and its wider spread are reported, and ChatGPT and the owner are told before ST-58 runs.
- **O-3:** these are modelling and protocol choices that ChatGPT and the owner have not yet accepted. **They are additions to v16, not a literal breakdown of it.** They must be agreed before ST-58 runs, and each is declared before any run:
  - DC-6: the scenarios, the order contract and the lower envelope;
  - DC-7: the no-adequate-method consequences and the harm-test definition;
  - DC-8: the retrospective universe;
  - DC-9: how many placebo orders and when (the more-active-arm driver), the informative threshold, the cautious power property, and set-local, point-in-time and nuisance inputs;
  - DC-10: the committed-spend reading, the three billing arrangements, and reporting of excess;
  - DC-12: dividends and their tax, the as-traded basis and splits, and the other replay rules.

  **Which DCs change a rule v16 states (checked one by one):**
  - **DC-3:** market-at-open fills may exceed L; agreed in revision 2;
  - **DC-12(5):** the FX buffer's "overnight move" is measured close to close, because the stored daily EUR/USD bars have open = close, and it is measured in Step 1 rather than step 3.

  Every other DC fills a gap v16 leaves open or defines a construction v16 names without specifying.
- **O-4:** mapping a requirement here does not prove its acceptance contract is complete. The judge reviews each batch's acceptance tests against this map at each gate.
- **O-5 (needs ChatGPT's and the owner's decision):** the per-token arrangement needs a per-component cost schedule. v16's only figure, about $8 per market per run, is a whole-run estimate from **before** the routine change, and no per-component cost is tracked yet (ST-19 builds the tracker). **Proposal M:** costs measured once **both** ST-19 and ST-22 are live, recorded with their dates, used as a fixed nuisance input. They are operating costs, not trading outcomes; this is an explicit exception to the ≤ 9 Oct rule. **Fallback S,** used for the historical replays only if M is rejected: $8 per market per run as a stress assumption, applied to whole steps with the "cost unchanged after a pause" rule (it overstates spend, so pauses come earlier). Under S, every policy that needs any paid component is charged the full $8 per market per run, including on paused days. **S is a stress view, never the governing economics.** The forward accounts' governing economics always use the actual executed calls, fixed commitments and bills (ST-19).
- **O-6 (owner):** the billing arrangement in force must be recorded with evidence before registration (ST-43 refuses otherwise). It is a fact about which plan pays for the routine sessions, not a personal question; v16 §5.1 already lists it as open. **Recommendation:** record it now. The calculation still runs for all three arrangements (DC-10), but registration can only proceed with the arrangement recorded.

## Appendix 2: Design clarification register (published in full as `docs/PLAN_v16_errata.md`; v16 unchanged)

| DC | Clarification | Why | Stories |
|---|---|---|---|
| DC-1 | The graph-builder (Opus, monthly) produces the connection map read by the Sonnet trader's `news` input. It, and the judge's check of its edges, are AI components: tracked in costs, charged to `acct.ai.v1`, in the ≥ 70% Opus budget tier (the stored map used with its age when paused), and in the manifest as a producer with its refresh rule. The section stays in the trader's input. | Judge v16 finding 3; ChatGPT verified the chain; v16's §5 and §8.10 lists omit it. Verified in code: `pipeline/context.py` line 291 (`news_hits.context_section`), `traders/prepare.py` line 31; the rule strategies' `news_score` does not read it. | ST-19, ST-20, ST-22, ST-27, ST-41, ST-42, ST-56 |
| DC-2 | The company universe and each company's sector come from stored `watchlist_events` (lifecycle loader). They are protected as a hashed state snapshot **fixed before the registration record is posted** (its hash is in the record), used by the registered policies from their first session; later lifecycle events are caught; and the detection test changes a sector **through an event**. v16's intent (a generated functional manifest) already covers this; the clarification makes stored state explicit. | Judge v16 finding 4, as narrowed by ChatGPT: the guard is not "config only", but stored state needs explicit coverage. | ST-41, ST-42 |
| DC-3 | v16 §4.3's "a buy fill is never above L" applies to **limit** fills. The market-at-open sensitivity fills at the open, even above L. **Implementation assumptions** (v16 does not specify them): it is sized at L with the same formula; the quantity is fixed at submission; at the open, orders are processed in ranking order, and an order whose cost exceeds its reservation plus the free cash then available is rejected (`insufficient_cash_at_fill`); no resizing and never negative cash. | ChatGPT points 3 (revision 1) and 3 (revision 2): the literal rule breaks the market experiment v16 specifies; without an affordability rule the sensitivity could create borrowing that v16 prohibits ("no leverage", §4.2). | ST-06, ST-08 |
| DC-4 | B.23's "a test fails if any tax total exceeds the liability" means **tax expense** must equal the computed liability and never be expensed twice. Gross withholding above the liability is valid (it becomes a refund receivable). | ChatGPT point 9: the literal wording would reject v16's own ₹1,000 / ₹600 example. | ST-15 |
| DC-5 | Wording errata in §8.2 and Appendix E: (a) the 28 India and 3 US dropped dates are exchange holidays with **no** watchlist bars (not "only some companies"); (b) the gaps to ChatGPT's figures are, **for India**, 0.0009 / 0.0028 / 0.0019 (sd(A), sd(A−B), correlation), not "within 0.002"; **for the US**, 0.0153 / 0.0051 / 0.0011; (c) **cause:** both computations use the same session panel and method; only the **order in which the companies are listed before the seeded random draws** differs. With the companies sorted alphabetically, the canonical script reproduces ChatGPT's figures exactly (India 1.0875 / 1.0668 / 0.5227; US 1.4653 / 1.5728 / 0.4484; verified by Claude on 11 Oct). Both are valid Monte Carlo realisations of the same method. The published figures and script are unchanged and correct. | Judge v16 findings 1–2; ChatGPT's revision-2 review (ticker order). | ST-01 |
| DC-6 | **Declared scenarios, order contract and governing scenario (§8.2–8.3).**<br>**Scenarios** (replayed pairs, both arms with deployment costs, under each DC-10 arrangement): H1: A ∈ {rule surrogate `acct.rule.v1|model-part`, `acct.noai.v1`, `acct.simple.v1`}, B = cash. H2: A ∈ {rule surrogate, `acct.noai.v1`}, B = `acct.simple.v1`. H3: B = replayed `acct.noai.v1`; A has `acct.ai.v1`'s wrapper, costs and guard behaviour, its own state, and one pre-open order per pre-open order of an exposure source {surrogate w = 0.10, `acct.simple.v1`}; each order copies one of B's same-day pre-open orders with probability ρ ∈ {0.8, 0} (v16 §8.2's two ends), else a uniform eligible pick; 4 scenarios × 200 paths per set.<br>**Order contract:** "order" means a pre-open submitted order, never a fill. A copied order takes B's horizon and gate decision; any other order, and every placebo order, takes those of the order it stands in for ("pass" for the gate-less `acct.simple.v1`).<br>**Surrogate:** clip(prob_model + u, 0.01, 0.99), u ~ U(−0.10, +0.10) per ticker, day and horizon. Scope: historically anchored on prob_model; the live trader anchors on `prob_up` including news.<br>**Usable scenarios (one rule, as ST-38):** a scenario is excluded from the power calculation, with its reason, if neither arm submits an order in the set (`no_orders`), or if orders are submitted but d_t has zero sample variance there (`zero_variance`, e.g. orders that never fill).<br>**Governing:** v16 §8.3's "central scenario" = the **lower envelope** (the lowest power) over the usable scenarios. | ChatGPT revision-4 point 3; revision-5 points 1–3; revision-6 points 3 and 4; self-review (the w = 0.05 and w = 0.02 arms and ρ = 0.4 dropped: w = 0.05 cannot trade on India's flat model, and v16 names only the two ends). | ST-30, ST-37, ST-38, ST-39, ST-43, ST-58 |
| DC-7 | **"No adequate method" consequences and the harm test** (§8.5 says the hypotheses are then "reported descriptively only, with estimates and intervals"; v16 does not say which intervals or define the harm test). No adequate method: power "not computed"; window 250; **§8.9's precedence kept** ("Stopped for harm" first, otherwise "Descriptive only"); the intervals of all six methods shown, each "unvalidated". **Harm test:** H₀ mean ≥ −2% a month vs H₁ below; the registered method's p-value, or with no adequate method **any** candidate's, as a precautionary stopping rule (the report names the method and says "unvalidated"); interim p-values labelled "precautionary at this length" (the methods are validated at 126, 189 and 250 sessions only); a constant d_t fires the stop exactly when it is below −2% ÷ 21 per session; the drawdown prong is account-level; **a policy stopped under any hypothesis is stopped in all of them**, and the rehearsal account following it stops too; each keeps its α share. | ChatGPT revision-3 smaller point 2; revision-4 point 4; revision-5 note; self-review (the harm null, interim lengths, constant series and two-comparator policy were undefined). | ST-35, ST-38, ST-39, ST-43 |
| DC-8 | **Retrospective research universe** for the replay and every registration analysis (§8.2, §8.5, §9.4). The stored watchlist events cannot give a historical universe: all 40 are `seed` events recorded on 7 Oct 2026 and effective from 7 Oct 2024, and the lifecycle loader returns 0 companies before 7 Oct 2024. The replay therefore uses a frozen file of the 20 companies per market recorded by 9 Oct 2026, with their recorded sectors, for every date. Each company enters on its first session with complete inputs (first bar plus warm-up). Nothing is backdated or written to `watchlist_events`. Every output carries the label "retrospective research universe: today's 20 companies, chosen in 2024–2026 with hindsight (survivorship bias); not a historical watchlist". The eligible count per date, the survivorship caveat and the 2026 sector classification are reported. This matches the existing 15-year backtest's stated limit ("today's watchlist (survivorship bias)", `lab/backtest.py`). | ChatGPT revision-4 point 1, verified by running the loader for both markets on 11 Oct (0 / 0 / 0 / 20 / 20 companies on 3 Jan 2011, 29 Jun 2018, 6 Oct 2024, 7 Oct 2024 and 2 Jan 2025). | ST-30, ST-37, ST-43, ST-58 |
| DC-9 | **Validation and power (§8.2, §8.5): only what v16 leaves open.** Placebo pairs follow the scenario's more active arm's pre-open orders: how many, when, and with which horizon and gate decision (v16 says only "random selections"). Families too sparse to test are reported as uninformative, at a threshold stated by the builder. Untestable windows never lower a rejection rate. Verification needs at least one informative family. v16's tolerance, its δ values, its sets and its seeds apply literally, and the cost of the literal tolerance is reported. Power follows v16 §8.2 under the replay's measured dependence; because the estimate is imprecise, the window uses a cautious estimate that must cover the truth in ≥ 95% of simulated series on four stated processes, one fat-tailed with volatility clustering. The builder chooses the method. The selected method's placebo power is reported, not used in the window rule. Inputs: set-local, point-in-time, or fixed nuisance (listed). Label rules: `not_established` counts as below 80%; a constant d_t gives S1 "not met". | ChatGPT revisions 4–8; the independent reviewer (fat-tailed coverage, one definition of degenerate). | ST-37, ST-38, ST-39, ST-43 |
| DC-10 | **Committed spend, billing arrangements and excess (§5.1, §5.3).** v16 §5.3's check runs unchanged before each paid step. **Committed** = fees already due for the month plus paid steps already started; future runs are not committed. The last admitted step can cross a threshold; every excess is recorded and reported, and the ceiling is called "a target". **Scope:** one guard for the whole system, both markets. **Three arrangements** (v16 §5.1): (i) an existing subscription with no incremental bill; (ii) a subscription taken for this tool; (iii) per-token (historical schedule: O-5). Each is computed in advance; the arrangement **in force**, recorded with evidence at registration, governs **power and the window**. **S2 and S3 always use the actual dated costs and bills** (money actually kept); the registered-arrangement figure is shown beside them, labelled. A billing change during a window is a dated billing fact (ST-19), not a deviation: billing is not a frozen policy input, so ST-41 is untouched. | ChatGPT revisions 6 and 8; the independent reviewer. | ST-19, ST-20, ST-21, ST-30, ST-38, ST-39, ST-43, ST-58 |
| DC-11 | **Withdrawn in revision 9.** v16 §8.3's window rule applies unchanged. | ChatGPT revision-8 point 1; the owner's no-deviation rule. | — |
| DC-12 | **Dividends, corporate actions and replay realism (§9.4, §4.2, §4.7, §4.8; v16 is silent on these).** (1) **Dividends** in every account: eligibility for holdings bought before the ex-date (a sale on the ex-date keeps it, a buy on it earns nothing); the amount on the as-traded share basis; cash spendable in forward and rehearsal accounts only on a verified payment date or a recorded receipt (the receivable counts in equity meanwhile); in replays an assumed payment date only as a labelled assumption with a timing sensitivity; a missing amount or an unknown basis makes the result incomplete, never zero income; withholding recognised once as the dividend's tax through the bridge (I-7). Rates are dated, owner-confirmable scenarios. Box 3: under the deemed regime only via later 1 January balances; under C1, C2 and 2028, part of the actual return; stored prices are not dividend-adjusted (`collectors/prices.py`: `auto_adjust=False`), so without this the replay books ex-date drops as losses. v16 does not mention dividends. (2) **As-traded basis:** positions in as-traded shares. Prices are rebuilt from each source's own adjustment basis, because stored views, `ohlc_raw` included, can carry the source's later adjustments (HDFCBANK 22 Aug 2025: ₹982.30 stored, ₹1,964.60 traded). There is never a double adjustment. A frozen corporate-actions record supplies dividends (with payment dates where available), splits and bonuses. A split preserves q × P, with no cash or tax. (3) **Results blackout:** stored earnings dates start on 11 Oct 2023 (India) and 12 Oct 2023 (US); earlier dates are backfilled from allowlisted sources where possible; sessions without a known calendar are flagged `blackout_unknown`, counted, and have no blackout applied (a sensitivity excludes them). (4) **Tax years:** v16's current rules applied to every replayed year, labelled. (5) **FX:** every conversion uses the §4.7 rule; since the stored daily EUR/USD bars have open = close, "overnight move" is measured as the close-to-next-close move (so b = the 99.9th percentile of the absolute one-day move). ST-46 measures b in Step 1, earlier than v16's step 3, so that the Step-1 engines use measured values. (6) **Exposure:** the replayed comparisons keep slot = equity ÷ 3 (v16 §8.2); placebo windows start at C₀. (7) **Frozen inputs:** the long-history cache (gitignored, re-fetchable) is frozen with a per-file SHA-256 manifest recorded in every replay, ST-58 and ST-43 record. | Self-review (independent reviewer, each point checked: dividends missing, adjusted-price sizing, earnings history from Oct 2023, unfrozen cache, undefined tax years and FX overnight). | ST-12, ST-15, ST-16, ST-17, ST-18, ST-30, ST-43, ST-46, ST-55, ST-58 |

## Appendix 3: Fixture coverage and phase

| Item | Story | Phase | Item | Story | Phase |
|---|---|---|---|---|---|
| A.1 | ST-05, ST-06, ST-10, ST-15 | 1 | B.22 | ST-39 | 2 |
| A.2 | ST-06, ST-08, ST-11 | 1 | B.23 | ST-15 | 1 |
| B.1 | ST-05 | 1 | B.24 | ST-39 | 2 |
| B.2 | ST-09 | 1 | B.25 | ST-37 | 2 |
| B.3 | ST-06 | 1 | B.26 | ST-16 | 1 |
| B.4 | ST-05 | 1 | B.27 | ST-38 | 2 |
| B.5 | ST-10, ST-31 | 1 and 3 | B.28 | ST-35 | 2 |
| B.6 | ST-19 | 1 | B.29 | ST-12 | 1 |
| B.7 | ST-10 | 1 | B.30 | ST-06, ST-08 | 1 |
| B.8 | ST-10 | 1 | B.31 | ST-07 | 1 |
| B.9 | ST-14 | 1 | B.32 | ST-16 | 1 |
| B.10 | ST-06 | 1 | B.33 | ST-39 | 2 |
| B.11 | ST-09 | 1 | B.34 | ST-07, ST-15 | 1 |
| B.12 | ST-27 | 3 | B.35 | ST-17 | 1 |
| B.13 | ST-13, ST-29 | 1 and 3 | B.36 | ST-17 | 1 |
| B.14 | ST-41 | 2 | B.37 | ST-16 | 1 |
| B.15 | ST-16 | 1 | B.38 | ST-17 | 1 |
| B.16 | ST-19, ST-35 | 1 and 2 | B.39 | ST-09 | 1 |
| B.17 | ST-16 | 1 | B.40 | ST-07 | 1 |
| B.18 | ST-15 | 1 | B.41 | ST-42 | 3 |
| B.19 | ST-17 | 1 | I-1 to I-7 | ST-55 | 1 |
| B.20 | ST-15 | 1 | | | |
| B.21 | ST-20 | 1 | | | |

## Appendix 4: Reply to ChatGPT's review of revision 1

**Overall:** I accept all eleven points and the story-by-story dispositions. My withdrawn claim ("exactly, nothing added") was wrong, and ChatGPT's request for a requirement → story → test map with exposed open items is the right standard; Appendix 1 provides it. **I checked the points I could verify in the repository before accepting them:**
- `pipeline/context.py` line 291 calls `news_hits.context_section`;
- `traders/prepare.py` line 31 maps "Connections: second-order news" to `news`;
- the graph-builder frontmatter says `model: claude-opus-5-5`, and its instructions say the judge verifies its edges;
- the rule strategies' news path (`model/news_score.py`, `lab/strategies.py`, `lab/predict_inputs.py`) has no graph reference.

| # | ChatGPT point | Verdict | Change |
|---|---|---|---|
| 1 | The graph-builder must have an owning story | Accept | ST-56 + DC-1; ST-19, 20, 22, 27, 41, 42 updated; the section stays in the input |
| 2 | Watchlist and sector state comes from events; "config only" overstated | Accept both halves (the "config only" wording was mine, in revision 1's Appendix 3) | DC-2; ST-42 protects stored state and tests through an event; prices and news are not frozen |
| 3 | ST-08's "never above L" breaks the market-order sensitivity | Accept | DC-3; limit-only wording; open-102 fixture |
| 4 | ST-25 vs ST-29: shared gate ambiguity | Accept | ST-25 = execution and risk only; gates and rankings are per policy; negative-heuristic momentum test |
| 5 | "Absolute" lost; daily vs intraday sources | Accept | ST-09 and ST-46 restored; direction test; separate intraday source with its sample size |
| 6 | Selection passes, verification fails | Accept | ST-37 explicit rule and fixture; no substitution, retuning or second run |
| 7 | Central scenario | Accept | ST-38 declares it; DC-6 for H3's midpoint |
| 8 | Missing dependencies; Step 2 depending on Step 3; rehearsal infrastructure in Step 1 | Accept | Dependencies added (ST-30, ST-11, ST-44, ST-43); gates G1–G4; ST-58 runs the Step-2 machinery on Step-3 data; ST-57 = Step-1 infrastructure |
| 9 | Integrated fixtures; the "tax total" ambiguity | Accept | ST-55 (I-1 to I-6); DC-4 |
| 10 | The deviation must be validated | Accept | ST-41 validity rules and negative tests |
| 11 | Deferred common gates; ST-48 evidence wording; ST-49 detail | Accept | Common gates block; ST-48 separates held-out evidence from the constructed check; ST-49 detail restored |
| Dispositions | ST-01 run command; ST-23 → ST-32; ST-32 dataset; ST-39 all branches; ST-13/14 pending orders and fee; ST-26–29 inheritance | Accept | All applied |

**One narrow point of my own:** DC-6 (H3's central scenario) is a choice v16 left open. I chose the midpoint because it sits neutrally between v16's two stated ends, and it is declared before any run. If ChatGPT prefers another neutral rule, it must still be fixed before ST-58 runs.

### 4b. Reply to ChatGPT's review of revision 2

I accept all seven points and both smaller corrections. I verified the two I could check mechanically before accepting them:
- **The cycle:** revision 2's ST-09 listed ST-46, and ST-46 listed ST-09.
- **Ticker order:** re-running the canonical script with the companies sorted gives India 1.0875 / 1.0668 / 0.5227 and US 1.4653 / 1.5728 / 0.4484, exactly ChatGPT's figures.

| # | ChatGPT point | Verdict | Change in revision 3 |
|---|---|---|---|
| 1 | FX cycle ST-09 ↔ ST-46; ST-56 completion loop through ST-42 | Accept | ST-09 is built on fixture values with no ST-46 dependency, and integration is checked at G1. ST-56 is only the Step-1 cost and producer contract; the manifest coverage moved into ST-42. A cycle check of all "Depends on" lines is clean (Appendix 5) |
| 2 | "Midpoint" undefined; H1 governing surrogate unclear | Accept | DC-6 defines the overlap share s, the path construction, the endpoints 0.8 and 0, the central 0.4, cost and exposure handling, and the seeds. H1 and H2 govern on the named rule surrogate `acct.rule.v1|model-part` (ST-30). I withdraw "neutral": it is a declared modelling assumption, open item O-3 |
| 3 | Market-order sensitivity needs an affordability rule; sizing at L is an assumption | Accept | DC-3 and ST-08: fixed quantity, ranking-order processing, rejection when cost exceeds reservation plus free cash, no resizing, no negative cash; affordable and unaffordable-gap fixtures |
| 4 | Placebo construction and measured-dependence power shortened away | Accept | ST-37 restores the construction (same candidates, full wrapper, costs, brake), the H3 surrogate placebos, the full-span test and the mandatory limitation statement. ST-38 makes simulation power under measured dependence the registration figure; the independent table is a calculator check only |
| 5 | Gates incomplete and not cumulative | Accept | Cumulative G1–G4; ST-01, ST-20 and ST-56 in G1; ST-42 producer coverage and ST-45 in G3; "guaranteed" ceiling only after ST-21; the cost study does not block registration |
| 6 | Disclosure vs "no forward input"; intraday cut-off | Accept | ST-43 separates selection inputs from disclosure, with a test that changing the disclosure changes no choice. ST-46 cuts the intraday sample at ≤ 9 Oct for registration use. ST-58 enforces the cut-off through full provenance |
| 7 | Snapshot timing inconsistent; a deliberate change ends which window? | Accept | One time: fixed and hashed before the record is posted, used from the first session (DC-2, ST-42). ST-41: only the altered policy's window ends; challengers do not end the incumbent's |
| a | DC-5 cause and scope | Accept | Corrected: the cause is ticker order in the seeded draws; India and US gaps stated separately |
| b | "Open items: none" | Accept | Withdrawn; O-1 to O-4 listed |

**One clarification of my own** on ChatGPT's market-order illustration (3,000 available, three orders at 100, all opening at 102). Under the affordability rule the outcome depends on the free cash beyond the reservations: with none, **all three** are rejected, and none is filled partly or resized. The ST-08 fixture pins both that case and a 50-extra variant (two fill, the third is rejected), so the test checks the exact rule, not a plausible outcome.

### 4c. Reply to ChatGPT's review of revision 3

I accept all five points and both smaller points. I checked the two I could verify directly before accepting them:
- **The overlap formula:** with M eligible stocks, revision 3's generator matches B with probability s + (1 − s)/M, for example 0.43 at M = 20 and 1.00 at M = 1, exactly as ChatGPT says.
- **The hidden loop:** ST-20's acceptance required ST-42 (Step 3) while G1 required ST-20; my mechanical check had parsed only the "Depends on" lines.

| # | ChatGPT point | Verdict | Change in revision 4 |
|---|---|---|---|
| 1 | DC-6's s is not the match probability | Accept | DC-6 replaced. The new generator has no copy parameter; overlap is an **outcome**, measured and reported |
| 2 | DC-6 undefined when B does not trade (the India case) | Accept | Both arms run independently on their own state; A can trade while B is in cash. Fixtures (a)–(d) with exact outcomes in ST-38 |
| 3 | A zero-edge placebo blurred with an asymmetric scenario; power δ on a non-zero base | Accept; the most important point | ST-37 separates N (null: symmetric N1, and constant-centred N2), P (N + δ, true δ after costs) and S (uncentred, description only). The expected-outcome check and the −0.2% → +0.5% (not +0.3%) test are in its acceptance |
| 4 | Hidden Step-1 loop via ST-20 → ST-42 | Accept | The manifest check moved to ST-42; ST-20 completes at G1; B.21 is phase 1. **Lesson:** a dependency check must also read acceptance criteria. Appendix 5 now says what was checked and how |
| 5 | Historical analysis state vs deployment state | Accept | ST-30: a point-in-time universe ≤ min(D, 9 Oct), hashed per run. ST-42: the deployment snapshot. ST-43 records both, as analysis inputs and as deployment metadata. ST-58 consumes only the historical state |
| s1 | Reservation release timing at the open | Accept | ST-08: releases after the batch only; the fixture is consistent |
| s2 | "No adequate method" branch in power and registration | Accept | DC-7, ST-38 fixture, ST-43 |

**Where I push back:** nowhere. One note on DC-6: I replaced the copy generator rather than relabelling it, because ChatGPT's point 2 (B in cash) cannot be fixed inside a design where A's decisions are derived from B's. In the new generator, w is a **declared assumption** (O-3), not a measured fact. The real trader's adjustment distribution after 12 Oct may not be used, because registration may only use data up to 9 Oct.

### 4d. Reply to ChatGPT's review of revision 4

I checked each point against the repository at 82ff0f5, against v16 and against revision 4 before deciding. All five are correct, and I accept them. On point 2 I accept the conclusion but disagree with part of the reasoning, explained below. I also found three further problems ChatGPT did not raise.

| # | ChatGPT point | My check (evidence) | Verdict | Change in revision 5 |
|---|---|---|---|---|
| 1 | ST-30's point-in-time universe is impossible: the loader gives 0 companies before 7 Oct 2024 | Ran `contracts.watchlist.watchlist` for both markets: 0 on 3 Jan 2011, 29 Jun 2018 and 6 Oct 2024; 20 on 7 Oct 2024 and 2 Jan 2025. Each market has 20 events in one file `2026-10-07.jsonl`, all `add`, channel `seed`, effective 2024-10-07, recorded 2026-10-07. | **Accept** | DC-8: a frozen, labelled retrospective universe; entry by data availability; no backdating; tests. Measured facts: cache row counts show later listings (HDFCLIFE 1,693, SBILIFE 1,724, INDIGO 2,190 rows against 3,382; META 3,115 against 3,462) |
| 2 | Centring population undefined; possible verification leakage; set-wide zero ≠ per-window zero; self-centred checks prove little; seed ranges | Revision 4's text says "mean over all days and all seeds of that scenario on that history", which does not exclude the verification period. Its expected-outcome check tested a series against the mean it was built to have, so it could not fail. DC-6's seeds 20,001–20,999 lie outside v16's two ranges. | **Accept the conclusion; I replace the construction rather than repair it** | Centring is removed. Nulls are symmetric placebo pairs, zero in every window given its history by exchangeability (v16 §8.5's own construction). H1/H2 pairs are rescaled, with no effect on rejection rates. Set-specific inputs; a verification-isolation test; a check that can fail; seed blocks inside v16's ranges (DC-9) |
| 3a | w = 0.05 is inactive on India's flat model | Stored India `prob_model`: 0.4659–0.4744 on all 262 N+k rows (horizons 1–5); `prob_up` with news at most 0.5215; every threshold 0.55 (`config/strategies.yaml`). 0.4744 + 0.05 < 0.55. | **Accept**, and extended | The activity rule: quiet scenarios never govern; fixture (e). **Also applies to H1/H2:** India's rule surrogate has a zero news shift, so it is the same flat model. Revision 4's H1/H2 central scenarios could have been quiet too. They now fall back to the lowest-power active scenario, or "not established" |
| 3b | The surrogate covers only part of the AI-vs-model-only difference; adjustment width ≠ overlap scenarios | `traders/gate_evidence.py` line 115 anchors on the stored score's `prob_up`; `base.model_only.v1` has `news_weight: 0.0`. Historically there is no news archive, so no surrogate can include the news term. | **Accept** | The scope is stated in every output. H3 now uses v16's overlap ends directly (ρ = 0.8 and 0) through symmetric pairs, with the surrogate as one exposure source. The H3 governing scenario is the weakest active one |
| 3c | Revision 4 dropped the AI arm's deployment cost | Revision 3's DC-6 had "a deterministic daily accrual"; revision 4's has none. | **Accept** | DC-6 costs: §5.2 components per arm, two declared views, §5.3 tiers applied; fixtures in ST-30 and ST-38 |
| 4 | DC-7 overrides §8.9's harm-stop precedence | §8.9: "(1) Stopped for harm; (2) Descriptive only". Revision 4: "the only label is 'Descriptive only'". | **Accept** | Precedence kept; ST-39 fixture with "none adequate" plus a 21% drawdown |
| 5 | ST-01 still publishes DC-1 to DC-6 | Revision 4's ST-01 and O-1 both said DC-1 to DC-6. | **Accept** | ST-01 publishes every DC; a test compares the lists |

**Where I disagree with part of point 2's reasoning.** ChatGPT's example treats two periods' realised average advantages (0% and 2%) as their *expected* values. Within one history, a realised period mean is not an expected value. Applied per set rather than pooled, revision 4's constant would have zeroed both of ChatGPT's periods. So the example shows the pooling problem, not that constant centring as such is invalid. ChatGPT's deeper point still stands: centring cannot **guarantee** a zero expectation in each window, and a check against the mean it was built to have proves nothing. I removed the construction instead of defending it. The symmetric pairs give the guarantee that centring could not, and the "conditional zero" acceptance test uses ChatGPT's own two-period example.

**Three further problems I found (not raised by ChatGPT):**
1. **H1 and H2 have the same quiet-scenario problem as H3** in India (point 3a above).
2. **The harm stop's p-value prong had no method** when none is adequate (DC-7 now closes it protectively).
3. **Revision 4 left two choices unspecified:** which set's power is registered, and how one method is chosen across several scenarios. DC-9 fixes both: the verification set's power (selection-set power is biased upwards), and maximin selection.

**On ChatGPT's recommendation to start the accounting stories now:** I agree that Step-1 accounting (ST-02 to ST-19, ST-55 to ST-57) is untouched by these points. ST-01 is touched, through the errata. Under the owner's rule, nothing starts until ChatGPT agrees and the owner approves, so it is the owner's decision whether to start Step 1 before the evaluation stories are agreed.

### 4e. Reply to ChatGPT's review of revision 5

I accept all four points. I checked each one, and on point 3 one of the fixes is stronger than revision 5's approach in a way I want to state openly. I disagree with nothing of substance; one clarification on my side is below.

| # | ChatGPT point | My check (evidence) | Verdict | Change in revision 6 |
|---|---|---|---|---|
| 1 | SD matching does not reproduce dependence; active-vs-cash keeps a market factor that symmetric pairs cancel; k undefined at zero SD | Recomputed: with daily SD 0.1%, 250 sessions, α 0.01 one-sided, 80% power, the detectable advantage is 0.421% a month for independent days and 1.262% under AR(1) 0.8 (long-run variance factor 9). ChatGPT's 1.25% agrees to rounding. Revision 5 had no acceptance test for dependence; the scale-invariance argument was correct, but it covered only size, not representation. | **Accept** | Rescaling withdrawn. Power and a second validity family come from a circular block bootstrap of each comparison's own replayed difference: both arms' exposure, the market factor, dependence up to 63 sessions. AR(1) and common-factor fixtures. H3 paths are now asymmetric (B can sit in cash). Degenerate branch defined; k no longer exists |
| 2 | The candidate-only "quiet" rule excludes meaningful H2 comparisons; maximin undefined with no family; the ST-37 → ST-39 path is incomplete | Correct: revision 5 tested only arm A's entry count; for H2, a rule surrogate in cash against active momentum has d_t = −momentum's result, which is far from quiet. With no active family, revision 5's "weakest active family" had no value. | **Accept** | Only a paired difference that is zero on every session is degenerate. Selection uses the placebo families, which always exist, so it never needs an active scenario. Every branch is written out; integrated fixture in ST-39 (five paths) |
| 3 | Lengths, scenario choice, cost view and ties not uniquely determined; name the zero-cost case | Correct: revision 5 never said at which length the method is chosen, and "lowest power" is ambiguous across lengths, as ChatGPT's table shows. **Recomputed the cost views:** v16 §5.1's estimate (about $8 per market per run) gives about $336 a month for two markets, above the 100% tier of $250 (§5.3), so in that view only unpaid steps run. | **Accept** | One procedure: qualification at every length, selection at 250 sessions, lower envelope at each length, ties by v16's order. ChatGPT's table gives 70 / 83 / 94% and a window of 189 (fixture). Governing protocol view: "an existing subscription with no incremental bill"; per-token reported in full. Billing rule for S2/S3 |
| 4 | Verification isolation ignores upstream inputs (ST-46); S-path interface contradictory | ST-46's FX percentiles come from the daily cache up to 9 Oct 2026, which spans the verification period. The intraday proxy uses 5-minute data that exist only recently and cannot be set-local. Revision 5 both refused S paths and derived quantities from them. | **Accept** | Inputs split into set-local and fixed nuisance (listed with values). The isolation test re-runs the whole chain and allows changes only through nuisance inputs. Explicit list of what may be derived from S paths |

*(Withdrawn in revision 7: this paragraph relied on the unstated "projected" reading of the budget guard; see 4f and DC-10.)* **On the per-token view.** ChatGPT asked for the governing billing assumption; I did not expect the answer to be this stark. At v16's own estimate, the per-token view switches the paid AI components off under the $250 ceiling (v16 §5.1 already said "very unlikely to pay for itself"). It therefore cannot govern a test of those components. It is run and reported in full, so the owner sees the consequence. The estimate predates the §5.4 routine change and is an upper bound; the measured figure comes from ST-19 after 12 Oct and cannot feed registration (cut-off ≤ 9 Oct).

**My clarification on point 1.** I keep the symmetric placebo pairs as one validity family because they are v16 §8.5's own construction, and they check the methods on real price paths with the real wrapper. The new bootstrap families cover what pairs cannot. Two methods, (c) and (d), are themselves bootstrap methods. Testing them on bootstrap-generated data could favour them, so the generating blocks (63 sessions) are fixed, longer than every candidate's block and set before any run. Even so, a method must also pass on the placebo families, which owe nothing to any bootstrap.

**Agreed limitation (ChatGPT's closing point).** DC-6 to DC-9 are protocol additions. They are listed as such in O-3 and published in the errata. They are not claimed to be in v16.

### 4f. Reply to ChatGPT's review of revision 6

I accept all four points. On each one my revision-6 text claimed more than its evidence supported, and two statements were plainly wrong. I reproduced ChatGPT's counterexample before accepting.

| # | ChatGPT point | My check (evidence) | Verdict | Change in revision 7 |
|---|---|---|---|---|
| 1 | The 63-session bootstrap does not keep dependence within 63 sessions; a lag-1 test cannot catch it; "longer than every candidate's block" is wrong; "not because a constant was estimated" obscures the centring | Equal-weight MA(62): the variance multiplier of a 250-session mean is 57.71 for the process and 41.84 for blocks of 63, 63, 63 and 61; detectable advantage 3.20% against 2.72% a month. At 189 sessions: 56.00 against 42.01; at 126: 52.50 against 42.01. All reproduced by my own calculation. ST-37 said "fixed block (10, 20)", which is correct, but my Appendix 4e said "every candidate's block", which is wrong: (c) and (d) choose their block automatically. | **Accept** | Adaptive block length {21, 63, 126} with a 90% window-mean-variance rule at all three lengths; "not representable" → `none_adequate` → Descriptive only. Exact fixtures, including ChatGPT's MA(62). Bootstrap described as an approximation; centring wording corrected |
| 2 | The per-token conclusion is unsupported; commitment undefined; the fixture hard-codes my assumption; choosing the view that keeps the AI running is a poor basis | v16 §5.3's text says "spend to date plus committed spend"; only the table header says "projected". My conclusion silently used the projected reading. Simulated with committed spend, $16 a day pauses Opus from day 12, the traders from day 15, news from day 16 and paid steps from day 17, so the AI runs about two-thirds of the month. $8 is v16's pre-change estimate (§5.1). | **Accept** | DC-10: committed spend defined, the guard simulated in replays, three arrangements each fully computed in advance, the recorded arrangement governs. The hard-coded fixture is replaced by a guard-mechanics fixture with fixture costs. O-5 (cost source) and O-6 (arrangement record) |
| 3 | H3 random entries have no horizon; gate behaviour undefined; placebos the same | ST-25: "the candidate source, cost gate, ranking and horizon are policy-specific". Revision 6 specified none of them for random entries. | **Accept** | Order contract: copied entries take B's horizon and gate decision; others take those of the source entry they stand in for; placebo attempts likewise. Integrated 5-day fixture (entry, occupied slot, planned exit, `slots_full`) |
| 4 | Nuisance exception vs "no verification data"; isolation claim; constant series; 200-path degenerate rule; "no active scenario" leftover | All confirmed in the revision-6 text: ST-39 still said "no active scenario". | **Accept** | Scoped isolation rule with named nuisance inputs; "conditional on frozen execution assumptions"; zero-variance windows "undefined" and counted as non-rejection; degenerate only if all paths are; one structured outcome |

**Where I add to ChatGPT's points:**
- **Adequacy has a hard limit, and I have said so.** A block bootstrap can only reproduce dependence that fits inside its blocks. With blocks capped at 126 sessions, a comparison whose daily difference is as persistent as the MA(62) example **cannot be validated from this history at all**. The protocol now says so and sends that hypothesis to "Descriptive only". I chose that cap so the shorter set still holds about 14 independent blocks. Longer blocks would make the estimated rejection rates rest on too few independent pieces of history to mean anything at α = 0.01.
- **Realism, not a rejection:** daily profit and loss of a 3-stock long account typically has weak serial correlation, even with volatility clustering. Volatility clustering alone does not change the variance of a mean. I therefore expect b = 21 or 63 for most real comparisons. That is an expectation, not a measurement; the procedure decides.
- **O-5 is a genuine choice for ChatGPT and the owner.** Using measured operating costs after 12 Oct would break the ≤ 9 Oct rule, so I propose it as an explicit, named exception, with a defined fallback if it is rejected.

### 4g. Claude's full self-review of revision 7 before sending (revision 8)

After ChatGPT's six rounds found gaps each time, the owner asked for a complete re-review before sending anything. I re-read all 1,322 lines, and in parallel an independent expert reviewer (the judge agent, with no view of my reasoning) attacked the document. It reported 23 blockers and 15 cosmetic points. I checked each one before accepting it. The ones that change the design:

| Finding | My check | Verdict | Change |
|---|---|---|---|
| The adequacy test mostly measures sampling noise | The reviewer's simulation (2,000 independent series, n = 1,850): "not representable" in 13.5% of cases; the probability of passing every scenario then collapses. The revision-7 fixtures used population autocovariances, so they could not reveal this. | **Accept; withdraw rather than patch** | Bootstrap families removed; power from the measured long-run variance (v16's own formula); conservative end registered |
| Qualification compounds over many checks | Recomputed: P(an exactly sized method exceeds 16 of 1,000) = 2.64%; passing 54 checks 0.236, 18 checks 0.618 | Accept | K-adjusted binomial caps; fewer families (H3: 4) |
| Undefined windows hide oversizing | Arithmetic: 2.5% of 40% defined = 1.0% reported | Accept | Rates over defined windows, undefined share reported |
| Degenerate placebo families decide selection | True: an arm that never trades gives power 0 for every method, and list order then picks (a) | Accept | More-active-arm driver; uninformative families excluded |
| The guard overshoots (the fixture reached $256) | True | Accept | No-overshoot rule; fixture now ends at $240 |
| Guard scope, fee, split, mark rate and mid-window change undefined | True | Accept | DC-10 |
| O-5 M impossible (nothing is tracked yet) | Grep: no `operating_costs` in `scripts/` | Accept | M = costs once ST-19 and ST-22 are live |
| Accrual cycle treated as random dependence | True under per-token billing | Accept | Deterministic accruals removed before estimating V |
| Phase-order claim false | True: Step-2 acceptance named Step-3 policy code in words, which my ID-based check could not see | Accept | Those fixtures moved to ST-58; Appendix 5 corrected |
| Replay start state and placebo windows undefined | True | Accept | Restarts at C₀; seed-drawn starts |
| The order fixture contradicts T+1 | True | Accept | `insufficient_free_cash` under T+1 |
| "Entry" could mean a fill (look-ahead) | True | Accept | "Order" = a pre-open submitted order, everywhere |
| False and untestable acceptance criteria | True: on v16's US figures, sd(A − B) 1.58% > sd(A) 1.48% | Accept | Removed with the bootstrap; estimator checks rewritten |
| The six methods underspecified | True | Accept | ST-36 exact specification |
| Harm test undefined | True | Accept | DC-7 |
| No results blackout before Oct 2023 | Queried: `event_history` earnings rows start 2023-10-11 (India) and 2023-10-12 (US); the US 2023-10-04 row is an ex-dividend date | Accept | DC-12 (3) |
| No dividends | v16 has no mention of dividends; `auto_adjust=False` confirmed in both price code paths | Accept | DC-12 (1) |
| Split-adjusted sizing | True | Accept | DC-12 (2) |
| Cache not frozen | `work/` is gitignored | Accept | DC-12 (7) |
| Verification set cold-starts the model | True: set locality was applied to model scores | Accept | Model scores are point-in-time in both sets |
| ST-42 stale wording; label rules missing from the register | True | Accept | Fixed; DC-9 label rules |

**Second round with the same reviewer (on the revision-8 draft).** It confirmed every recomputed number and that 16 blockers were resolved. It found:
- **1 not resolved:** dividends were in the replay only, not in the live ledger;
- **4 partly resolved:** sparse placebo families, the fallback cost charging, the blackout behaviour and the harm p-value form;
- **5 new blockers:**
  - my power formula divided by 250 once too often;
  - my "conservative end" (×1.42) still overstated power in about a third of cases, as its simulation showed;
  - DC-11's "can only err towards too short" was false, and v16's three-length power report had been dropped;
  - the US earnings start date was wrong. I re-queried: 12 Oct 2023; 4 Oct 2023 is an ex-dividend date;
  - the harm test's p-value form was missing.

All were checked and are fixed in this revision. Dividends are now in the Step-1 ledger (ST-12, ST-18). The power bound is a 95% χ² bound (×2.77 at n = 1,850; 96–99% coverage in the simulation), with a coverage acceptance test. Power is reported at all three lengths.

**Consequence to note:** with an honest bound, even v16's most favourable case (daily SD 0.1%, independent days) registers power 0.475 at 250 sessions. Most hypotheses will register power below 80%, so a non-rejection will be labelled "Inconclusive", not "Failed". That is the truthful reading of how much evidence a year of paper trading can give.

**Two choices are mine, and ChatGPT may challenge them:**
- **DC-11, the fixed 250-session window.** It deviates from v16's rule, deliberately, for the reason given in the register: a noisy estimate makes the window choice noisy, and the harmful error is a window that is too short. It is reversible with no other change.
- **Withdrawing the bootstrap families.** This drops revision 6's extra check of the methods under each comparison's own dependence. Validation is now exactly v16 §8.5's placebo design, with v16's own limitation statement. Dependence still drives the registered power through the long-run variance.

**Cosmetic points applied:**
- the clock pinned in ST-01's command;
- `--end` added to ST-32's command;
- the unused w = 0.02 arm dropped;
- ST-19 and DC-10 aligned on three arrangements;
- the ST-10 → ST-57 dependency added;
- the Monte Carlo SE described as conditional on the one history;
- the surrogate draw and gate-less "pass" defined;
- the open items reordered;
- old change logs moved to Appendix 6.

**Not changed:** the US 15:45 exit priced without a spread is v16-faithful and stays as v16 has it. The O-6 recommendation is in the open items.

### 4h. Reply to ChatGPT's review of revision 8 (each point reasoned, not taken on authority)

**A principle first.** These stories are the plan. The implementing agent decides **how**. The stories fix **what** and the **properties** a test must show. Where ChatGPT's points were about missing requirements, contradictions or facts, I acted on them. Where they asked the plan to prescribe more implementation, I declined, with reasons.

| # | ChatGPT point | My reasoning | Verdict | Change |
|---|---|---|---|---|
| 1 | DC-11 (fixed window), the K-adjusted cutoff and δ = 1%-only placebo power change v16 | Correct as fact. My changes had real motives, but the owner's rule is "no deviation from v16". v16's rules are workable; their costs (a noisy estimate, compounding checks) can be **reported** rather than designed away. | Accept | v16's window rule, literal tolerance and both δ restored; costs reported |
| 2a | Registered power must be the selected test's own power (take the lower of the two) | **I disagree.** v16 §8.3 sets the window from "the step-3 analysis" of §8.2, i.e. power under the replay's measured dependence. v16 §8.5 item 6 **reports** each method's placebo power. "The lower of the two" would be a new rule. It would also bind on the placebo construction, whose dependence §8.5 itself says may differ from the real comparison's. | **Push back** | Window from §8.2's analysis; method power reported beside it |
| 2b | Fees, interest and operating costs are not deterministic | Correct: fees depend on fills, interest on idle cash, run costs on failures and pauses. Removing them would remove real uncertainty about net profit. | Accept | Only fixed, pre-declared calendar fees may be set aside |
| 2c | Specify centring, normalisation and H3 pooling | **Partly.** Pooling: correct that H3's paths share one history, which is a requirement, so it is stated. Centring and normalisation are implementation choices; prescribing them is how revisions 5–8 became disputes about formulas. | Partly accept | A coverage **property** on four processes, not a formula |
| 3 | Fixtures used the wrong multiplier at two lengths; use one executable specification | The arithmetic error was real; I reproduced ChatGPT's numbers. But the cure is not more code in the plan. The plan states the property; the builder's tests carry the numbers. During review I did check that the property is achievable: one method reached 95.5–98.9% coverage on the three Gaussian processes. The independent reviewer then showed that the same method reached only 82–94% on a fat-tailed GARCH process. So the fat-tailed case is now in the property, with a stop-and-report rule if it cannot be met. | Accept the error; decline the code appendix | Formula-derived fixtures removed; property-based criteria |
| 4 | Dividend tax contract incomplete; wrong "equity unchanged" sentence; split identity; name the price basis | Correct and material. Prices are not dividend-adjusted (`auto_adjust=False`), so omitting dividends biases every long position. The tax **contract** belongs in the plan (once only, bridge intact); the rates and the Dutch-tax reading are scenario parameters. | Accept the contract; rates stay parameters | ST-15 to ST-17 rules; fixture I-7; split identity; basis named; the Box 3 sentence corrected for C1, C2 and 2028 (the reviewer's finding) |
| 5 | "Cannot overshoot" is false; S is not governing economics; the ST-58/ST-43 cut-off clash; billing change as a deviation | All four are factual. On the remedy, I chose **v16's check unchanged plus reported excess** rather than ChatGPT's "reserve an enforceable maximum". The latter would change v16 §5.3's rule, and the owner asked for no deviation; truthful wording and reporting already meet the concern. | Accept the facts; v16-faithful remedy | "Target" wording; excess recorded ($6 in the fixture); S as a stress view; one exception; billing change as a dated fact |
| 6 | Empty verification can pass; fixture (vi) ignores harm precedence; inconsistent tokens | Logic errors in the document. | Accept | Fixed |

**On ChatGPT's remark that the 76% figure assumes independent checks:** correct. Revision 9 reports a simulated figure on the real window and family layout instead.

**Independent reviewer's check of the draft (7 findings), each reasoned:**
- **Accepted:**
  - fat-tailed coverage (now a required property);
  - one definition of degenerate ("neither arm submits an order");
  - the stale "validated at 250 sessions only";
  - the Box 3 sentence;
  - "only DC-3 changes v16" being false (O-3 now lists DC-3 and DC-12(5)).
- **Made moot:** two findings no longer apply, because the parts they concerned are removed: "demonstrated power ignores undefined windows" (method power no longer sets the window) and "the fixed-slot paths need a cash rule" (the fixed slot was my implementation choice, it departed from v16 §8.2's "actual exposure series", and it is gone).

### 4i. Reply to ChatGPT's review of revision 9 (each point checked and reasoned)

| # | ChatGPT point | My check (evidence) | My reasoning | Verdict | Change |
|---|---|---|---|---|---|
| 1 | `ohlc_raw` is not as-traded | Queried: HDFCBANK 2025-08-22 `ohlc_raw` close 982.3, identical to `ohlc`. `collectors/prices.py` lines 21–22 record NSE's as-traded 1,964.60 for the same day. No `data/india/adjustments/` folder exists. | Wrong prices change affordability, quantities, costs and later trades. A generic split fixture could not catch a basis error in the source data. | **Accept** | Reconstruction from each source's own adjustment basis; real HDFCBANK fixture; no-double-adjustment fixture |
| 2 | Dividend inputs and eligibility incomplete | Queried: `event_history` ex-dividend rows have `date` and `amount` only (no payment date), with US upcoming amounts null. `HISTORY_COLUMNS` = OHLCV only. Eligibility: on and after the ex-date shares trade without the dividend, so a buy on the ex-date earns nothing and a sale on it keeps the entitlement. | Correct and material: crediting the wrong trade, or making cash available early, could fund trades that could not happen. **Where I go further than ChatGPT:** its "no invented cash availability" would lock the cash forever when no payment date is recorded, which understates the account. A **declared latest payment date** errs only late, never early, and is disclosed. I also added the **amount basis**: per-share dividends can be source-adjusted for later bonuses too. | **Accept, refined** | Eligibility, amount basis, a payment-date contract with a declared latest date, a frozen corporate-actions record; four tests |
| 3 | Actual bills vs the registered arrangement contradict each other for S2 and S3 | The revision-9 text confirms it: DC-10 said "governing forward economics always use the actual calls and bills", while ST-39 said "S2 and S3 use the billing arrangement recorded at registration". | v16 defines S3 as "money kept after all deductions" and the owner's objective is net profit, so actual costs must decide. Power and the window stay as registered, because they were fixed before the window and must not move with outcomes or bills. | **Accept** | S2 and S3 on actual dated costs; the registered-assumption figure labelled beside them; billing-change fixture (+€100 trading, −€150 bills → −€50, no profitability label) |
| 4 | Coverage alone can be met by a uselessly wide estimate; state the processes; say what kind of power each figure is | A bound inflated without limit covers 100% of cases and makes every result "Inconclusive". That is the opposite failure, and coverage alone cannot detect it. | Correct. The plan cannot fix a width threshold in advance without arbitrariness, so it requires the width to be **reported** and reviewed at G2, and names the failure mode. Stating the processes and their parameters is test design, not implementation, so it belongs in the plan. ChatGPT explicitly did not ask for "the lower of the two powers", which matches my earlier pushback. | **Accept** | Width reporting; four processes with parameters, declared in advance; a label on every power figure |

**On ChatGPT's recommendation to start the unaffected work now:** the accounting, routine and policy stories other than ST-12, ST-30, ST-38 and ST-39 have not changed in the last two reviews. Starting them is the owner's decision.

### 4j. Reply to ChatGPT's review of revision 10 (each point reasoned)

| # | ChatGPT point | My reasoning and evidence | Verdict | Change |
|---|---|---|---|---|
| 1 | "Declared latest payment date" is not a verified upper limit, so unconfirmed dividend cash could fund trades early | **I re-examined my own argument, and it fails.** I had relied on India's 30-day payment rule, but that rule runs from the dividend's **declaration**. Interim dividends are declared before the record date; **final** dividends are declared at the annual meeting, which can be weeks after the record and ex-dates, so payment can legally arrive later than ex-date + 30 days. For US dividends there is no statutory limit at all. ChatGPT's day-30 versus day-45 example is therefore realistic, and a purchase funded by money not yet received would distort the later trades and their profit. ChatGPT's point that keeping a receivable preserves equity is also right: holding the cash back removes nothing from the account's value; it only stops the account from spending money it does not have. | **Accept** (my earlier claim withdrawn) | Forward and rehearsal accounts: spendable only on a verified payment date or a recorded receipt. Replays: a labelled assumed date with a timing sensitivity. Missing amount or basis → "incomplete", never zero. Three tests |
| 2 | Two definitions of "degenerate" disagree | Confirmed in the revision-10 text: ST-38 said "neither arm submits an order", while DC-6 still said "zero sample variance of the trading part". Orders placed but never filled satisfy the second and not the first. That is a contradiction I left behind when I changed ST-38 in revision 9. Both cases leave no comparison variability to estimate, so both must be excluded. | **Accept** | One rule in ST-38 and DC-6: `no_orders` and `zero_variance` are both excluded, with the reason reported; a fixture for submitted-but-unfilled orders |

**On ChatGPT's statement that revision 10 is good enough to start implementation:** these two corrections touch only the dividend behaviour (ST-12) and the evaluation (ST-38). Every other story is unchanged since revision 9. When building starts is the owner's decision.

## Appendix 5: Dependency check

All "Depends on" lines were parsed mechanically (stories ST-01 to ST-58; gate and phase references excluded). **What was checked (revisions 4 and 5):** the "Depends on" lines **and** every story reference inside **acceptance criteria** (revision 3 checked only the former, which hid the ST-20 → ST-42 loop). That check found one more hidden reference: ST-23's acceptance required the forecast scoreboard (ST-32). It is removed: ST-23 now tests only its own records (the `forecast_stage` field), and ST-32 tests separate scoring on fixtures of all three stages. Result: **no cycles and no uncovered acceptance references** (58 stories checked; ranges such as "ST-03 to ST-19" expanded). Revision 5 added two dependencies, ST-35 → ST-36 (the harm prong uses the candidate methods) and ST-30 → ST-19 (the cost schedule). Revision 6 added ST-39 → ST-38 (the integrated path fixture runs through the power code) and ST-37 → ST-46 (the isolation test re-runs ST-46's recalibration; found by the acceptance-criteria check). Revision 7 added ST-38 → ST-20; revision 8 removes it, because ST-38 is now a pure calculator, and the replayed guard is tested in ST-30 and ST-58. Revision 8 adds ST-10 → ST-57.

**What this check cannot see (corrected in revision 8):** it reads story IDs only. An acceptance criterion that needs another story's code without naming its ID, such as revision 7's Step-2 fixtures that used the Step-3 policy wrapper, is invisible to it. Revision 8 moved every such fixture to ST-58 and labels each Step-2 acceptance list "no policy code needed"; the judge checks this wording at G2. All point to earlier or same-phase stories, and everything is re-checked. The longest chain runs from ST-02 through the accounting core, the wrapper and the policies to ST-30, ST-58 and ST-43.

**Phase-order check:** no Step 1 or Step 2 story depends on a Step 3 story. The one cross-phase dependency found is intentional: **ST-24** (the descriptive four-week cost study, Routine) depends on ST-30. It runs on its own timetable once ST-30 exists, and blocks no gate.

## Appendix 6: Change history of revisions 2 to 10 (historical record only)

*These are the change logs as they were written. Later revisions withdrew or corrected several of them (marked in each later log and in Appendix 4). They are not requirements; the stories and Appendix 2 above are. Revision 8's fixed window, K-adjusted cutoff, restart blocks, prescribed estimator and "can no longer overshoot" claim are all withdrawn in revision 9.*

**What changed in revision 8 (a full self-review before sending; reply with evidence in Appendix 4, section 4g).** Before sending, the whole document was re-read end to end, and an independent expert reviewer (the judge agent) attacked it in parallel. Every finding was checked against the repository, v16 or a recomputation before it was accepted. The accounting stories ST-02 to ST-19 are unchanged except where a finding named them. The main changes:
- **The statistics are simpler and sturdier (ST-37, ST-38, DC-9, DC-11).**
  - Revision 7's block-bootstrap families and their 90% "adequacy" test are **withdrawn**. The reviewer simulated it: on ordinary independent data of realistic length (1,850 sessions), it wrongly declared "not representable" in 13.5% of cases. That alone would make about 58% of H1 runs, and about 93% of H3 runs, "Descriptive only" for no reason.
  - **Power now uses v16 §8.2's own formula with the measured long-run variance** of each comparison, at 126, 189 and 250 sessions as v16 requires. That captures the comparison's dependence, both arms' exposure and the market factor, and needs no random generator. Because the estimate is imprecise with seven years of data, the registered power uses a **95% upper bound** of that variance; the reviewer's simulation shows it holds in 96–99% of cases.
  - **Every test window is 250 sessions (DC-11).** This is a registered deviation from v16's "shortest adequate window" rule. A noisy power estimate makes that rule's choice noisy in both directions, and the harmful direction is a window that is too short. 250 is v16's own cap and, by v16's own figures, the likely outcome anyway.
- **Method validation is fixed (ST-37).**
  - **Placebo pairs only, as v16 §8.5 describes.** Each pair is driven by the more active arm's pre-open orders.
  - Families in which neither arm ever trades are excluded rather than silently deciding the choice.
  - Undefined windows no longer dilute false-alarm rates.
  - The tolerance is adjusted for the number of checks. Revision 7 would have failed an exactly correct method 76% of the time under H3's 54 checks.
- **The replay and the live ledger are more realistic (ST-12, ST-18, ST-30, DC-12):**
  - dividends credited, net of withholding, in the forward accounts as well as the replay;
  - sizing on the prices that actually traded, not later split-adjusted ones;
  - the results-blackout gap before Oct 2023 handled;
  - the long-history data frozen and hashed;
  - one rule each for tax years, FX "overnight" moves and restart capital.
- **The budget guard can no longer overshoot the ceiling (ST-20, DC-10).** A step runs only if its own cost fits under its tier, and the guard's scope and inputs are defined.
- **The harm stop is fully specified (ST-35, DC-7):** its null hypothesis, interim lengths, constant series and a policy with two comparators.
- **The six methods are pinned down (ST-36):** kernel, plug-in, replicates, p-value form, block rule and seeds.
- **Phase order is corrected.** Fixtures that need policy code moved from Step-2 stories to Step-3 stories. Appendix 5 now admits what its earlier check missed.
- **The change history is moved out of the way:** revisions 2–7's change logs are kept verbatim as history in Appendix 6, so that withdrawn statements are not read as current requirements.

**What changed from revision 6** (ChatGPT's review of revision 6; point-by-point reply with the evidence in Appendix 4, section 4f). The evaluation stories ST-30, ST-37 to ST-39 and ST-43 change, and so does the budget guard ST-20, by defining v16's "committed spend". The other accounting stories are untouched.
- **The block bootstrap is an approximation, sized and checked (ST-37, DC-9).** Revision 6 claimed that 63-session blocks keep dependence "within 63 sessions". That is false: independent blocks also cut dependence inside that range. ChatGPT's counterexample, which I reproduced, is a moving average whose dependence ends at lag 62. The variance multiplier of a 250-session mean is 57.71, but 41.84 with blocks of 63, 63, 63 and 61, so the detectable advantage is 3.20% a month against 2.72%. The block length is now chosen per scenario and set from {21, 63, 126}: the shortest one that keeps **at least 90% of the variance of window averages** at all three test lengths. If none does, the scenario's dependence is **"not representable"** and that hypothesis cannot be validated; it goes down DC-7's "Descriptive only" path, never silently to a confirmatory label. The fixtures have exact expected outcomes: independent data → 21, AR(1) 0.8 → 63, dependence concentrated at lag 30 → 126, ChatGPT's MA(62) → not representable. The wording on centring is corrected.
- **The cost view no longer chooses itself (DC-6, DC-10, ST-20, ST-38, ST-43).** Revision 6's claim that the per-token view switches every paid step off was **unsupported**. It assumed a "projected" reading of the budget guard that v16's text does not give: v16 says "spend to date plus committed spend". With committed spend defined (DC-10) and the guard simulated day by day, $16 a day for both markets stops Opus from day 12, the traders from day 15, news from day 16, and leaves only unpaid steps from day 17. So in that stress case the AI runs about two-thirds of each month; it is not off. The $8 figure is now labelled an old-workflow stress assumption. **All three billing arrangements of v16 §5.1** get a complete conditional protocol computed in advance: an existing subscription with no incremental bill, a subscription taken for this tool, and per-token. The arrangement actually in force, recorded with evidence at registration, selects which one governs. The fixture that hard-coded my conclusion is removed.
- **The H3 and placebo order is fully specified (ST-37, ST-38, DC-6).** Every random entry inherits a horizon and a gate decision from a named source: a copied entry takes B's horizon and decision; any other entry takes those of the exposure-source entry it stands in for. An integrated fixture traces entry, occupied slots, planned exit and the next entry opportunity.
- **Smaller contracts:**
  - the selection-isolation rule is scoped to set-local inputs, with the fixed nuisance inputs named as the only exception, and validation is described as conditional on them;
  - constant and zero-variance windows have a defined outcome;
  - an H3 scenario is degenerate only if all 200 of its paths are;
  - ST-39 uses one structured outcome from ST-37 and ST-38.

**What changed from revision 5** (ChatGPT's review of revision 5; point-by-point reply with the evidence in Appendix 4, section 4e). *Revision 7 corrects two of these revision-6 changes: the 63-session claim, and the governing cost view.* Only the evaluation protocol (ST-30, ST-35, ST-37 to ST-39, ST-43, DC-6, DC-7, DC-9) changes; the accounting stories are untouched.
- **Power now comes from the comparison itself, with its own dependence (ST-37, ST-38, DC-9).** Revision 5 rescaled symmetric placebo pairs so that their daily standard deviation matched the comparison's. ChatGPT showed that this keeps the placebo's serial dependence and loses the comparison's market factor. With the same daily SD of 0.1%, the detectable advantage at 250 sessions is 0.42% a month for independent days but 1.26% under AR(1) dependence of 0.8 (recomputed by Claude). Scaling is withdrawn. Power and an extra validity family now come from a **circular block bootstrap of each comparison's own replayed daily difference** (blocks of 63 sessions, centred so that the null is exact under resampling). This keeps both arms' exposure, including active-against-cash, the common market factor and serial dependence up to a quarter. The symmetric placebo pairs stay as v16 §8.5's validity family.
- **H3's scenario paths are now asymmetric.** Arm B is the replayed model-only account (often in cash in India); arm A follows the scenario's entry counts and overlap rule.
- **The candidate-only "quiet" rule is withdrawn (DC-6).** A scenario is excluded only if the **paired** difference is degenerate, meaning zero on every session of the set. A comparison that is sparse but variable is kept, such as a rule surrogate in cash against an active momentum account.
- **One deterministic procedure (DC-9):**
  - qualification at each of 126, 189 and 250 sessions;
  - method selection at 250 sessions on the lower envelope across scenarios;
  - the window chosen on the lower envelope at each length;
  - ties broken by v16's method order;
  - one governing cost view;
  - every empty branch defined, with an integrated fixture through ST-37 → ST-38 → ST-39.
- **The governing cost view is named (DC-6).** For the protocol it is "an existing subscription with no incremental bill". At v16's own per-token estimate (about $336 a month for two markets), projected spend is above the 100% tier of the $250 ceiling, so every paid AI step would be switched off and the AI comparisons would test nothing. That view is run and reported in full. For the money conditions S2 and S3, the billing basis recorded at registration governs; if it is unconfirmed, both are computed and the one less favourable to the candidate decides.
- **Input provenance (ST-37, DC-9).** Inputs are split into **set-local** inputs, recomputed from each set's own sessions, and **fixed nuisance inputs**: ST-46's FX buffer and stresses, and the US intraday exit proxy, whose 5-minute data exist only recently. The isolation test recalibrates everything upstream and allows changes only through the listed nuisance inputs.
- **The harm-stop fallback is labelled for what it is (DC-7):** a precautionary rule. Its report names the triggering method and marks it "unvalidated".

**What changed from revision 4** (ChatGPT's review of revision 4; point-by-point reply with the evidence in Appendix 4, section 4d). *Revision 6 withdraws three of these revision-5 changes: the H1/H2 rescaling, the candidate-only activity threshold of 12 entries, and the symmetric-only H3 pairs.*
- **The historical universe is declared, not reconstructed (DC-8, ST-30).** Revision 4 required a point-in-time universe from the stored watchlist events. That cannot work: all 40 events are seed events recorded on 7 Oct 2026 and effective from 7 Oct 2024, so the lifecycle loader returns **0 companies** on every date before 7 Oct 2024 (verified on 3 Jan 2011, 29 Jun 2018 and 6 Oct 2024; 20 from 7 Oct 2024). The replay now uses a frozen **retrospective research universe**: today's 20 companies per market with their recorded sectors, each entering when its inputs exist. It is labelled as chosen with hindsight (survivorship bias), and no event is backdated.
- **Null experiments are zero by construction, not by centring (ST-37, DC-9).** Revision 4's constant-centred null experiments (N2) are withdrawn. Every null experiment is now a **symmetric placebo pair**, as v16 §8.5 describes: two exchangeable random arms with the scenario's exposure profile and overlap. Its expected statistic is exactly zero in every window, given that window's history, with nothing estimated. For H1 and H2, the pair is rescaled to the paired variability measured in the replay. The rescaling cannot change any rejection rate, because all six methods are scale-invariant. Every quantity a selection experiment uses comes from the selection period only, and a test proves that verification data cannot change selection.
- **Scenarios cannot be quiet and still govern (DC-6, ST-38).** India's stored model probability is 0.466–0.474 on every one of its 262 stored N+k rows, below the 0.55 threshold, so the central w = 0.05 surrogate can never trade there. This was ChatGPT's point. **I found the same problem in H1 and H2:** the India rule surrogate has no news shift, so it is the same flat model. Scenarios that trade less than about once a month are now flagged "quiet" and can never set the power or the window. H3 now uses a grid that covers v16's own overlap ends ("mostly the same stocks" and "independent selections"), and is governed by its weakest active scenario.
- **The surrogates carry their deployment costs again (DC-6).** Revision 3 had this and revision 4 lost it. Each replayed arm that stands for a costed policy is charged that policy's §5.2 components as accruals. Two declared views are reported: subscription and per-token. The budget tiers are applied to them.
- **"Stopped for harm" keeps first place (DC-7, ST-35, ST-39).** The no-adequate-method fallback no longer overrides v16 §8.9's precedence. **I also closed a gap ChatGPT did not raise:** the harm stop's p-value prong needs a method, so when none is adequate, the most protective of the six is used.
- **The registered power comes from the verification set (ST-38).** Revision 4 did not say which set's power is registered. The selection set's power is biased upwards, because the method was chosen there as the best.
- **ST-01 publishes every clarification (DC-1 to DC-9 at that revision)**, and a test compares the errata file with Appendix 2.

**What changed from revision 3** (ChatGPT's review of revision 3; point-by-point reply in Appendix 4, section 4c). *Two of these revision-4 changes are withdrawn in revision 5: the constant-centred null experiments and the point-in-time historical universe.*
- **DC-6 rebuilt.** Revision 3's "copy with probability s, otherwise random" generator was mislabelled: its real match rate is s + (1 − s)/M, not s. It also left undefined what happens when the model-only arm does not trade, which is the usual India case. The H3 scenario is now a **random-adjustment surrogate**: both arms run independently on their own account state, and the AI-like arm adds a random adjustment u ~ Uniform(−w, +w) to the model probability. That is the same band within which the real Sonnet combined trader may move the model score (at most ±0.10). Realised overlap and exposure are **measured and reported**, not assumed.
- **Null, scenario and power experiments are separated (ST-37).** Every null is checked to have a zero expected paired statistic after the deployment costs included in it, and every power experiment the intended +0.5% or +1% a month. The constant-centring rule for asymmetric scenario pairs is documented.
- **ST-20's hidden completion loop is removed:** its "tiers are in the manifest" check moved to ST-42. B.21 is now a Step-1 fixture.
- **Historical analysis state is separated from deployment state:** a point-in-time universe for the replay and power work, and the frozen snapshot for the registered policies (ST-30, ST-42, ST-43, ST-58).
- **Reservation release timing** at the open is pinned (ST-08).
- **The "no adequate method" branch** of the power calculator and registration is defined (ST-38, DC-7).

**What changed from revision 2** (ChatGPT's review of revision 2; point-by-point reply in Appendix 4, section 4b):
- **Dependency cycles removed:**
  - ST-09 no longer depends on ST-46;
  - ST-56 is now only the Step-1 cost and producer contract, and its manifest coverage lives in ST-42.

  A mechanical check of every "Depends on" line finds **no cycle** (Appendix 5).
- **H3's central scenario is defined numerically (DC-6).** H1's governing surrogate is named.
- **Market-at-open affordability:** fixed quantity, no resizing, no negative cash (DC-3).
- **Restored in acceptance:**
  - the placebo construction;
  - the H3 surrogate placebos;
  - the "placebos do not validate every adaptive AI policy" statement;
  - power **under measured dependence**.
- **Gates G1–G4 are cumulative.** ST-01, ST-20 and ST-56 are in G1; ST-45 is in G3.
- **Registration:** selection inputs are separated from the forward-outcome disclosure. The ≤ 9 Oct cut-off applies to every derived input.
- **One snapshot time** for the protected universe and sectors (DC-2).
- **A deliberate change ends only the altered policy's window.**
- **DC-5 corrected:** the remaining volatility gap is caused by the **order in which companies are listed before the random draws**. Claude reproduced ChatGPT's figures exactly by sorting the companies alphabetically.
- **"Open items: none" is withdrawn.** Appendix 1 now lists the open items (O-1 to O-4).

**Earlier history:** revision 1's claim that "these stories implement v16 exactly, nothing added" was withdrawn in revision 2.
- **In its place:**
  - **Appendix 1:** a requirement → story → test map, which exposes anything unresolved;
  - **Appendix 2:** a **design clarification register** (then DC-1 to DC-6; now DC-1 to DC-10). It records, openly, every place where a story must go beyond or clarify v16's wording. **v16 itself stays unchanged and keeps its hash.** The clarifications are published as a separate errata file (ST-01).
- **Stories added (4):**
  - ST-55: integrated accounting fixtures;
  - ST-56: graph-builder dependency;
  - ST-57: live-instruction infrastructure, split out of ST-31 as Step 1 per §10;
  - ST-58: Step 3 evaluation runs, split from the Step 2 machinery.
  
  **Total: 58 stories (51 in Steps 1–3 and routine, 7 deferred)**, unchanged in revision 3.
- **Phase completion gates** are added (section "Gates").

**What changed in revision 9** (ChatGPT's review of revision 8 and an independent check of the draft; every point was reasoned through before acting on it, with the reasons in Appendix 4, section 4h):
- **v16's rules are restored where revision 8 had changed them.**
  - The window rule is v16 §8.3's: the shortest of 126, 189 or 250 sessions with ≥ 80% power, else 250. DC-11 is withdrawn.
  - The method tolerance is v16 §8.5's literal "α + 2 Monte Carlo SE".
  - Placebo power is reported at δ = 0.5% and 1% on both sets.
  - The reason: the owner's rule is "no deviation from v16". Revision 8's changes had real motives (a noisy power estimate; checks that compound), so the plan now **reports** those costs instead of changing the rules.
- **Power follows v16 §8.2–8.3:** the step-3 power analysis under the replay's measured dependence and actual exposure sets the window. The selected method's placebo power is **reported** beside it (v16 §8.5 item 6). I did **not** adopt ChatGPT's proposal to register "the lower of the two", which would be a rule v16 does not have (reasons in 4h).
- **Statistical stories state required properties, not formulas.** The cautious variance estimate must cover the true value in ≥ 95% of simulated series for four stated test processes, including a fat-tailed, volatility-clustering one that resembles real trading P&L. The builder chooses the method.
- **Dividends** enter every account, with tax counted once and the tax bridge intact, proven by an integrated fixture (I-7). Splits must preserve wealth exactly, and the price basis is named. Rates are dated, owner-confirmable parameters.
- **The budget guard keeps v16 §5.3's check unchanged and is described truthfully:** the ceiling is a target the last admitted step can cross, and any excess is recorded and reported. The word "guaranteed" is withdrawn.
- **Contracts reconciled:**
  - one definition of "degenerate";
  - ST-58 carries ST-43's single exception;
  - a billing change is a recorded fact, not a deviation;
  - an empty verification set never passes;
  - "Stopped for harm" keeps precedence in every fixture.
- **O-3 lists honestly which DCs change a rule v16 states:** DC-3 (market fills above L) and DC-12(5) (measuring the FX "overnight" move close to close, because stored daily EUR/USD bars have open = close). All the others fill gaps v16 leaves open.

**What changed in revision 10** (ChatGPT's review of revision 9: four targeted points, each checked against the repository and reasoned through before acting on it; reply in Appendix 4, section 4i). Only ST-12, ST-30, ST-38, ST-39 and DC-10/DC-12 change.
- **The as-traded price basis is corrected (ST-30, DC-12).** Revision 9 named `ohlc_raw` / `bars_raw` as "prices that actually traded". That is wrong, as I checked: `ohlc_raw` holds ₹982.30 for HDFCBANK on 22 Aug 2025, while the collector's own documentation records the as-traded NSE price as ₹1,964.60 (before the 1:1 bonus). India has no stored adjustment records, so these views show the source's own already-adjusted basis. As-traded prices are now reconstructed from each source's actual adjustment basis, with this real example as a fixture.
- **The dividend input contract and eligibility rule are completed (ST-12, ST-30, DC-12).** I checked the data:
  - stored dividend events carry an ex-date and an amount, but **no payment date**, and upcoming US amounts are empty;
  - the long-history cache holds only open, high, low, close and volume.

  The plan now says where amounts, payment dates and split events come from, on which share basis, and which holding earns a dividend (bought before the ex-date; a sale on the ex-date keeps it). A missing payment date makes the cash available only at a declared latest date, never earlier. Three tests are added.
- **Actual bills govern the money result (ST-39, DC-10).** Revision 9 contradicted itself: DC-10 said actual bills govern forward economics, while ST-39 used the registered arrangement for S2 and S3. Actual dated costs now govern S2 and S3. The registered-assumption figure is shown beside them, labelled. A billing-change fixture proves that a loss cannot be labelled profitable on outdated costs.
- **The power check reports usefulness, not just safety (ST-38).**
  - The coverage test now also reports how wide the cautious estimate is, so a uselessly wide estimate cannot pass unnoticed.
  - The four test processes are fully stated, with their parameters.
  - Every power figure is labelled either "analytical planning approximation" or "demonstrated for the selected test".

Research only. The system never places real trades and never connects to a broker.
