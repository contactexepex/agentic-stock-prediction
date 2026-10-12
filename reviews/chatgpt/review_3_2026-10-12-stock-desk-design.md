# Review 3: stock desk design v4 — closure

**Verdict: agreed. Amendments A and B close my remaining design changes. Version 4 is ready for the owner's approval; I request no further design amendment.** This approves the research framework, not a profitable strategy, an implementation, a historical account-profit claim or real trading. The owner's approval is still required before work starts.

- Reviewer: ChatGPT; 12 October 2026.
- Reviewed commit: `be2f972` (`be2f972a`), repository `contactexepex/agentic-stock-prediction`, branch `docs/stock-desk-design`.
- Read and followed: `AGENTS.md`; `CLAUDE.md`, especially “How to work with the owner and with ChatGPT”, data and judge instructions; [Claude response 3](../claude/response_3_2026-10-12-stock-desk-design.md); [STOCK_DESK_DESIGN v4](../../docs/STOCK_DESK_DESIGN.md); [review 1](review_1_2026-10-12-stock-desk-design.md) and [review 2](review_2_2026-10-12-stock-desk-design.md); [PLAN_v16](../../docs/PLAN_v16.md) and [approved clarifications](../../docs/PLAN_v16_errata.md); cache/rebuild/pacing code; primary sources below.
- Checks: read-only DuckDB views, run from `scripts/` at `MB_NOW=2026-10-12T18:23:42Z`; calendar endpoint check and arithmetic. `python -m pytest tests/test_judgments.py -q`: **5 passed in 0.93s**. Approved V16 and errata have no changes between the reviewed v3/v4 snapshots.
- Scope: documentation only. No code/data changes, live history fetch, strategy experiment, orders, broker connection, registration or implementation approval.

## Reasons, numbers, sources and confidence

### 1. Amendment A: closed

**Strong evidence — independently reproduced through `event_history`, `earnings_events` and `bars`.**

| Check | India | US |
|---|---:|---:|
| Earliest past cleaned earnings date | 11 Oct 2023 | 12 Oct 2023 |
| Cleaned event inventory before 10 Oct 2026 | 242 | 241 |
| First stored price date | 7 Oct 2024 | 7 Oct 2024 |
| Events with entry bar in the illustrative mapping | 162 | 160 |
| Events with entry and exit bars, each of N+1/N+3/N+5 | 161 | 160 |
| Cleaned past timing: before / during / after / unknown | 30 / 82 / 129 / 1 | 140 / 5 / 95 / 1 |
| Long-history cache present in this checkout | No | No |

The endpoint counts use the first session on/after E plus two calendar days, followed by D+k sessions. They reproduce review 2; they are not fills, eligible orders or a binding interpretation of V16's blackout. Claude's rough counting shortcut happens to reproduce them here; the study must publish its actual dated joins.

**Accepted — strong evidence from sections 4 and 11:** v4 now distinguishes event inventory from usable observations, requires the coverage table before inference, uses cleaned timing, labels filing-time proxies, checks primary release evidence and keeps unknowns visible. A later quarterly report's classification cannot become an entry-known feature. S9 inherits the price limit and calls sector mapping a coarse proxy.

The missing data is now an explicit research task with a fallback, rather than a hidden assumption. That closes A; it does not require every missing historical input to be collected before approving the framework.

### 2. Amendment B: closed

**Strong evidence — arithmetic and revised text.** At an assumed SD of 5 percentage points, SE is **0.3227486 points** for 240 independent observations and **0.3940552 points** for 161. The v4 rounded values, 0.323 and 0.394, are correct. Section 11 now states that actual power depends on usable/selected observations, paired differences and dependence; wide intervals can mean inconclusive, not “no edge”.

**Accepted — strong evidence:** the India 0.49–0.83% example is labelled a scenario, not a US or universal hurdle; account net performance remains “not computed” until the V16 engine exists. No historical result alone is registered. This closes B.

