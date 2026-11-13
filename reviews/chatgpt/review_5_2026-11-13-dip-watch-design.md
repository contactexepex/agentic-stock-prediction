# Review 5 — Dip-Watch design v1 (2026-11-13)

**Reviewer:** ChatGPT (independent review)  
**Repository / branch:** `contactexepex/agentic-stock-prediction`, `claude/adoring-bell-62so0u`, PR #491.  
**Read in requested order:** `AGENTS.md`; `reviews/claude/response_7_2026-11-13-dip-watch-design.md`; `docs/DIP_WATCH_DESIGN.md` v1; `docs/DIP_WATCH_BRIEF_ORIGINAL.md`. Also checked `docs/PLAN_v16.md`, `docs/STOCK_DESK_DESIGN.md`, `CLAUDE.md`, and `reviews/chatgpt/README.md`.  
**Status:** Design review, not an empirical validation. No historical replay, live quotes, provider-credit measurements, or broker fee statement independently executed for this review. Figures identified as proposals below are **not** observed performance.

## Verdict — NO, not sound enough to build as a trading-suggestion system

**Some evidence.** The architecture is a reasonable *research prototype*, but its promotion test can falsely declare success, its entry/exit accounting is internally inconsistent, and its research gate cannot validate whether a news explanation is true. Most importantly, the proposed 4–6 week trial cannot establish a 20-session result for signals generated near its end. Do not approve the current design for a build that emits actionable CANDIDATE/BUY labels. Approve a **bounded data-collection/shadow prototype only after** correcting the event ledger, scoring rules, and safety labels; then make promotion a separate owner decision.

This is not an assertion that dip buying cannot work. It is an assertion that the present test cannot tell whether *this implementation* works.

## Agreements

1. **Research only; no orders or broker access. — Strong evidence (repository rules).** Keep this hard line. The owner alone chooses any real trade.
2. **Deterministic prices/calculations, AI only for event interpretation, and quiet runs. — Reasoning only.** Good separation; it limits cost and hallucinated arithmetic. It does **not** establish factual correctness of the news.
3. **Append-only positions and signal decisions; pre-earnings WAIT; explicit missing-data labels; capped research calls. — Some evidence.** These improve traceability and reduce avoidable errors. Keep them, but tighten their semantics below.
4. **Mode A is counter to conventional 52-week-high momentum evidence; Mode B resembles reversal rather than proven net profit. — Strong evidence for historical effects, not for this strategy.** George & Hwang (2004), Jegadeesh & Titman (1993), Lehmann (1990), and Jegadeesh (1990) are relevant starting points, not validation of today's selected signals.
5. **A forward trial and a price-only baseline are necessary. — Strong evidence (evaluation principle).** They are not sufficient as specified. Do not treat agreement between Claude and ChatGPT as evidence of alpha.

## Disagreements — Claude's five questions

### 1. Mode A versus George & Hwang (2004)

**Verdict: narrow the BUY-eligible Mode A population; retain the broad 15/20/25% scan for observation. — Some evidence.** George & Hwang found the nearness to the 52-week high helped predict momentum returns; a stock 15–25% below its high is not automatically cheap. A 52-week-high *closing* measure is also not identical to their exact implementation. Their cross-sectional momentum result does **not** prove every dip strategy loses, nor does it directly test market-shock recoveries.

**Change:** classify all dips, but allow an A `CANDIDATE` only if (i) verified MARKET/SECTOR shock, (ii) company quality `pass` with complete required inputs, (iii) no known adverse issuer-specific event, and (iv) no earnings blackout. RESULTS stays `WATCH / hypothesis` until separately validated; an LLM calling a miss an “overreaction” is not evidence. Treat the 15/20/25 ladder as observation levels, not presumed optimal buys. **Test:** compare same-day, same-sector, same-size cohorts: broad dip; restricted dip; near-high momentum; sector ETF; and cash, with next-executable entries, 20/60-day forward net returns and drawdowns. Register the cuts before evaluating untouched data. Do not tune cuts on the trial.

### 2. Thirty candidates; median 20-session return versus S&P 500 and biased backtest

**Verdict: REJECT the proposed go/no-go bar. — Strong evidence (arithmetic and sampling logic).** Thirty candidates are not 30 independent experiments: one crash can generate 30 highly correlated names. A 20-session outcome needs approximately four trading weeks **after each signal**. In a 4-week trial, late signals cannot mature by trial end; even at 6 weeks many remain censored. A median ignores position weighting, tail losses, and fees. The backtest's present-day survivor universe and absent historical quality/news filter make it an invalid pass/fail hurdle. A strategy can “beat” an overstated or understated biased baseline for the wrong reasons.

