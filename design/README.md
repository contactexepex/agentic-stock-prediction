# Cockpit design workspace

Working area for the owner's personal stock cockpit (the multi-page dashboard served from
`reports/` on the private Vercel site). Pages are designed here one at a time, each in its own
cloud session, then one consolidation session turns them into the production generator under
`scripts/marketbrief/presentation/` (judged like any code change, see CLAUDE.md).

## Rules for every page session
- **Real data only.** Every page is a template plus a data builder that reads the repo's stored data
  read-only through DuckDB (`from marketbrief.core.database import connect`) and the existing helpers.
  Never write to `data/`, `reports/` or `summaries/`. Anything not built yet is visibly tagged *Mock* or
  *Coming*; history not yet live comes from the back-test / rule replay and is tagged *Back-test*.
- **Dynamic templates.** A page must regenerate for any market and ticker:
  `python design/<page>/build.py --market india|us [--ticker T] --out <dir>`. No hard-coded values in
  the template; the builder computes everything at build time. The consolidation session will move the
  builders into the daily run, and later behind a database-backed app, so keep data assembly and
  presentation separate (builder -> JSON -> template).
- **Design system.** Use the shared Material 3 light design system in `design/system/` (tokens,
  typography, components, icons). Do not invent page-local colours. Self-contained output: no CDNs,
  no external fonts or requests (vendor anything needed, with its licence).
- **Owner's direction** (from conversation): personal cockpit for the 40 watchlist companies (20 India,
  20 US); plain language, icons over text, aggregated on lists and detailed on the company page; strong
  signals shown only once proven ("No proven strong signals today" + Paper candidates until then);
  every signal Paper until the track record proves it; history matters (yesterday / last weeks /
  next 1 and 5 days, deviations and their causes); research only, never trades.
- **Accessibility.** Light theme, phone (390px) and desktop (1280px), not colour alone, keyboard usable.
- **Deliverables per page:** `design/<page>/` with `build.py`, the template, a generated example
  output, screenshots at 1280 and 390, `rationale.md` and `notes.md` (queries used). Check with
  Playwright and the pre-installed Chromium: no console errors, no horizontal scroll, no external
  requests.

## Pages
| Page | Status |
|---|---|
| `decision/` Stock decision page (HDFC Bank example) | layout approved by the owner; recolour to Material 3 |
| `system/` Material 3 design system | to do (first) |
| Home | to do |
| Watchlist | to do |
| Portfolio (paper) | to do |
| Track record | to do |
| News, Help | to do |

`reference/` holds earlier rejected iterations (v2) for context only.
