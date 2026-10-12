# Plain-language review: implementation notes (UX2)

Implements `docs/ux/plain_language_review.md` (approved by the owner, merged in PR #445): the wording fixes W1–W7,
the layout changes L1–L6 and the data fields D1–D4. Research only: nothing tells the reader to buy or sell, and every
signal stays Paper.

## Where things live

| Item | Code |
|---|---|
| Shared words (Paper, "not proven yet", market mood, importance, event types, refusal codes, "why no buy or sell") | `web/lib/ui/constants.ts` |
| k-day hold labels (`holdLabel`, `holdTab`; N+k stays in tooltips) | `web/lib/ui/format.ts`, `web/components/ui/controls.tsx` |
| "Expected …" cost labels and `ExpectedMoney` (expected values never styled like results) | `web/components/blocks/costs.tsx`, `web/components/ui/primitives.tsx` |
| Empty states that say when they fill (L2) | `web/lib/ui/empty.ts` |
| Signals band naming the main rule strategy (W7), freshness and mood chips, "Technical details" footer (L5) | `web/components/blocks/page-head.tsx` |
| Home: "Can I rely on this yet?", "Today in 3 lines", "Paper trades so far" (L1) | `web/app/(cockpit)/[market]/_home/home-page.tsx`, logic in `web/lib/market-pages/home.ts` |
| Company page opening sentence and "What our paper trades did" (L3) | `web/app/(cockpit)/[market]/stocks/[ticker]/_parts/summary.tsx` |
| Help: "Why the app does not tell you when to buy or sell", "When will each page fill?", glossary (L4) | `web/app/(cockpit)/[market]/help/_parts/help-page.tsx` |
| Assistant starter "Can I rely on these signals yet?" and the decline's Help link (L6) | `web/app/(cockpit)/[market]/assistant/_parts/conversation.tsx` |
| D1–D4 | `scripts/marketbrief/warehouse/rm_common.py` (`go_live_checks`, `go_live_nearest`, `next_intraday`), `rm_home.py` (`skill`), `api/schemas/home.yaml` |

## Where the build differs from the proposal's letter, and why

- **D1–D4 are new top-level keys of the Home payload** (`go_live_checks`, `go_live_nearest`, `skill`,
  `intraday_next_at`), declared in Home's contract case `extra_keys`, instead of new keys nested in `go_live` and
  `status.runs`. Those two blocks are shared by every page, and the contract check compares each page with its approved
  mockup, where a nested key would be "not in the mockup" on every page. The change is additive: no field was removed.
- **D4 is one time, `intraday_next_at`**, not `status.runs.intraday[].next_at`: before the first check of a session
  the `intraday` list is empty, so there is no element to carry the time the empty state needs.
- **`go_live_checks.earliest_date`** (the reference strategy's `live_from` plus the bar's 2 months) was added so the
  checklist can say "earliest: 12 Dec 2026"; the Home payload carries no `live_from`.
- **The post-close run is called "the after-close run"** on the pages: "evening run" already names B17's preview run
  (`routine/EVENING_PROMPT.md`), which never settles anything.
- **The weekly review is "Friday evening, New York time"**, not Saturday: that is its schedule since the owner's
  decisions of 2026-10-10 and 2026-10-12 (`routine/WEEKLY_PROMPT.md`).
- **No time is named for the next morning run** (forecast history's empty state, the Companies page's "takes effect
  at the next morning run"): no payload carries that time. The first range's check date on Track record is not named
  either: the track-record payload carries no exit date of an unscored range.
- **Brier and AUC are shown as words** ("more honest than a coin flip"; "yes / slightly / no" beside the AUC's interval
  bar), with the number in small print, rather than as new meters.