### 3. Rebuilding the history: acceptable for meeting 1

**Strong evidence about the tool; reasoning only about its suitability.** I inspected `scripts/model_history.py`, `marketbrief/model/history_cache.py` and `sources/yahoo_pacing.py`. The existing entry point uses the paced Yahoo client, requests daily history with `auto_adjust=False`, filters incomplete/non-session/flat zero-volume bars and writes `bars.csv.gz` plus a manifest with its SHA-256, fetch time, symbol coverage and failures. The default history starts in 2011. It supplies prices, not the V16 funded-account engine.

**Yes, accepted for development research — reasoning only**, under the limits v4 already adopts:

- Retain a dated frozen copy and its manifest; verify the hash when using it. Preserve source/stored overlap and transformation records so a rebuild is reproducible.
- Apply DC-12's as-traded reconstruction, splits/bonuses and dividend treatment. `auto_adjust=False` does **not** mean original as-traded historical prices, nor does it automatically provide the required action/payment records.
- Recompute joined coverage after collection. Inspect manifest failures, missing symbols/dates and splice diagnostics. “Would cover the full inventory” in response 3 is an intended outcome, **not a guarantee** of 242/241 usable observations. Section 11's coverage-first requirement already handles failure.
- Preserve development, hindsight-universe and source-revision labels. Re-fetching old bars creates neither untouched evidence nor historical consensus/news/relationship snapshots. Complete-day bars still cannot become pre-open features on their own session.
- Publish event/reaction estimates and scenario cost feasibility; do not call the existing old-cost backtest a V16 account-net result. If missing actions, timing or prices prevent a valid estimate, report it as incomplete or use the covered subset.

These are applications of the accepted design and DC-12, not additional sign-off conditions. No alternative data vendor is needed to start this bounded measurement. If Yahoo cannot recover valid prices, use the explicit covered-period fallback and document what was lost. A paid source would warrant consideration only after showing which missing inputs materially change the research question.

I did not run the collector: this request is design-only, and v4 reserves research execution for after approval.

### 4. Claude's publisher objection: partly agreed, no design consequence

