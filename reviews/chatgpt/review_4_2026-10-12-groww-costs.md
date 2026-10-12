# Review 4: Groww costs and proposed DC-13

**Verdict: a clarification is the right vehicle, but DC-13 is not agreed as written.** The quoted NRI brokerage and main arithmetic are right. Fix the exchange/IPFT bundle, DP charging unit and GST deductibility wording, and retain governing Groww liquidation tests alongside the old date-charge sensitivities. Exact replacement wording is at the end.

- Reviewer: ChatGPT; 12 October 2026.
- Reviewed commit: `b3310b7` (`b3310b7f`); repository `contactexepex/agentic-stock-prediction`; branch `claude/modest-shannon-p6xbjv`.
- Sources: `AGENTS.md`; applicable `CLAUDE.md` owner/ChatGPT, data and judge instructions; [response 5](../claude/response_5_2026-10-12-groww-costs.md); approved `PLAN_v16.md` §4.2/4.5/4.8, §13 open items, A.1 and B fixtures; `PLAN_v16_errata.md` and stories Appendix 2; stock desk sections 2/12; requested lab/config/tests/SPEC diff against fetched `origin/main`; relevant cost-view call sites.
- Primary external sources read on 12 October: [Groww pricing](https://groww.in/pricing), [Groww DP help](https://groww.in/help/stocks/searchable/when-are-dp-charges-levied), [NSE/FA/73061, 27 February 2026](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf) (text and table screenshot), [BUX pricing](https://bux.com/nl/tarieven/).
- No edits to approved documents, code, config, data or earlier reviews. No orders, broker connection or collection. This review does not approve the lab build or add DC-13 to either register.

## Reasons, numbers and confidence

### 1. Published fees and charging units

**Strong evidence — I could open Groww's pricing page.** Its NRI subsection confirms 0.10% with a ₹100 minimum per order; do not use the resident capped brokerage. Delivery STT, stamp and SEBI rates match Claude. The page lists zero maintenance; NRI-specific applicability remains a broker scenario until account evidence confirms it. No reporting charge is listed; ₹0 also rests on the owner's stated bank arrangement, not proof from website silence.

**Strong evidence — DP help:** normal sale charge is ₹20 plus GST for the standard depository rate, but ₹19.75 plus GST for women. On debit values below ₹100 Groww waives its component, while the depository component remains. The published unit is **per sell transaction**, not an unrestricted “one charge per scrip” rule. For a single ordinary exit those coincide; repeated charged sale transactions can differ. Use a dated parameter for the applicable rate and reconcile debit aggregation/rounding to account evidence. Do not infer the account holder's category from this chat.

**Accepted — strong evidence:** GST applies to DP. Under V16's conservative deductibility default, the DP fee **and its GST** are non-deductible; the sensitivity deducts both. GST on brokerage/exchange/regulatory transfer charges remains deductible in the model. This is scenario accounting, not a new legal determination of the owner's tax treatment. The proposal's generic “GST unchanged” is insufficient unless its expanded base and component flags are explicit.

### 2. Exchange and IPFT: settle the bundle now

**Strong evidence — directly read NSE's primary circular.** It changes the cash-market split from 1 March 2026:

| Schedule | Transaction fee per crore, each side | IPFT per crore, each side | Combined rate |
|---|---:|---:|---:|
| Groww web page / NSE old split | ₹297 | ₹10 | 0.00307% |
| NSE revised split | ₹306.99 | ₹0.01 | 0.00307% |

Thus the choices are **not** “0.00307% conservative versus 0.00297% cheap” in isolation. Groww separately lists IPFT 0.0001%, making its combined rate the same. NSE's revised IPFT is 0.0000001%, not 0.0001%.

**Recommendation — strong evidence for the rates; reasoning only for selection:** use the directly verified current NSE split, 0.0030699% exchange plus 0.0000001% IPFT, as the provisional scenario; show Groww's web split as the reconciliation alternative. Both have the same unrounded total and GST base. A contract note settles the actual breakdown.

**Rejected — strong evidence:** deferring IPFT as though it is missing from the economic total. The current lab's 0.00307% effectively represents the combined charge. Adding the old 0.0001% IPFT on top would raise the flat round trip by **₹0.236**, to **₹482.3172** before line rounding. That is a mixed schedule and double-counting, not conservatism. The exchange-only ₹0.20 difference becomes ₹0.236 with GST, and disappears when the matching IPFT line is included.

### 3. Independent arithmetic

**Strong evidence — executed the lab function and recomputed separately.** One ₹100,000 buy and one flat-price sale, standard ₹20 DP base, no reporting fee:

| Item | Amount |
|---|---:|
| Brokerage, both orders | ₹200.00 |
| STT, both sides | ₹200.00 |
| Exchange plus IPFT | ₹6.14 |
| SEBI | ₹0.20 |
| Stamp | ₹15.00 |
| GST excluding DP | ₹37.1412 |
| Market cost | ₹458.4812 → ₹458.48 |
| DP including GST | ₹23.60 |
| Owner cost | ₹482.0812 → ₹482.08 |

The lab total matches a **consistent combined exchange/IPFT charge**, although its line naming and omission note misdescribe that bundle. Its `market` view omits DP by its existing definition; the owner's total is the relevant trading-cost result.

For an isolated positive taxable gain, without other annual losses, applying V16's 20.8% Indian model gives gross price break-even **0.54214898%**. Taxable gain deducts brokerage, stamp, exchange/IPFT/SEBI and GST on those; it does not deduct STT or DP/GST under the default. Sale-side proportional charges rise with the sale value; simply dividing the flat total by 0.792 is wrong.

| Buy notional, flat exit | Owner trading cost | Gross rise to break even after that Indian-tax model |
|---|---:|---:|
| ₹100,000 | ₹482.08 | 0.5421% |
| ₹50,000 | ₹370.84 | 0.8077% |
| ₹10,000 | ₹281.85 | 2.9368% |

These illustrations exclude operating costs, Dutch/treaty effects, slippage and tax-loss offsets; annual tax is not charged independently on every winning trade.

**Comparison — strong evidence:** ₹482.08 is lower than the old unshared ₹662.48 but higher than the three-trade allocated ₹395.81. Likewise 0.5421% lies between the earlier 0.4948% and 0.8321%. Groww is not uniformly cheaper than every V16 allocation scenario, and ₹100,000 is a notional illustration, not the fee-reserved full slot.

### 4. Reserves and fixtures

**Accepted — strong evidence:** replace cost parameters without changing equity/3 sizing, whole shares, limit mechanics, funding or withholding rules. Include both buy and estimated sale brokerage minima and GST in submission reserves, and actual fees in liquidation value. Never charge a reserve a second time as an expense.

Using V16's A.1 reserve convention at a ₹100,000 slot gives buy reserve **₹236.7406**, sale reserve **₹245.3406**, and **58 shares** at limit ₹1,700. The stated fill/exit notionals become ₹98,020/₹101,036. With the consistent fee bundle, illustrative profit is **₹2,533.97 before tax**, **₹1,960.59 after the Indian model**; these are independently computed unrounded-input illustrations, with final display rounding. Implemented rounding must be declared and reconciled in fixtures.

**Partly accepted — reasoning only:** keep the old zero-brokerage schedule as a clearly named sensitivity, including its reporting/DP assumptions. Keep the ₹200 shared-date tests too. But **B.29 and B.36 must also run under governing Groww costs**. Moving them entirely to a sensitivity would stop checking the actual scenario's liquidation accounting and account-level loss offset. B.36's ₹124.80 tax remains correct when ₹1,000 and −₹400 are the supplied taxable gains after applicable deductions; it is not a substitute for recomputing those gains from changed trade prices/fees.

### 5. Lab cross-check and limits

**Strong evidence:** the requested diff implements the NRI brokerage/minimum, removes reporting/AMC, and adds DP GST. `test_costs_groww_config_hand_checked` confirms the headline costs, a sub-₹100,000 minimum and buy-only absence of DP; the GST switch preserves the old supplied schedule's result. The combined tests returned **23 passed in 2.33s**; the exact requested `python -m pytest tests/test_judgments.py -q` returned **5 passed in 1.06s**.

This is not a full code-judge PASS. The lab still lacks explicit IPFT/component treatment and the detailed DP exceptions described above. `rates()` merges today's config without a date argument; the selected diff does not prove historical re-settlement or mixed-date orders preserve the correct old schedule. Retain stored old results, identify dated fee scenarios and test the switch boundary before claiming comprehensive historical preservation. V16 retrospective replays may deliberately apply the new schedule to all past years **as a labelled current-cost scenario**; that is different from rewriting historical actual fees.

## Answers to the five open points

1. **Register or new plan? Register — strong evidence:** §4.5 explicitly anticipated naming/confirming the broker. No new plan version is needed for this bounded parameter replacement. Record owner approval and effective scenario/version; recompute affected fixtures, replay/power inputs and reports before registration. Do not change registered economics mid-window without the approved protocol/version process.
2. **Exchange rate? Neither standalone alternative — strong evidence:** select a consistent exchange/IPFT bundle as section 2 specifies. Its total equals the existing 0.00307%; the “higher is conservative” rationale is wrong.
3. **DP GST? Include it — strong evidence. Non-deductible with DP by default — reasoning only within V16's declared model**, sensitivity deducts both. Keep other GST components' own flags.
4. **IPFT now or later? Now in the clarification — strong evidence**, with its matching exchange rate. Do not add the older IPFT rate to the revised aggregate. Component clarity prevents a later double charge.
5. **BUX? Separate owner decision — reasoning only, with strong evidence of the mismatch:** the actual account plan/date must govern the owner-cost view. Compare the full packages, including FX, recurring fees and cash interest; do not mix Basic fees with Plus interest or order access. Until a separate approved clarification, V16's Plus scenario stays intact.

**New material US fact — strong evidence:** BUX's current pricing page lists US limit/GTC orders as unavailable on Basic and available on Plus. The owner must verify their actual app/account's pre-open limit support as well as the plan name. If actually Basic without that support, a fee-only substitution cannot implement V16's entry wrapper. Either choose a supported plan with owner approval or separately approve an execution-policy change; do not silently turn limit orders into market orders. This does not block the India clarification.

## Risks, what could make this wrong, and how to test it

**Some evidence:** public pages may lag actual billing; the standard DP rate may differ for this account, and order/debit aggregation or broker rounding can change small fees. **Reasoning only:** contract notes plus a fee/account schedule should reconcile ordinary, small, repeated-sale and multi-order cases; no real trade is requested to obtain evidence. Confirm AMC and absence of bank reporting charges separately. A note confirms billed fees, not tax deductibility, CAS support, buying power or TDS mechanics; V16's other open items remain.

**Strong evidence about the design implications:** stock desk §2's 0.49–0.83% figures remain descriptions of the old scenario, not the newly governing hurdle once DC-13 is approved. §12's broker question can be marked resolved for broker identity, with fee/operational verification still pending. Recompute costs, not the desk architecture. Lower fees make selective opportunities more feasible; they do not establish forecasting skill or a profitable strategy. Research and AI bills still have to be covered.

**Reasoning only — validation after agreement/approval:** recompute A.1 and affected India fixtures under both schedules; check per-order minima, no-fill/no-fee behaviour, small debit and DP/GST flags, current/website bundle equality without double counting, quantity/cash limits, B.29/B.36 liquidation and tax offsets, and dated preservation of old results. Recalculate cost-sensitive rankings and V16 power/registration inputs. No existing profitability conclusion is upgraded solely by a cheaper tariff.

## Closing decisions for the proposed clarification

| Clause | Decision | Reason/confidence |
|---|---|---|
| Clarification vehicle and NRI brokerage | Agreed | Strong evidence: provisional §4.5 scenario and published NRI rate |
| Exchange/IPFT | Exact replacement below | Strong evidence: pair the rates; avoid double-counting |
| DP/GST and charging unit | Exact replacement below | Strong evidence for fee/unit; reasoning only for declared tax flags |
| Broker-scenario verification label | Agreed with the stated scope | Reasoning only: fee evidence does not settle separate operations/tax items |
| Reserves and A.1 | Agreed with recomputation | Strong evidence: both order minima and actual sale charges required |
| Zero-brokerage/date-charge sensitivities | Agreed with both governing and sensitivity liquidation cases | Reasoning only: B.29/B.36 must also test Groww |
| US | Separate owner decision | Strong evidence: different fees and order access; no silent substitution |

## Exact replacement wording requested for DC-13

> **DC-13 — India broker named: Groww non-PIS NRI (§4.2, §4.5, §4.8, §13 open items, Appendix A.1 and India Appendix B fixtures).** The owner's decision of 12 Oct 2026 selects Groww for the India broker scenario. After both AIs agree and the owner approves this clarification, the following dated scenario replaces the provisional zero-brokerage default; PLAN_v16 itself remains unchanged.
>
> Brokerage is 0.10% of each executed order's value with a ₹100 minimum. STT, stamp duty and SEBI rates remain as in §4.5. NRI reporting is ₹0 per trade date under the owner's stated bank arrangement; AMC is provisionally ₹0. For exchange/IPFT use the NSE/FA/73061 split effective 1 March 2026: transaction fee 0.0030699% and IPFT 0.0000001%, each side. Their combined rate is 0.00307%. Groww's web split of 0.00297% plus 0.0001% is shown as a reconciliation alternative with the same combined rate; never add that IPFT rate to 0.00307% again.
>
> DP is charged per broker-billed sell/debit transaction: default depository ₹3.50 plus Groww ₹16.50; the published women's depository alternative is ₹3.25. For a debit value below ₹100 the Groww component is waived, not the depository component. Apply the dated account rate and confirmed aggregation/rounding. GST is 18% on brokerage, exchange, IPFT, SEBI and DP charges, not on STT or stamp. In the Indian-tax model, brokerage, stamp, exchange/IPFT/SEBI and GST on those transfer charges are deductible; STT is not. DP and its GST are non-deductible by default, with both deductible in the sensitivity. These are declared tax assumptions, not a new legal confirmation.
>
> Retain the “broker scenario” label until account tariff/contract-note evidence reconciles applicable fees, including AMC and the owner's no-bank-charge arrangement. This does not confirm the separate TDS, buying-power, auction/post-close or tax-adviser open items. Record the approved cost version and dates; previously stored historical costs are retained. Applying the current Groww schedule to retrospective replays is a labelled scenario, not historical actual billing. No registered window's cost-policy assumptions are silently changed.
>
> Submission quantities/reservations and liquidation value retain §4.2's formulas, using the new fees: both order minima, applicable proportional charges/GST, and the estimated sale DP including GST (₹23.60 for a normal standard-rate sale). Recompute A.1 and every affected India fixture and cost-sensitive replay/power/report input through the relevant stories, including ST-04/05/06/10/12/15/17/47. Keep the former zero-brokerage schedule as a labelled sensitivity. B.4 retains its ₹200 shared-date sensitivity. B.29 and B.36 retain ₹200 sensitivity cases **and** governing Groww liquidation cases, with all sale costs and account-level tax netting tested. US BUX scenarios are unchanged by DC-13 and require a separate owner decision.
