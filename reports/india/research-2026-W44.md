# Research review india 2026-W44 (2026-10-26 to 2026-11-01)

_Research only, not investment advice. Paper trades are records, never orders. Proposals change nothing until the owner applies them._

## Leaders to date (accuracy view, after costs)

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 60 | 31 | 12870.63 | 0.21 |
| ai | ai.news_results.sonnet.v1 | 8 | 1 | -11410.73 | -1.43 |
| baseline | base.always_up.v1 | 1006 | 437 | -15480.41 | -0.02 |
| baseline | base.momentum.v1 | 515 | 207 | -56393.86 | -0.11 |
| rule | rule.model_news_double.v1 | 15 | 3 | -12192.9 | -0.81 |

## This week

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 9 | 6 | 1666.29 | 0.19 |
| ai | ai.news_results.sonnet.v1 | 1 | 0 | -2237.83 | -2.24 |
| baseline | base.momentum.v1 | 173 | 73 | -10569.73 | -0.06 |
| baseline | base.always_up.v1 | 430 | 194 | -28749.46 | -0.07 |
| rule | rule.model_news_double.v1 | 3 | 0 | -3880.42 | -1.29 |

## Findings

- The pattern-mood AI trader leads to date: 60 trades, 31 wins, net 12870.63 INR, return 0.21%; this week 9 trades, 6 wins, net 1666.29. It reads prices, regime and sectors only. 60 trades is a small sample and these inputs carry no luck test, so this is not yet evidence of skill. (ai.pattern_mood.sonnet.v1)
- Both baselines lose after costs to date: always-buy 1006 trades, 437 wins, -0.02%; follow-yesterday 515 trades, 207 wins, -0.11%. Their week swung with the market: baselines lost 84819.77 in Monday's settlements and gained 88973.14 in Friday's. A strategy must beat these yardsticks before its result means anything. (base.always_up.v1, base.momentum.v1, eod-india-2026-10-26, eod-india-2026-10-30)
- News-led strategies trail: the news-and-results AI trader has 8 trades, 1 win, net -11410.73 (-1.43%); the double-news rule has 15 trades, 3 wins, net -12192.9 (-0.81%). With 8 and 15 trades this cannot separate poor use of news from bad luck. The other rule strategies and both combined AI traders do not appear in the leaders tables. (ai.news_results.sonnet.v1, rule.model_news_double.v1)
- Verified news cannot be judged yet: the confirmed_primary and corroborated earnings and analyst rows are all 'not enough events yet' (at most 4 events). The statuses the signal model weights most therefore have no measured effect this week; these rows are not evidence either way. (ni-india-2026-W44-earnings-confirmed_primary-medium-1, ni-india-2026-W44-earnings-confirmed_primary-high-1, ni-india-2026-W44-earnings-corroborated-high-1, ni-india-2026-W44-analyst-confirmed_primary-medium-1)
- Single-source medium analyst news shows positive abnormal returns at 3 and 4 days (+1.08%, CI 0.57 to 1.60; +1.37%, CI 0.75 to 1.99), but mean sector moves of 2.86% and 4.17% suggest sector rallies may be mixed in. Single-source high earnings news flips sign: -0.46% at 2 days, +0.72% at 3. One week only: likely noise. (ni-india-2026-W44-analyst-single_source-medium-3, ni-india-2026-W44-analyst-single_source-medium-4, ni-india-2026-W44-earnings-single_source-high-2, ni-india-2026-W44-earnings-single_source-high-3)
- In the cited trade reasons, the DRREDDY win is put down to a sector lift with no news part, while the HDFCBANK miss is the largest news-led miss (reason code news_negative). The daily review notes targets were reached in session 1 on most items, yet several trades still ended with large losses. (eod-india-2026-10-28, tra:acc:base.always_up.v1:2026-10-16-HDFCBANK-5d:biggest_miss, tra:acc:base.always_up.v1:2026-10-19-DRREDDY-5d:biggest_win)

## Proposals (status: proposed; each is a diff for the owner to approve)

None this week.