**Change (proposed protocol, not validated thresholds):**
- Freeze signal rules, selection ranking, timestamp, price source, and comparison methods *before* the forward test. Run **6 weeks of signal collection plus 20 trading sessions of follow-up after the final eligible signal**; do not call this a completed 6-week evaluation.
- Report every eligible signal, including unfilled limit orders, WATCH/AVOID, duplicate modes, unresearched candidates, and failed data runs. Group results by **signal day** and show number of independent market days and crash days; bootstrap confidence intervals by date, not ticker.
- Primary metric: paired **net return difference** against a *same-entry-time* S&P 500 buy-and-hold benchmark at 20 sessions, for a fully specified, executable paper policy. Include trading costs, fills, stops and time exits. Secondary: excess versus sector ETF and a **point-in-time** simple price-only policy, evaluated on the *same dates*; plus cash and maximum drawdown.
- **No automatic real-money promotion from 30 observations.** Proposed minimum for a *review* is 30 matured eligible signals on **at least 15 distinct market days**, with positive mean net excess and a date-clustered 95% confidence interval whose lower bound exceeds zero, positive portfolio-level net profit after costs, and no unacceptable drawdown. These numbers are conservative *design proposals*, not a power calculation; if data are too sparse, report `INCONCLUSIVE`, extend the forward test, and estimate power from observed daily paired differences. No post-hoc rule changes inside the registered test.
- Backtest is a diagnostic, **not** a second promotion hurdle until reconstructed with historical constituents, historical fundamentals available then, corporate actions, and realistic fills. Historical LLM news judgement cannot be reconstructed without leakage.

**Test disagreement:** simulate the proposed 30-signal median rule on multiple historical market blocks, keeping crash-day clusters intact. Count false passes against a null (random same-day/sector picks). Compare with the registered forward, clustered rule.

### 3. Mode B ±7%, 7-day review, live hourly S&P trigger

**Verdict: REJECT ±7% as evidence-based; retain only as a pre-registered experimental arm. — Some evidence.** Short-horizon reversal exists in older studies, but no evidence here supports *7%* rather than 3%, 5%, 10%, or an ATR/volatility-scaled exit. A symmetric +7/−7 has **zero gross expectation at 50% target-first** before costs, assuming equal realized win/loss size. With a hypothetical $1,000 position and two €1 fees, the break-even win rate is about **51.4%** at EUR/USD parity and exact ±7% fills; actual FX, gaps and spreads change this. A −7% *alert* is not a guaranteed −7% fill; a gap can lose more. “Review after 7 sessions” is not an executable exit and leaves the outcome undefined.

**Change:** record both (a) first intraday threshold crossing and (b) close-confirmed crossing as separate cohorts; only send a `WATCH` during the session until market/stock price freshness and news are verified. Fix a time exit at the close of session 7 for the experimental paper policy; report both gap-through-stop and conservative stop/target sequencing. Evaluate +7/−7 against ±5%, volatility-scaled barriers and no stop, **on a development sample**, then lock one rule for the forward test. Never describe a Telegram notification as a broker stop.

**Test:** timestamp every hourly S&P and stock observation; count intraday −2% S&P events that recover above −2% by the close; measure Mode B signal count, forward net return, stop-first rate, and missed opportunities for live versus close-confirmed entry. Daily OHLC alone cannot reconstruct the intraday trigger or the order of two barriers hit in one bar.

### 4. Quality limits

**Verdict: REJECT as a universal pass/fail model. — Reasoning only for exact thresholds; some evidence for financial-statement timing risks.** Revenue −5%, debt/equity 2.0 and coverage 1.5×/3× are heuristics, not demonstrated predictors of profitable rebounds. A company with negative equity makes debt/equity misleading; near-zero interest expense makes coverage undefined. Cash-rich growth firms, utilities, REITs and banks need different measures. An operating-margin “speculative” label can still mask insolvency. Yahoo financial fields may be stale, inconsistent, or restated.