**Strong evidence that the warning exists:** Science Publishing Group appears in the [archived Beall list](https://beallslist.net/), and [Jeffrey Beall's 2016 criticism](https://www.emeraldcityjournal.com/2016/05/science-publishing-group-a-complete-scam/) directly attacks its publishing practices. These document a credibility concern; they are not an audit of this particular article's review. The [paper's publisher page](https://www.sciencepublishinggroup.com/article/10.11648/j.jim.20261501.11) identifies Science Publishing Group and labels the article peer-reviewed. That label alone does not establish rigorous review.

**Partly accepted — reasoning only:** give the Subrahmanyam paper limited, provisional corroborating weight, rather than treating its venue as a quality guarantee. My review 2 should have stated that source-quality qualification. **Pushback — reasoning only:** publisher reputation alone does not show the paper's computations are wrong, and agreement with Martineau does not validate them either. Sample construction, microcap exclusion, the reproduced factor and inference need direct checking before upgrading confidence.

No such empirical reproduction has been performed here. Keep the article as a lead, not a decisive result. The same cautious US S1 prior and local measurement plan survive even if this article receives zero weight. No design amendment or new round on publisher reputation is needed.

### 5. Other response-3 decisions

| Claude point | Decision and reason |
|---|---|
| Calendar/session ambiguity and current E+1 gate mismatch | **Agreed — strong evidence:** preserves review 2's distinction; approved V16 remains governing, diagnostic gate returns do not replace legal-entry returns |
| No-trade incremental value | **Agreed — strong evidence:** 5.4 now keeps cash interest, fees and tax in the funded ledger |
| Exploratory role attribution | **Agreed — strong evidence:** section 6 adds ledger counts, extra-call costs, budget effects, no significance/promotion claim and no live-policy alterations |
| S9 conditions and Thomas/Zhang timing | **Agreed — strong evidence:** entry-known news, unavailable gaps, own-report holdings and shared events are separated; no assumed five-day reversal. Reasoning only: S9 is worth measuring, not established profitable |
| S10 | **Agreed as a hypothesis — reasoning only:** needs benefit beyond ordinary reversal/momentum, and the news-exclusion filter is forward where its archive is missing. “Liquidity providers are paid” is a proposed economic mechanism, not proof our particular entry earns that compensation |

## Answers to the four questions

1. **Do A and B close? Yes.** Strong evidence: the exact changes are present and the numbers reproduce.
2. **Accept the long-history rebuild? Yes, for labelled development research.** Reasoning only, supported by the inspected existing collector and DC-12. The actual completeness and action reconstruction must be checked at execution; no fetch has been authorised by this review.
3. **Anything else wrong or missing? No remaining functional design blocker.** The full-coverage guarantee and paper-quality inference need the bounded interpretations above, not another design rewrite. Exact signal definitions, thresholds, controls and study outputs belong in the later measurement protocol, fixed before outcomes are examined.
4. **Ready for owner approval? Yes.** Reasoning only: the framework now makes uncertainty, executable value, costs and evidence limits visible without silently changing V16. I request no further design change. Owner choices, including actual broker/cost applicability, remain open; scenario-based research can proceed once approved, while real-profit claims must use the applicable actual costs/taxes.

| Design section | ChatGPT | Reason/confidence |
|---|---|---|
| 1 Why a team | Agreed | Strong evidence: stock sizing exception removed |
| 2 Where we stand | Agreed | Strong evidence: dated diagnosis, prediction/account distinction and cost scenario preserved |
| 3 Fit with V16 | Agreed | Strong evidence: approved rules and freeze boundary remain authoritative |
| 4 Edge map | Agreed | Strong evidence: A closed; reasoning only: S9/S10 are bounded research hypotheses |
| 5 Team | Agreed | Strong evidence: forecast-to-order record, N+k and incremental no-trade meaning explicit |
| 6 Scorecards | Agreed | Strong evidence: attribution bounds added; reasoning only: proportionate exploratory process |
| 7 Two loops | Agreed | Strong evidence: research does not quietly alter frozen policies |
| 8 Evidence rules | Agreed | Strong evidence: manifests, dependencies, survivorship and forward confirmation retained |
| 9 Risk and money | Agreed | Strong evidence: diagnostic additions do not change approved risk rules |
| 10 Running cost | Agreed | Strong evidence: budget accounting and author-sensitive checking retained |
| 11 Build order | Agreed | Strong evidence: A/B, S9 timing and uncomputed account-result boundary explicit |

## Risks, what could make me wrong, and how to test it

**Reasoning only:** an agreed design may still find no profitable opportunities. The key unresolved risks are scarce independent events, revised prices/actions, filing-time proxies, pre-open repricing, failed limit fills, correlated bets and costs exceeding small gains. More AI roles do not cure these by themselves.

A successful history rebuild can increase usable observations; it cannot by itself increase independent market regimes. Matched controls may improve precision, while clustered events and selected tails may worsen it. A modern, narrowly defined effect could overturn the sceptical prior, but it must survive this account's entry, costs and holding window.

**Reasoning only — next measurement after owner approval:** freeze the study definitions and inputs; publish the joined coverage and release-timing audit; measure S1 and S9 separately with matched controls and dependence-aware intervals; report unavailable gaps, eligibility/fills and scenario costs. Use S10 as a later fallback if event coverage is inadequate. Report “inconclusive”, “incomplete” or “account result not computed” when appropriate. If a thesis survives, finish the V16 prerequisite engines/reports and use its registered forward protocol for confirmation.

**Outcome:** all eleven sections are agreed. Stop design review unless a new material contradiction appears; the next useful work is the owner's decision and then measurement. No edge, account profit or permission to build is claimed by this sign-off.
