# News mockup: rationale

Page 9 of docs/SPEC.md section 6 ("news by company with verification status and impact category", read model
`rm.news`), designed in the design track on the owner's rules of 2026-10-08, which replace the earlier decision to
fold the news into Home and the Company page. Status: **built on the owner's instructions**; the example data holds
one story per market in the 3-day window, so the page is also waiting for W1's data request 8 (market-wide items,
summaries, volume) before it can be judged and landed as a filled page.

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
   the source and "n hours before the cut-off", the status badge, the materiality, how many outlets carry it, the
   companies as links to their pages, and "Open article". Ranking (until W1's engine-side flag): market-wide first,
   the watchlist's results next, then materiality, then newest; only market-wide, results or high-materiality
   stories qualify. An honest empty state when the window has none.
3. **Last 3 days** (the feed): filter chips (All, Last 24 h, Market-wide, Can carry a call) and a company select;
   stories grouped by the local day with a sticky header ("Today · n stories"), each row with the local time (its
   tooltip has the first-stored and published times), the sentiment arrow, the same item body as the band; a pager
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
- Data request 8 to W1 (recorded in `_data_requests`): market-wide items with a scope and region, a one-or-two-line
  summary per item, about 30 items per market in the window with at least 12 in the last 24 hours and every status,
  and if cheap an engine-side market-moving flag. The page is written for those fields (a summary line renders when
  present; the scope is derived from the tickers until a `scope` field exists) and will be rebuilt and judged on them.

## Design rules kept
Design system v2 only; light theme; phone and desktop (the band's two columns and the rail collapse; the feed row
puts the time above the story on a phone); never colour alone (every status and flag has words; the sentiment arrow
has an accessible label; the tone bar has its counts in words); keyboard: chips, the select, the pager, the company
count and every link are buttons or links, every tooltip focusable; plain language; Paper in the band and the
legend; research only. Links to the Company page (every ticker), the Help page (statuses) and, in the sidebar, every
other page.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. Rebuild is byte-identical. The filters, the pager
and the volume of the band and the feed can only be exercised once W1's items arrive; that check and the judge's
review follow then.

## Decisions taken for the owner (to confirm)
- The movers are a ranked band of cards above the feed, not a separate tab, so the first screen answers "what
  moves the market" and the feed is one scroll away.
- The feed is grouped by day with sticky headers and filtered by chips rather than split into "today" and "older"
  cards: one list, newest first, the owner's filters on top.
- The rail holds the calendar (the week ahead) and the news per company; "big news" lives in the band, so the rail
  does not repeat it.
- Market-wide stories are the ones without a company; they appear in every market's page where W1 stores them.