**Change:** keep these thresholds as *descriptive flags*, not universal proof of safety. `PASS` requires an explicit **as-of** date, financial-statement period, source, valid denominator, and no missing *critical* inputs. Separate `UNKNOWN` from `PASS`; unknown critical earnings date, splits, financials, or source freshness means **no BUY suggestion**, not “missing never fails.” For financials use sector-appropriate solvency/capital measures; for REITs and utilities use appropriate cash-flow/leverage metrics. Negative equity, nonpositive EBIT, missing interest, and zero denominator get explicit handling. A going-concern flag is a hard avoid pending verified filing review, but absence of a 5-day news hit does not prove absence of a warning.

**Test:** hand-label a stratified sample (e.g. 100 flagged firms across sectors) using contemporaneous SEC filings; measure completeness, false PASS, and predictive contribution of each flag out of sample. No claim of quality skill until tested.

### 5. What the deterministic gate cannot catch

**Verdict: its claimed numeric traceability is necessary but deeply insufficient. — Strong evidence (logical counterexamples).** A price copied faithfully from a stale quote is still wrong; a cited article can refer to the wrong company or an old event; a real earnings date can be reported after the cut-off; an LLM can infer “market-driven” despite a same-day fraud disclosure. A URL/document ID proves a source was referenced, not that the interpretation is supported.

**Change:** add hard gates for ticker/exchange/issuer identity; market-session and quote timestamps; last-trade versus delayed quote; adjusted-versus-unadjusted price basis; split/merger/halt/delist; results calendar confidence; as-of publication timestamps; source-to-claim entailment; and contradiction between filings, exchange notices and news. Critical unresolved conflicts force `WATCH / DATA UNVERIFIED`, not CANDIDATE. Use a separate reviewer or structured claim-checker on every CANDIDATE, with citations to exact passages and a small adversarial fixture set (wrong ticker, late news, stale quote, split, bankruptcy, halted ADR, false market-cause). **Test:** report false-candidate and abstention rates on at least 100 labeled historical/forward cases, including deliberately injected failures. No unverified “AI high confidence” as a substitute.

## Open point 18.1 — paper versus real Telegram commands

**YES: separate paper and real ledgers from day one. — Strong evidence (accounting integrity).** During the no-money trial, default all `/buy` and `/sell` to **paper**, or better require explicit `/pbuy` and `/psell`; reject ambiguous bare commands until the owner chooses a policy. Reserve `/rbuy` and `/rsell` for later manual recording only, behind a deliberate config unlock after approval; the bot still never trades. Every row needs `account_type=paper|real`, `position_id`, `mode`, `execution_at`, `recorded_at`, `currency`, `fees`, `source_message_id`, and correction linkage. Do not let a paper sell close a real position or an A position close a B position by ticker alone. **Test:** interleaved paper/real A/B buys, partial sells, undo, duplicate Telegram updates and out-of-order messages; assert independent balances and exactly-once ingestion.

## Additional defects and financial risks not resolved by the five questions

