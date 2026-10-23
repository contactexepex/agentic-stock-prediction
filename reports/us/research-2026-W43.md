# Research review us 2026-W43 (2026-10-19 to 2026-10-25)

_Research only, not investment advice. Paper trades are records, never orders. Proposals change nothing until the owner applies them._

## Leaders to date (accuracy view, after costs)

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 59 | 30 | 157.17 | 0.27 |
| ai | ai.combined.sonnet.v1 | 3 | 1 | -80.25 | -2.68 |
| baseline | base.model_only.v1 | 1 | 0 | -77.65 | -7.77 |
| baseline | base.momentum.v1 | 341 | 161 | -1212.46 | -0.36 |
| baseline | base.always_up.v1 | 646 | 314 | -2661.63 | -0.41 |
| rule | rule.model_news_calm.v1 | 1 | 1 | 1.42 | 0.14 |
| rule | rule.model_news_global.v1 | 2 | 1 | -2.6 | -0.13 |
| rule | rule.model_news_double.v1 | 7 | 3 | -59.57 | -0.85 |
| rule | rule.model_news_confirmed.v1 | 1 | 0 | -77.65 | -7.77 |
| rule | rule.model_news_half.v1 | 1 | 0 | -77.65 | -7.77 |
| rule | rule.model_news_high.v1 | 1 | 0 | -77.65 | -7.77 |
| rule | rule.model_news.v1 | 3 | 1 | -80.25 | -2.68 |

## This week

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.combined.sonnet.v1 | 3 | 1 | -80.25 | -2.68 |
| ai | ai.pattern_mood.sonnet.v1 | 39 | 15 | -165.33 | -0.42 |
| baseline | base.model_only.v1 | 1 | 0 | -77.65 | -7.77 |
| baseline | base.momentum.v1 | 236 | 109 | -765.82 | -0.32 |
| baseline | base.always_up.v1 | 463 | 225 | -1784.85 | -0.39 |
| rule | rule.model_news_calm.v1 | 1 | 1 | 1.42 | 0.14 |
| rule | rule.model_news_global.v1 | 2 | 1 | -2.6 | -0.13 |
| rule | rule.model_news_double.v1 | 7 | 3 | -59.57 | -0.85 |
| rule | rule.model_news_confirmed.v1 | 1 | 0 | -77.65 | -7.77 |
| rule | rule.model_news_half.v1 | 1 | 0 | -77.65 | -7.77 |
| rule | rule.model_news_high.v1 | 1 | 0 | -77.65 | -7.77 |
| rule | rule.model_news.v1 | 3 | 1 | -80.25 | -2.68 |

## Findings

- ai.pattern_mood.sonnet.v1 leads to date: 59 trades, 30 wins, net +157.17 USD after costs (0.27%), the only strategy with a usable sample and a positive total. This week it lost: 39 trades, 15 wins, -165.33 USD (-0.42%). The lead is small and unproven; these inputs hold no luck test. (ai.pattern_mood.sonnet.v1)
- Both baselines lost after costs: base.always_up.v1 646 trades, 314 wins, -2661.63 USD (-0.41%); base.momentum.v1 341 trades, -1212.46 USD (-0.36%). The week's biggest misses were company-specific drops (META, GM), the biggest wins sector lifts (PGR, CVX); the end-of-day note says news explained none of the move in any item. (base.always_up.v1, base.momentum.v1, eod-us-2026-10-23, tra:acc:base.always_up.v1:2026-10-15-META-5d:biggest_miss, tra:acc:base.always_up.v1:2026-10-15-GM-5d:biggest_miss)
- Rule strategies are too thin to judge: at most 7 trades (rule.model_news_double.v1, -59.57 USD). rule.model_news_confirmed.v1, rule.model_news_half.v1, rule.model_news_high.v1 and base.model_only.v1 each have one trade at -77.65 USD, the net of the BAC pick where news explained most of the move; rule.model_news.v1 and ai.combined.sonnet.v1 match at -80.25 USD. One-parameter comparisons cannot separate yet. (rule.model_news_double.v1, rule.model_news_confirmed.v1, rule.model_news_half.v1, rule.model_news_high.v1, base.model_only.v1, rule.model_news.v1, ai.combined.sonnet.v1, tra:h2h:best_expected_gain:rule.model_news.v1:2026-10-09-BAC-5d)
- Promotional analyst items were followed by negative abnormal returns: -0.665% at 3 days (interval -1.18 to -0.15, 136 events) and -0.91% at 5 days (-1.65 to -0.18). The benchmark fell about as much (-0.74%, -1.12%) and the event windows overlap, so this one week is no evidence for a new news weight. (ni-us-2026-W43-analyst-promotional-low-3, ni-us-2026-W43-analyst-promotional-low-5)
- Verified news is too thin to judge: no confirmed_primary or corroborated row has enough events yet; earnings confirmed_primary had 1 event, and analyst single_source medium had 10 events with intervals spanning zero (3 days: +0.80%, -0.67 to 2.28). The NVDA lesson fits: one corroborated story did not stop a losing call. (ni-us-2026-W43-earnings-confirmed_primary-low-1, ni-us-2026-W43-analyst-single_source-medium-3, lesson-2026-10-08-NVDA-5d)

## Proposals (status: proposed; each is a diff for the owner to approve)

None this week.
