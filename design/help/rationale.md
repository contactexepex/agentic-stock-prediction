# Help screen: rationale

Files: `template.html` + `build.py` (`--out DIR`), `help.html` (self-contained, no network), `data-help.json`,
screenshots `shot-help-*.png`, `notes.md`. Same shell and design system as the other screens (`design/system/`).

## What it is for
The owner's test for every screen was "how will someone who is not a financial wizard understand this". Help is
the page that test points to: it explains the cockpit once, in plain words, so the other pages can stay terse.
Every number on it (the call line, the adjustment cap, the four tests' thresholds, the costs, the session hours,
the regime levels, the feed counts) is read from the repo's configuration or stored data by `build.py`, so the
page cannot drift from the rules the pipeline enforces.

## Layout
1. **Guide**: what this is, in four sentences, ending with "every signal is paper until the four tests pass".
2. **Contents** chips to the eight sections.
3. **Your five-minute morning**: the order to read the pages in (Home banner, the news card, a YES company
   page, Record, Portfolio), each step one card with a link; the run timing per market underneath.
4. **The pages**: one card per page with the single question it answers and what is on it.
5. **How a call is made**: the seven steps of each run, after the close and before the open (collect, score the news, model, debate,
   forecaster, ranges, score it), then the table of rules the system never breaks, each with what it means
   for the reader and where in the repo it is checked.
6. **Colours, words and badges**: the verdict (NO red, YES light green okay, dark green strong, with the
   strength rule), price moves, the live / back-test / paper / derived / mock tags, the verification badges in
   their three groups, materiality, the regime words with each market's volatility levels, the 50% and 80%
   ranges.
7. **When can it be trusted with money**: "Not yet", the four tests of the Record page with their thresholds,
   and what "trusted" would and would not mean.
8. **Glossary**: 24 terms in the pages' own words.
9. **Where the numbers come from**: per market, the session hours, price sources, benchmark and volatility
   index, cues, factors, news feeds and counts, filings and flows, what is stored so far, and the 20 companies
   by sector (chips link to the decision pages that exist in this design set).
10. **Questions people ask**: nine answers, collapsed.

Phone: single column, the flow two across, the rules table keeps its three columns.

## Real, derived
- Real: every threshold from `config/model.yaml`, `ranges.yaml`, `review.yaml`, `settings.yaml`, `costs.yaml`
  (through the pipeline's own `round_trip_cost`) and `config/markets/*.yaml`; session hours from the exchange
  calendar; counts and dates from DuckDB.
- Constants restated from code: the YES strength rule (decision page), the confidence range, the ±0.10
  adjustment cap, the one-session results block and the single-source penalty (CLAUDE.md prediction rules,
  enforced by `scripts/validate.py`); each is named in `build.py` with its source.
- Nothing is mock.

## Checked
Playwright, pre-installed Chromium, 1280 and 390 px: no console errors, no horizontal scroll, no external
requests. With this screen the Help entry in every page's navigation becomes a link; all nine pages were rebuilt
and re-checked.