1. **Fill-price contamination — BLOCKER. Strong evidence (arithmetic).** Section 13 scores from a *suggested limit* **or the last price if the limit never filled**. That turns a non-trade into a profitable hypothetical entry. A buy limit below market may not fill for days; it can fill on a bad-news plunge. **Fix:** two separate series: (i) *signal return* from the contemporaneous next-executable price, (ii) *policy P&L* only on orders that would have filled under a documented fill model, with unfilled orders kept as cash. No switching entry basis after observing the outcome. Test against minute bars or conservative daily low/high fill bounds.
2. **Scheduling and market hours — BLOCKER. Strong evidence (calendar arithmetic).** The listed seven hourly runs 09:35–15:35 ET omit the 15:35–16:00 period and do not cover an after-close release; half-days need exchange-specific hours. XNYS calendar does not fully describe every Nasdaq-listed security's trading status. **Fix:** actual exchange session open/close, early closes, and security-level halt checks; log scan coverage and missed minutes. Test DST transitions, Thanksgiving Friday, and half-day sessions.
3. **Mode A state can silently suppress new danger — BLOCKER. Reasoning only.** “No automatic re-checks” of previously flagged names means a previously acceptable dip can deteriorate without an updated decision; holdings get daily news checks but watched non-holdings do not. **Fix:** revalidate active WATCH/CANDIDATE names on a material new filing, earnings release, downgrade or significant price move, with a bounded daily cost budget; expiry (e.g. 5 trading sessions) on every BUY-eligible label. Test adverse-news-after-alert fixtures.
4. **Top-10 ranking contradicts its own pipeline — BLOCKER. Strong evidence (document logic).** Section 2 ranks to ten *before* quality, yet section 6.3 ranks quality `pass` ahead of `speculative`; section 4.2 requires pass for Mode B before research. **Fix:** perform cheap quality checks on **all** triggered tickers before ranking; make eligibility, priority and research cap deterministic. Otherwise a bad top-ten displaces a good eleventh. Test crash day with 100 flags and failures at ranks 1–10.
5. **Risk exposure is hidden by “no caps” — BLOCKER for actionable suggestions. Some evidence.** Owner can choose size, but simultaneous signals are correlated and three one-third ladder buys can concentrate losses. Prior approved `PLAN_v16.md` has account-level risk/cost controls; Dip-Watch calls itself separate but does not resolve whether those controls govern real-money promotion. **Fix:** respect the owner's decision not to prescribe sizes, **but** show existing holdings, same-sector/market overlap, worst-case drawdown, and an explicit `SIZE NOT ASSESSED` warning; get an explicit owner decision on interaction with v16 before any real-money recommendation. Test market-crash clustered exposures.
6. **Market data survivorship, corporate actions, and IPO treatment — BLOCKER. Some evidence.** A new IPO's since-listing high is not a 52-week high; a 252-session label does not make the strategy comparable. Adjusted closing highs and raw live quotes may be on different bases; missing fundamentals never failing a name is dangerous. **Fix:** separate IPO cohort and exclude from initial BUY eligibility; reconcile split/dividend adjustments and timestamp price bases. Rebuild historical universe point-in-time. Test split, dividend, ticker reuse, ADR ratio changes and delisted firms.
7. **“No FX fee” and €1/trade are assumptions, not verified actual costs. — Some evidence.** Revolut plan allowances, execution spread, currency treatment, regulatory charges, and local tax treatment depend on current terms and circumstances. **Fix:** preserve exact broker confirmations and observed USD debit/credit for real trades; paper model includes spread, fees, slippage, dividends, FX and a separate annual tax scenario. Never infer realized P&L from a synthetic EURUSD closing rate alone. Test reconciliation to broker statements on a small historical sample.
8. **Stage/position logic — BLOCKER. Strong evidence (arithmetic).** Recomputing average entry after a partial sale must not change remaining shares' cost basis under an average-cost method; “sell one third” must define whether fractions refer to original position, current shares or target shares. Resetting +15/+20/+30 alerts on every buy risks duplicate partial exits. **Fix:** event-sourced lots, deterministic remaining quantity and fees, one-time exit tranche IDs; document FIFO versus average-cost display and realized P&L. Test buys after partial sales and after stage resets.
9. **Missing raw inputs prevents reproducing AI decisions. — Some evidence.** A document ID and a handful of selected facts cannot reproduce what Claude saw, whether an article changed, or whether a conflicting source was omitted. **Fix:** retain compact immutable *evidence excerpts*, source ID, retrieval/publication timestamps, content hashes, prompt/model version and decisions for flagged names only, with appropriate retention/security; avoid storing unnecessary full copyrighted articles. Test replay of 20 decisions from the stored evidence bundle.
10. **Delivery ordering can lose or duplicate alerts. — Reasoning only.** Telegram send then Git push is not atomic; retry can double-send and a failed push can lose state. Telegram updates may expire after 24h if runs fail. **Fix:** durable idempotent outbox with message/update IDs, retry state and acknowledgments; commit ledger before marking delivery complete, and a cheap frequent command poller independent of the expensive Claude routine. Test crashes before/after send and push, plus 25h downtime.
11. **Selection bias from only researching top 10. — Some evidence.** The other 90 crash-day flags are not randomly missing. **Fix:** score *all* flagged stocks mechanically, preserve the denominator, and report that Claude-selected top ten cannot represent all dips. Compare a fixed random sample of excluded names in shadow research; never extrapolate top-ten results to the full universe.
12. **No evidence that the claimed SPCX security facts are correct. — Reasoning only pending exchange/issuer verification.** A manually seeded ticker can refer to the wrong security or an unsupported Yahoo quote. **Fix:** independently verify official listing, issuer, symbol, exchange, and broker availability before including it; otherwise mark `UNVERIFIED` and exclude from BUY eligibility. Apply the same rule to all manually seeded symbols.

## Proposed experiment / go-no-go specification (NOT validated performance)

