# News and events screen: rationale

Files: `template.html` + `build.py` (`--out DIR`, both markets, in-page India/US switch), `news.html`
(self-contained, no network), `data-news.json`, screenshots `shot-*.png`, `notes.md`. Same shell and design
system as the other screens (`design/system/`).

## What it is for
The evidence behind every call, in the owner's words: which stories the pipeline saw about the 20 companies,
how far each one is verified, and what is scheduled in the next eight weeks. The forecaster may only lean on a
story that is confirmed by a primary document or corroborated by independent outlets (DESIGN.md 3b), so the
page makes that status the first thing on every story and explains each badge once, in plain language.

## Layout
1. **Guide**: what the page is and the one rule that matters (a call may only lean on a confirmed or
   corroborated story).
2. **Six tiles**: headlines stored (high materiality), stories (companies with news), fit to support a call,
   single source, rumour or promotional (never support a call), claims checked.
3. **Stories by company** (left, the main column): one card per story (a news cluster): company chip, status
   badge, materiality and event type, mood arrow, first to last report time, headline and outlet, counts
   (headlines, copies, outlets, independent origins, unread vetted, filings attached), flags, the checked
   claims with their verbatim quote and attribution, and the story's headlines on demand. Filters: words or
   company, status, materiality, company. 10 stories shown, button for all.
4. **All headlines** table: when, headline (link), source, company, mood, materiality, status; filter by
   words, company, status; sort newest first, oldest first, by company, by materiality. The page embeds the
   newest 800 headlines plus every high-materiality one; the count line says how many of the stored total.
5. **Right column**: what the status badges mean (with this run's counts per status), what's coming in the
   next eight weeks grouped by week (results and ex-dividend dates from the stored events, market-wide events
   from `config/events.yaml`, each results date with its reaction session and the "no new call within one
   day" rule), where the headlines come from (top ten sources, article-page access counts, "full texts are
   never stored").
6. Collapsed data sources.

## Colour and status
Status badges reuse the design system's verification badges: green for confirmed primary and corroborated
(the only statuses that can carry a call), amber for single source, grey for unverified, red for rumour,
promotional and contradicted. Mood arrows use the up/down tokens only for the headline's sentiment; they say
nothing about a call.

## Real, derived
- Real: `news` + `enriched_latest` (headline, source, sentiment, materiality, event type), `news_clusters_latest`
  (stories), the latest `news_verified` pass (status, origins, flags), `news_claims` (quotes), `news_articles`
  (access), `events` and `market_events` (calendar).
- Derived: the tile counts, per-status counts and the "fit to support a call" number (confirmed primary +
  corroborated), the reaction session of a results date (`next_session`), the week grouping.

## Checked
Playwright, pre-installed Chromium, 1280 and 390 px: no console errors, no horizontal scroll, no external
requests. India: 1920 headlines (890 embedded), 51 stories, 24 claims, 33 events; US: 2911 headlines (813
embedded), 270 stories, 32 claims, 27 events.
