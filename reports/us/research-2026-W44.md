# Research review us 2026-W44 (2026-10-26 to 2026-11-01)

_Research only, not investment advice. Paper trades are records, never orders. Proposals change nothing until the owner applies them._

## Leaders to date (accuracy view, after costs)

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 69 | 36 | 285.24 | 0.41 |
| ai | ai.combined.sonnet.v1 | 6 | 3 | 9.36 | 0.16 |
| ai | ai.combined.opus.v1 | 1 | 0 | -44.68 | -4.47 |
| baseline | base.momentum.v1 | 583 | 296 | 271.27 | 0.05 |
| baseline | base.always_up.v1 | 1114 | 582 | -10.37 | -0.0 |
| baseline | base.model_only.v1 | 4 | 1 | -214.98 | -5.37 |
| rule | rule.model_news_double.v1 | 30 | 21 | 803.29 | 2.68 |
| rule | rule.model_news_global.v1 | 12 | 11 | 647.57 | 5.4 |
| rule | rule.model_news_calm.v1 | 9 | 7 | 377.03 | 4.19 |
| rule | rule.model_news_confirmed.v1 | 11 | 8 | 369.43 | 3.36 |
| rule | rule.model_news_high.v1 | 10 | 7 | 234.61 | 2.35 |
| rule | rule.model_news.v1 | 14 | 9 | 216.12 | 1.54 |
| rule | rule.model_news_half.v1 | 6 | 3 | -69.7 | -1.16 |

## This week

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 10 | 6 | 128.07 | 1.28 |
| ai | ai.combined.sonnet.v1 | 3 | 2 | 89.61 | 2.99 |
| ai | ai.combined.opus.v1 | 1 | 0 | -44.68 | -4.47 |
| baseline | base.always_up.v1 | 468 | 268 | 2651.26 | 0.57 |
| baseline | base.momentum.v1 | 242 | 135 | 1483.73 | 0.61 |
| baseline | base.model_only.v1 | 3 | 1 | -137.33 | -4.58 |
| rule | rule.model_news_double.v1 | 23 | 18 | 862.86 | 3.75 |
| rule | rule.model_news_global.v1 | 10 | 10 | 650.17 | 6.5 |
| rule | rule.model_news_confirmed.v1 | 10 | 8 | 447.08 | 4.47 |
| rule | rule.model_news_calm.v1 | 8 | 6 | 375.61 | 4.7 |
| rule | rule.model_news_high.v1 | 9 | 7 | 312.26 | 3.47 |
| rule | rule.model_news.v1 | 11 | 8 | 296.37 | 2.69 |
| rule | rule.model_news_half.v1 | 5 | 3 | 7.95 | 0.16 |

## Findings

- Rule strategies lead to date: rule.model_news_double.v1 30 trades, 21 wins, net 803.29 USD (2.68%); rule.model_news_global.v1 12 trades, 11 wins, 647.57 (5.4%). Nearly all of it came this week (double: 23 trades, net 862.86), when base.always_up.v1 also earned 2651.26. A rising week for long-only rules, not proven skill. (rule.model_news_double.v1, rule.model_news_global.v1, base.always_up.v1)
- One-parameter comparisons with the reference rule.model_news.v1 (14 trades, 1.54%): calm 4.19% (9 trades), confirmed 3.36% (11), high 2.35% (10), half -1.16% (6). base.model_only.v1, news off, lost -214.98 on 4 trades. Samples of 4-14 largely shared trades prove nothing yet; rule.model_news_strict.v1 is absent from the tables. (rule.model_news.v1, rule.model_news_calm.v1, rule.model_news_confirmed.v1, rule.model_news_high.v1, rule.model_news_half.v1, base.model_only.v1, rule.model_news_strict.v1)
- ai.pattern_mood.sonnet.v1, the only AI trader with a real sample, has 69 trades, 36 wins, net 285.24 (0.41%), near base.momentum.v1 (583 trades, 0.05%). ai.combined.sonnet.v1 has 6 trades, ai.combined.opus.v1 1 (CAT, -44.68); ai.news_results.sonnet.v1 is absent from the tables. Too few to rank AI traders. (ai.pattern_mood.sonnet.v1, base.momentum.v1, ai.combined.sonnet.v1, ai.combined.opus.v1, tra:acc:ai.combined.opus.v1:2026-10-20-CAT-5d:biggest_miss, ai.news_results.sonnet.v1)
- The week's biggest wins and misses came from company-specific moves with no counted news (GM up, CAT down); GOOGL's falls were mostly news and sector. Their exits finished outside the published range, so the ranges were too narrow for these single-name moves. (tra:acc:base.always_up.v1:2026-10-21-GM-5d:biggest_win, tra:acc:base.always_up.v1:2026-10-21-CAT-5d:biggest_miss, tra:acc:base.always_up.v1:2026-10-23-GOOGL-4d:biggest_miss, eod-us-2026-10-29, eod-us-2026-10-30)
- Some cells' intervals exclude zero: promotional medium analyst items -0.6654% at 2 days (126 events) and -1.3803% at 5 (108); unverified high earnings items +0.8261% at 4 days and +1.6383% at 5 (110). Uncorrected intervals over hundreds of cells, events overlapping across horizons, one week: no edge shown. Verified earnings items: 1 event each, not enough. (ni-us-2026-W44-analyst-promotional-medium-2, ni-us-2026-W44-analyst-promotional-medium-5, ni-us-2026-W44-earnings-unverified-high-4, ni-us-2026-W44-earnings-unverified-high-5, ni-us-2026-W44-earnings-confirmed_primary-low-1, ni-us-2026-W44-earnings-corroborated-high-1)

## Proposals (status: proposed; each is a diff for the owner to approve)

None this week.
