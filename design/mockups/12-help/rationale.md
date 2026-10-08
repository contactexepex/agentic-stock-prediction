# Help mockup: rationale

Page 12 of docs/SPEC.md section 6 (decision 35: "how to read the cockpit in plain words: signals, the Paper label,
strategies, scores, the go-live bar; linked from every page"), designed in the design track. Status: **built on the
owner's delegated authority** (2026-10-08, the owner away: "go with your recommendation, notify the orchestrator";
the owner asked that a retail investor be able to understand every page, with visualisation and tooltips over long
text); judged and landed by the track; the owner reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the shell's market status, the go-live state, the default amount and the strategy registry; the page is
otherwise static), `page.html`, `notes.md`, screenshots `shot-1280-full.png`, `shot-390-full.png`,
`shot-390-viewport.png`.

## Who reads it and how
A retail investor opening the cockpit for the first time, or anyone who met a word they do not know on another
page: what Paper means, what the go-live bar is, what a horizon and a chance are, what the strategies are, what the
scores and the luck test mean, what a head-to-head pick and the two cost views are, what a news status allows, what
an intraday flag is, what each page is for, and where the numbers come from. Each section is short, uses the same
visual parts the pages use (the Paper tag, the horizon chip, the odds meter, the range bar, the status badges, the
check icons) with sample values labelled as such, and the glossary is folded away until wanted. The page is linked
from every page's sidebar and bottom bar.

## Layout (one column; an "on this page" chip row at the top)
1. **Page head** (the shell's chips, so the page also shows the as-of and freshness it explains) and the **on-this-
   page** navigation chips (anchors).
2. **Paper, and the go-live bar**: what a paper trade is, what the tag means, the five checks of the bar with the
   reference strategy's current state in the selected market (from the catalogue's go-live block), and what
   "proven" allows.
3. **Horizons, chances, targets and ranges**: N+k in words (from the shell's horizon wording), the odds meter and the
   range bar as labelled samples, the strategy's bar, and what agreement does and does not mean.
4. **The strategies**: the three families as boxes with a one-paragraph description each and the registry's
   strategies listed by name (the description in the tooltip, the one setting each differs in under it, a link to the
   Strategy lab), and the rule that a strategy never changes.
5. **Scores, and the luck test**: a definition list (profit after costs with the two cost views, return per trade,
   win rate, target reached, in range, drawdown, too few to rank) and the luck bar explained with the "edge" /
   "luck?" labels.
6. **Head-to-head picks, and the two cost views**: the accuracy and head-to-head views, the two pick rules in words,
   and the two cost labels of every pick (market cost; viable at your cost, decision 51).
7. **News, and what its status allows**: the seven statuses as the badges the pages use, each with its meaning from
   the shell's table, the evidence rules, and the sentiment arrows.
8. **Intraday checks**: how often, what is measured, the five band words and the three flags with their meaning.
9. **The pages**: eleven tiles, one line each, linking to the mockups.
10. **Where the numbers come from**: collection, settlement, no hand-typed numbers, the as-of and freshness rule,
    and what the assistant does.
11. **Glossary** (folded) and the research-only note; **footer**.

## Data and contract
- Static content by the spec. `data.json` is composed from four catalogue files only for the shell, the go-live
  checklist, the default amount and the strategy list (`notes.md` lists each field); every sentence is written for the
  page. No new data request.
- The constants the text cites (2 months, about 300 trades, 2 checks per session, 20 trades to rank, 15 years, the
  95% interval) are the shell's named constants with their sources, never typed inline.

## Design rules kept
Design system v2 only; light theme; phone and desktop (one column; the family boxes and page tiles stack on a phone);
never colour alone (every badge has words, the check icons have words); keyboard: the chips, links, tooltips and the
glossary's summary are focusable; plain language throughout (about 78 characters per line); Paper explained and shown;
research only, said in the first section and in the closing note.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. Rebuild is byte-identical.

## Decisions taken for the owner (reported to the orchestrator)
- The Help page is one scrolling page with an anchor chip row rather than tabs, so a reader can search it and a link
  from another page can land on a section.
- The strategy list and the go-live checklist come from the catalogue, so the Help page never contradicts the
  registry or the scoreboard.
- Sample visual parts are drawn with the pages' own helpers and labelled "sample", rather than described in words.