| Item | Proposal | Confidence |
|---|---|---|
| Setup | US listed $1B+, $20M ADV, exclude unverified symbols/recent IPOs from initial BUY-eligible cohort | reasoning only |
| Mode A | Scan ≥15% below adjusted 52-week closing high; BUY-eligible only verified market/sector shock + complete quality PASS; observe 15/20/25 ladder | some evidence |
| Mode B | Scan S&P ≤−2% and stock ≤−5%; record live and close-confirmed arms; ±7% and session-7 exit **experimental** | some evidence |
| Entry | First executable post-signal quote; limits count only when filled; unfilled = cash | strong evidence |
| Exit | Fully specified target/stop, gap and time exit; no automatic broker orders | strong evidence |
| Size | No owner sizing advice; report hypothetical fixed-notional and portfolio concentration separately | reasoning only |
| Expected edge | **Unknown**; no numeric positive expectancy justified | strong evidence (absence of validating data) |
| Main risk | Falling fundamentals, correlated crash losses, stale/misclassified news, overnight gap | some evidence |
| Proof | Registered forward paired net results, date-clustered CI, market/sector/cash controls, mature 20-session outcomes | some evidence |
| Pass/stop | No automatic promotion; provisional review threshold: ≥30 matured signals on ≥15 days, positive net excess, 95% CI lower bound >0, portfolio net positive; otherwise INCONCLUSIVE/FAIL | reasoning only |

## Section-by-section disposition

| Design section | Disposition / exact change |
|---|---|
| 1 Purpose | **Agreed**, retain no-order/no-broker boundary; add “not an established edge.” |
| 2 Workflow | **Change:** quality before top-ten ranking; durable event/outbox handling. |
| 3 Universe | **Change:** verify issuer IDs, IPOs, price adjustments and data freshness; point-in-time snapshots. |
| 4 Signals | **Change:** A eligibility narrow; B live/close arms and defined time exit; revalidate stale signals. |
| 5 Quality | **Change:** UNKNOWN blocks BUY; sector-aware, as-of validated checks. |
| 6 Research | **Change:** claim verification and contradictory-source handling; avoid AI overreaction as evidence. |
| 7 Buy suggestion | **Change:** define executable entry and limit expiry/fill; no synthetic fill credit. |
| 8 Positions | **Change:** paper/real separation, lots/tranches, explicit fees, idempotent commands. |
| 9 Delivery | **Agreed** Telegram/HTML concept; **change** idempotent durable outbox. |
| 10 Storage/gate | **Change:** preserve minimal evidence bundles and add semantic/data-age checks. |
| 11 Schedule/cost | **Change:** session-aware half-days, separate cheap polling, measure cost ceiling. |
| 12 Backtest | **Change:** point-in-time historical constituents and fills; diagnostic until repaired. |
| 13 Trial | **REJECT:** replace median/backtest promotion rule with registered mature, paired, clustered net evaluation. |
| 14 Config | **Change:** all new validity, expiry, policy and exit parameters in YAML. |
| 15–16 Build/acceptance | **Change:** implement adversarial and financial reconciliation tests before actionable outputs. |
| 17 Evidence | **Agreed** on momentum/reversal caveats; **change** claims to distinguish published effects from net strategy edge. |
| 18 Open points | **Resolve 1:** separate paper/real; **measure 2–3** before committing to recurring spend or latency. |
| Appendix A | **Agreed as a faithful decision register**, not independent proof the offered options were exhaustive. Reopen only the explicitly identified safety/evaluation conflicts with the owner. |

## Decisions requested from owner / Claude

1. **Approve only a shadow data-collection implementation**, not actionable BUY labels or real-money promotion, until the blockers are corrected. **Some evidence.**
2. **Choose explicit `/pbuy` and `/psell` during trial**; keep real ledger disabled until separately approved. **Strong evidence.**
3. **Authorize a longer evaluation horizon** (6-week intake plus 20-session maturation, extended if underpowered), not an automatic pass after 30 signals. **Strong evidence for timing; reasoning only for proposed minimum.**
4. **Resolve whether v16 account-level risk/cost policy governs any later real-money use of Dip-Watch**, despite the owner's no-sizing preference. **Some evidence.**
5. **Request data before selecting the winning A/B parameters**: historical point-in-time cohorts, realistic fill/cost model, and forward live-versus-close Mode B comparison. **Some evidence.**

**Bottom line:** build the measurement system first; earn the BUY label with forward evidence. Do not confuse an impressive Telegram report, a plausible Claude explanation, or a passing arithmetic gate with a profitable, executable strategy.
