# Research review us 2026-W41 (2026-10-05 to 2026-10-11)

_Research only, not investment advice. Paper trades are records, never orders. Proposals change nothing until the owner applies them._

## Leaders to date (accuracy view, after costs)

No settled accuracy-view trades.

## This week

No settled accuracy-view trades.

## Findings

- No strategy is ahead yet. Both leader tables are empty, the EOD analyses report 0 settled paper trades on 2026-10-08 and 2026-10-09, and no strategy, the reference and the baselines included, has a live_from date. There is nothing to rank and no config change is supported this week. (eod-us-2026-10-08, eod-us-2026-10-09, rule.model_news.v1, base.always_up.v1, base.model_only.v1, ai.combined.opus.v1)
- Verified news was too rare to judge. Only 1 confirmed_primary event (M&A, medium) and 1 corroborated event (other, high) occurred, both marked not enough events yet. They are not evidence. The statuses the rule strategies count cannot be tested from this week. (ni-us-2026-W41-ma-confirmed_primary-medium-1, ni-us-2026-W41-other-corroborated-high-1, rule.model_news_confirmed.v1)
- Unverified medium-materiality news came before stock-specific underperformance at the 1-day horizon. Sector items averaged -1.50% abnormal (interval -2.32 to -0.67, 24 events), earnings items -0.77% (39 events) and M&A items -0.78% (42 events). This is one week of overlapping events, a description and not an estimate of edge. (ni-us-2026-W41-sector-unverified-medium-1, ni-us-2026-W41-earnings-unverified-medium-1, ni-us-2026-W41-ma-unverified-medium-1)
- Promotional items also came with weaker 1-day abnormal returns. The 'other' category with low materiality averaged -0.54% (interval -0.78 to -0.30, 132 events) and low-materiality analyst items averaged -0.75% (14 events). Medium-materiality promotional analyst items were flat at 0.07% (20 events). The pattern is mixed, and one week cannot separate it from sector moves. (ni-us-2026-W41-other-promotional-low-1, ni-us-2026-W41-analyst-promotional-low-1, ni-us-2026-W41-analyst-promotional-medium-1)
- The effects do not hold across horizons. The largest bucket (unverified, other, low materiality, 395 events) averaged -0.36% at 1 day but +0.59% at 3 days, and the 3-day interval (-0.04 to 1.22) includes zero. Most 3-day rows are marked not enough events yet. (ni-us-2026-W41-other-unverified-low-1, ni-us-2026-W41-other-unverified-low-3, ni-us-2026-W41-earnings-unverified-medium-3)

## Proposals (status: proposed; each is a diff for the owner to approve)

None this week.
