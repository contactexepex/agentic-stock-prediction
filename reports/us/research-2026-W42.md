# Research review us 2026-W42 (2026-10-12 to 2026-10-18)

_Research only, not investment advice. Paper trades are records, never orders. Proposals change nothing until the owner applies them._

## Leaders to date (accuracy view, after costs)

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 20 | 15 | 322.5 | 1.61 |
| baseline | base.momentum.v1 | 105 | 52 | -446.64 | -0.43 |
| baseline | base.always_up.v1 | 183 | 89 | -876.78 | -0.48 |

## This week

| family | strategy | trades | wins | net P&L | return % |
|---|---|---|---|---|---|
| ai | ai.pattern_mood.sonnet.v1 | 20 | 15 | 322.5 | 1.61 |
| baseline | base.momentum.v1 | 105 | 52 | -446.64 | -0.43 |
| baseline | base.always_up.v1 | 183 | 89 | -876.78 | -0.48 |

## Findings

- The AI pattern-and-mood trader is the only listed strategy ahead after costs: 20 trades, 15 wins, net +322.5 USD (+1.61%). Both baselines lost: momentum -446.64 (-0.43%) over 105 trades, always-up -876.78 (-0.48%) over 183. All trading so far is this week; 20 trades prove little, and no luck test is in the inputs. (ai.pattern_mood.sonnet.v1, base.momentum.v1, base.always_up.v1)
- No rule strategy and none of the other AI traders shows a settled trade in the leaders; the EOD notes say the facts hold no rule-family result. So rule versus AI, and news weight versus no news, are untested. The inputs do not say whether they abstained, missed their threshold or failed a gate; check abstentions first. (eod-us-2026-10-14, eod-us-2026-10-16, rule.model_news.v1, base.model_only.v1, ai.news_results.sonnet.v1, ai.combined.sonnet.v1, ai.combined.opus.v1)
- The AI leader mostly rode sector swings: its LLY and WMT wins are tagged sector_lift, and its DE win was the same trade always-up also won. Its DAL loss came from market and sector declines, not the company. Fewer trades, not shown stock-specific insight, is the likely gap so far (reasoning only). (tra:acc:ai.pattern_mood.sonnet.v1:2026-10-09-LLY-3d:biggest_win, tra:acc:ai.pattern_mood.sonnet.v1:2026-10-09-WMT-3d:biggest_win, tra:acc:ai.pattern_mood.sonnet.v1:2026-10-09-DE-1d:biggest_win, tra:acc:base.always_up.v1:2026-10-09-DE-1d:biggest_win, tra:h2h:best_expected_gain:ai.pattern_mood.sonnet.v1:2026-10-12-DAL-3d)
- Baseline losses repeat the same moves across horizons and both baselines: CAT company-specific misses appear on two horizons, and the same UAL market-driven miss appears in each baseline. Overlapping trades share one price path, so the 183 and 105 trade counts overstate independent evidence. (tra:acc:base.always_up.v1:2026-10-09-CAT-3d:biggest_miss, tra:acc:base.always_up.v1:2026-10-09-CAT-4d:biggest_miss, tra:acc:base.always_up.v1:2026-10-09-UAL-4d:biggest_miss, tra:acc:base.momentum.v1:2026-10-09-UAL-4d:biggest_miss, base.always_up.v1, base.momentum.v1)
- Verified news gave no evidence either way: every corroborated or confirmed_primary group has 1 event, not enough events yet. The NVDA up call that relied on a corroborated chip-financing headline closed at 217.23 from 237.47. The EOD notes found news explained none of the reviewed moves. Whether verified news helps remains untested. (ni-us-2026-W42-other-corroborated-high-1, ni-us-2026-W42-ma-confirmed_primary-medium-1, ni-us-2026-W42-sector-corroborated-medium-1, ni-us-2026-W42-legal-corroborated-high-1, ni-us-2026-W42-macro-corroborated-high-1, lesson-2026-10-07-NVDA-5d, eod-us-2026-10-16)
- Rows with enough events are unverified, promotional or single_source, which the model weights little or not at all, and the largest mirror sector moves: sector promotional high news +7.1963% while its sector fell -6.921%; macro unverified medium -3.091% while its sector rose +2.461%. One week of this is no basis for changing news weights. (ni-us-2026-W42-sector-promotional-high-4, ni-us-2026-W42-macro-unverified-medium-4, ni-us-2026-W42-earnings-single_source-high-1)

## Proposals (status: proposed; each is a diff for the owner to approve)

None this week.
