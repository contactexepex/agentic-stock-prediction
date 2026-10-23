# Research review india 2026-W43 (2026-10-19 to 2026-10-25)

_Research only, not investment advice. Paper trades are records, never orders. Proposals change nothing until the owner applies them._

## Leaders to date (accuracy view, after costs)

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 51 | 25 | 11204.34 | 0.22 |
| ai | ai.news_results.sonnet.v1 | 7 | 1 | -9172.9 | -1.31 |
| baseline | base.always_up.v1 | 576 | 243 | 13269.05 | 0.02 |
| baseline | base.momentum.v1 | 342 | 134 | -45824.13 | -0.13 |
| rule | rule.model_news_double.v1 | 12 | 3 | -8312.48 | -0.69 |

## This week

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 38 | 17 | -153.68 | -0.0 |
| ai | ai.news_results.sonnet.v1 | 5 | 0 | -8028.13 | -1.61 |
| baseline | base.momentum.v1 | 214 | 72 | -93135.62 | -0.44 |
| baseline | base.always_up.v1 | 379 | 136 | -137296.95 | -0.36 |
| rule | rule.model_news_double.v1 | 11 | 2 | -10034.67 | -0.91 |

## Findings

- To date ai.pattern_mood.sonnet.v1 leads on return per trade: 51 trades, 25 wins, net +11204.34 INR (0.22%), versus base.always_up.v1 at 0.02% over 576 trades. This week it held near flat (-153.68 INR over 38 trades) while always_up lost -137296.95 INR. A short record with no luck test in these inputs: not proof of skill. (ai.pattern_mood.sonnet.v1, base.always_up.v1)
- ai.pattern_mood.sonnet.v1 gained when sector or news lifted its five-session holds (M&M, ONGC) and lost on one-session picks in a falling market (M&M, HINDALCO). Trading costs turned a near-flat TATASTEEL hold into a loss. Its edge so far looks like riding sector moves, not stock picking. (tra:h2h:best_expected_gain:ai.pattern_mood.sonnet.v1:2026-10-12-M&M-5d, tra:h2h:best_expected_gain:ai.pattern_mood.sonnet.v1:2026-10-12-ONGC-5d, tra:h2h:highest_probability:ai.pattern_mood.sonnet.v1:2026-10-19-M&M-1d, tra:h2h:highest_probability:ai.pattern_mood.sonnet.v1:2026-10-19-HINDALCO-1d, tra:h2h:best_expected_gain:ai.pattern_mood.sonnet.v1:2026-10-12-TATASTEEL-5d)
- News-led strategies trail: ai.news_results.sonnet.v1 has 7 trades, 1 win, -9172.9 INR (-1.31%); rule.model_news_double.v1 has 12 trades, 3 wins, -8312.48 INR (-0.69%). Their settled losses came mostly from market or company moves (ICICIBANK, RELIANCE), not news. No other rule strategy appears in the leaders lists. Far too few trades to judge. (ai.news_results.sonnet.v1, rule.model_news_double.v1, tra:h2h:highest_probability:ai.news_results.sonnet.v1:2026-10-16-ICICIBANK-1d, tra:h2h:best_expected_gain:rule.model_news_double.v1:2026-10-15-RELIANCE-4d)
- An IT sector rally drove the week's biggest moves. The TCS news item behind part of it is a confirmed_primary M&A story rated low materiality, a single event, so no evidence. Three TCS down calls resting on a small dividend all missed, with actual returns 0.181687, 0.126322 and 0.172516, each closing above the wider published band. (ni-india-2026-W43-ma-confirmed_primary-low-1, lesson-2026-10-08-TCS-5d, lesson-2026-10-09-TCS-5d, lesson-2026-10-12-TCS-5d)
- Among rows with enough events, unverified and single-source earnings items moved most: unverified high-materiality -2.1009% abnormal at N+2 (interval -2.9402 to -1.2616, 20 events); single-source medium +2.4844% at N+5 (43 events, sector mean +10.6408%). Every confirmed_primary and corroborated earnings row lacks enough events. One week, overlapping windows, a sector rally: not yet evidence. (ni-india-2026-W43-earnings-unverified-high-2, ni-india-2026-W43-earnings-single_source-medium-5, ni-india-2026-W43-earnings-confirmed_primary-medium-1, ni-india-2026-W43-earnings-corroborated-high-1)
- Some news-impact rows list one news id twice, as in the unverified high earnings row, likely one item tagged to two companies; if such events are not independent, the intervals are too narrow. Nearly every settled trade is also flagged target reached in session one, losers included (M&M), so that flag tells little. (ni-india-2026-W43-earnings-unverified-high-1, tra:h2h:highest_probability:ai.pattern_mood.sonnet.v1:2026-10-19-M&M-1d)

## Proposals (status: proposed; each is a diff for the owner to approve)

None this week.
