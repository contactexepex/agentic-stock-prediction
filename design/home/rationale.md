# Home (Today) screen: rationale

Files: `template.html` + `build.py` (`--out DIR`, both markets in one page), `home.html` (self-contained, no
network), `data-home.json`, screenshots `shot-*.png`, `notes.md`. Same shell and design system as the other
screens (`design/system/`).

## What it is for
The first (often the only) screen of the morning: both markets at a glance. It answers, in order, "is there
anything to do today", "what is each market doing", "what moved yesterday and why", "what is coming this week",
"what happened in the news and does any of it count", "did the pipeline run cleanly", and "is the system
proven yet". The owner dropped the separate News screen (7 Oct): the key news belongs here, the company page
has each company's full feed, and nobody reads a 2,000-headline archive.

## Layout
1. **Shell**: rail (Home current; Watchlist links to the India list), top bar with a market pair that opens
   each watchlist, a ticker tape of both watchlists (40 companies, each linking to its decision page).
2. **Header**: today's date, each exchange's session status with its data as-of date, LIVE DATA / PAPER tags.
3. **Signals banner** across both markets: "No proven strong signals today" with the Paper candidates (none on
   7 Oct) and the abstention counts, or the YES calls in green once live calls exist.
4. **Two market panels** (India, US), each with: regime and today's major event, benchmark, vol index, calls
   today, Paper candidates, FII/DII (India) or model skill (US); **what moved** on the last session (three
   largest rises and falls, each with a cause icon: market-wide, company news, or unexplained = mock); **next 7
   days** (market calendar plus the watchlist's results dates, today highlighted, major events marked); **what
   the latest run stored** (run time against the open of the session it predicts, bars, model scores, ranges
   published 1-day and 5-day, forecaster records, headlines, verified clusters, lessons; green when complete,
   red when not: India's 1-day ranges were withheld on 7 Oct because the run finished after the open); a
   button to the market's watchlist. The 7-day list has a "Next 8 weeks" button for the weeks behind it
   (results and ex-dividend dates, expiries, central-bank decisions).
5. **News card**, one panel per market, the last 24 hours of the stored archive (to the newest headline):
   - *What moved the whole market*: market-wide macro stories (no company tag, medium or high materiality)
     grouped by the news-analyst's one-line summary, which is identical across the copies of one story, so
     "RBI raised the repo rate 25 bps to 5.5%" shows once with "29 outlets (41 items)". Ranked by
     materiality, then by how many outlets reported it. The summary is the line shown when the analyst wrote
     one; the US analyst prompt writes "Macro: <title>", so US lines are the headlines themselves.
   - *Company news that can carry a call*: the stories whose newest verification row is confirmed (a filing
     or company release) or corroborated (independent outlets), the only statuses a call may lean on. When
     none, a dashed box says "Nothing that changes a call" with the count of stories it looked at.
   - *Set aside*: one line with the counts per status (single source, unverified, rumour, promotional), the
     high-materiality ones listed behind a click with the reason each cannot carry a call, and a pointer to
     the company pages for the rest.
6. **Track record** (live calls scored, 1-day 80% range coverage per market from the rule replay, model skill
   from the weekly review) next to **how to read this screen**.
6. Collapsed data sources.

Phone: single column, movers in one column, status tiles two per row.

## Real, back-test, derived, mock
- Live: everything in the tiles, movers, events and status comes from stored rows (the watchlist builder's rows
  plus this page's queries).
- Back-test: the two coverage tiles (rule replay over each market's 35-session window), tagged.
- Derived: the grouping of market-wide headlines by the analyst's summary and the split of company stories by
  verification status; the cause of a mover (same rule as the decision page: benchmark or sector index >= 0.75% the same
  way -> market-wide; high-materiality headlines on that local day -> company news; else unexplained), Paper
  candidates, blocked counts, before/after the open.
- Mock: unexplained causes (explainer agent not built). Coming: symbol search, Help.

## Checked
Playwright, pre-installed Chromium, 1280 and 390 px: no console errors, no horizontal scroll, no external requests.
News card on 7 Oct: India 4 market-wide groups, 1 story fit to carry a call (L&T, confirmed by an exchange
filing), 38 set aside; US 6 of 136 groups shown, 1 fit (Tesla, confirmed), 210 set aside.
