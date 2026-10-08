# News mockup: rationale

Page 9 of docs/SPEC.md section 6 ("news by company with verification status and impact category", read model
`rm.news`), designed in the design track on the owner's rules of 2026-10-08, which replace the earlier decision to
fold the news into Home and the Company page. Status: **built on the owner's instructions** (2026-10-08) and rebuilt the same day on W1's data request 8 (56
real stored stories, 28 per market, with scope, category, summary and an engine-side market-moving flag); judged and
landed by the track; the owner reviews it.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example payload of `GET /api/v1/markets/{market}/news`), `page.html`, `notes.md`, screenshots
`shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png`.

## The owner's rules
Nothing older than 3 days (a short trading window needs no older news). The last 24 hours come first. A band of at
most 10 stories that move the whole market (rates: Fed, RBI; inflation and jobs; the watchlist's quarterly results;
crude oil; wars; an index that drops sharply anywhere). Then the rest of the window, newest first, with pagination:
at most 50 stories, 10 a page. Each story is a heading with one or two lines and a link to the original article; the
cockpit never shows the stored text. A right rail with the calendar and the news per company. Linked with the other
pages.

## Who reads it and how
A retail investor before the open: "what happened that can move prices, and what is coming". The page answers in
that order: the movers first (few, ranked, each with its verification status so a rumour never reads like a fact),
then the full window for the reader who wants everything, filtered by the last 24 hours, market-wide, one company
or "can carry a call", then the week ahead and which companies the news is about. Patterns borrowed from trading
platforms and newsrooms: a short "top stories" lead, a chronological feed grouped by day with sticky day headers,
source and time on every item, an "open article" link that leaves the site, and a calendar rail; nothing is copied
from any site, only the conventions.

## Layout (desktop: the movers band full width, the feed beside a rail; phone: one column)
1. **Page head** (the shell's chips).
2. **Market movers · last 3 days**: up to 10 ranked cards in two columns: rank, the kind of story (market-wide
   stories carry a globe and the word "market"), the headline as the link, the summary line when the data has one,
   the source and "published n hours before the cut-off", the status badge, the materiality, how many outlets carry it, the
   companies as links to their pages, and "Open article". Ranking: the engine's market-moving flag first (W1's rule:
   high materiality and market-wide or a results item, shown as an amber "market moving" label), then market-wide
   stories, the watchlist's results and high materiality, newest first within each rank; the same headline stored
   twice shows once. A market-wide story carries "not verified per company" instead of a status, because
   verification is per company. An honest empty state when the window has none.
3. **Last 3 days** (the feed): filter chips (All, Last 24 h, Market-wide, Market moving, Can carry a call) and a
   company select ("Last 24 h" = published in the 24 hours before the cut-off); a note when most stories have no
   summary line;
   stories grouped by the local day they were stored, with a sticky header ("Today · n stories"), each row with the
   outlet's publish time (with its date when it differs from the stored day; the tooltip has both times), the sentiment arrow, the same item body as the band; a pager
   (10 a page, at most 50 in the window) that scrolls the feed into view.
4. **Rail: Coming up · 7 days**: the market's scheduled events and the active companies' results and ex-dividend
   dates from the session being predicted, a date tile each, "major" (widens every range) in amber, "widens its
   ranges" for results, the release time, "date provisional", the company as a link.
5. **Rail: By company · 3 days**: each watchlist company with a story in the window: ticker (link), the tone mix as a
   small bar (positive / neutral / negative counts in the tooltip), open paper trades, the latest headline, and the
   count as a button that filters the feed to that company.
6. **Legend** (Paper, the statuses that can carry a call with a link to the Help page's news section, what "Open
   article" does, the window's local times) and **footer**.

## Data and contract
- `data.json` is composed from five catalogue files only (`notes.md` lists each field). The page computes the
  ranking, the filters, the day groups, the pagination and the per-company counts; the engine's statuses and scores
  are shown as stored.
- No look-ahead: a story counts when its `first_seen_at` is at or before the cut-off, and the window is the 3 days
  before the cut-off; "n hours before the cut-off" is measured against the cut-off, never the viewer's clock. The
  calendar starts at the session being predicted.
- Data request 8 to W1 (recorded in `_data_requests`), answered the same day: 56 real stored stories with `scope`,
  `category`, `feed`, `summary` (`summary_source` article or analyst), `market_moving` and `origin`. What the stored
  data cannot supply is not invented: no region; the stored statuses are unverified, single source, rumour and
  promotional only (confirmed and corroborated exist on four of the six invented items, so "can carry a call" finds
  one India story and no US story, and its empty state says why); no cluster with more than one origin; most US items have no summary (the analyst's are
  templated), so they show the headline alone and a note under the filters says so. The window hides the older
  invented items (1 in India, 2 in the US) and the US invented item first seen after the cut-off.

## Design rules kept
Design system v2 only; light theme; phone and desktop (the band's two columns and the rail collapse; the feed row
puts the time above the story on a phone); never colour alone (every status and flag has words; the sentiment arrow
has an accessible label; the tone bar has its counts in words); keyboard: chips, the select, the pager, the company
count and every link are buttons or links, every tooltip focusable; plain language; Paper in the band and the
legend; research only. Links to the Company page (every ticker), the Help page (statuses) and, in the sidebar, every
other page.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. Rebuild is byte-identical. A script in both
markets: the band holds 10 stories (India: 5 flagged first; US: 5 flagged first), the feed 29 stories on 3 pages
(India 14 in the last 24 h, US 29), the filters give India 14 / 12 / 5 / 1 stories and the US 29 / 12 / 5 / none for
last 24 h / market-wide / market moving / can carry a call, page 2 adds the 5 Oct day group in India, the company
rail counts RELIANCE 8 and HDFCBANK 4 (India) and NVDA 4, AAPL 2, JPM 1 (US), no page error.

Judge round 1 (2026-10-08) found three blockers, fixed before round 2: the notes said two older items are hidden in
each market (India hides one, the US two, and the US invented item first seen after the cut-off is excluded); the
rationale said the page states the data's limits where it shows them, which it did not (the "can carry a call" filter
now explains its empty state and a note says when stories show the headline alone); and the 24-hour rule and the
0.05 sentiment band were typed in the template (now the shell's `NEWS_RECENT_HOURS` and `SENTIMENT_FLAT_BAND`, the
latter also used by the shell's sentiment arrow).

Closing round (2026-10-08, the owner: "fix it and close the design"): the "Last 24 h" chip and the head's count now use
the outlet's publish time, like the rows; the unused `opts.time` branch is gone; the stale bullets below are current.

## Decisions taken for the owner (reported to the orchestrator; confirmed by the owner on 2026-10-08)
- The movers are a ranked band of cards above the feed, not a separate tab, so the first screen answers "what
  moves the market" and the feed is one scroll away.
- The feed is grouped by day with sticky headers and filtered by chips rather than split into "today" and "older"
  cards: one list, the latest stored first, the owner's filters on top; "Last 24 h" counts by the outlet's publish
  time, like the time shown on every row (the owner's decision after the first review).
- The rail holds the calendar (the week ahead) and the news per company; "big news" lives in the band, so the rail
  does not repeat it.
- Confirmed by the owner (2026-10-08, after the first review): the ranking rule stays, the band shows at most 10 (not
  always 10), and every story shows the outlet's publish time rather than the collection time (the order of the
  feed stays "latest stored first", the owner's earlier rule).
- Market-wide stories are the catalogue's `scope` market (the tagger found no primary watchlist company); each
  market's page shows the stories its own feeds carried, so a Fed story appears in India only when India's feeds had
  it.
- The band uses the engine's market-moving flag first and fills up to 10 with the page's own order, so it is never
  empty while the window has market-wide or results stories (confirmed by the owner).
