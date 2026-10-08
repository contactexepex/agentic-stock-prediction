# Assistant mockup: rationale

Page 11 of docs/SPEC.md section 6 ("chat with sources and as-of times; also a side panel on every page"; F11; the
`explain` tool of F10, `mcp/tools.yaml`), designed in the design track from W1's data catalogue after W1 answered the
track's data request 6 with the `assistant_answer` entity (three answers per market, each composed from the
catalogue's own records). Status: **built on the owner's delegated authority** (2026-10-08, the owner away: "go with
your recommendation, notify the orchestrator"); judged and landed by the track; the owner reviews it in the morning.

Files: `build.py` (catalogue -> `data.json` -> `template.html` -> `page.html` through `design/mockups/_shared/mockup.py`),
`data.json` (the example conversation per market as the `explain` tool answers it), `page.html`, `notes.md`,
screenshots `shot-1280-full.png`, `shot-390-full.png`, `shot-390-viewport.png`.

## Who reads it and how
The owner, or a reader of the cockpit, with a question the pages do not answer directly: why a paper trade ended as
it did, who did better on a day, what the data says about a company. The page is the full version of the panel
every page carries: the conversation, with every answer marked by what it is (answered from the data, not in the
data, declined) and the records it rests on as chips a reader can open; beside it, how the assistant answers, the
records cited so far, and the budget. The assistant explains and cites; it never advises, and the page says so in
the head, in the rules and in the declined answer itself.

## Layout (desktop: the conversation beside a narrow column of rules, records and budget; phone: one column)
1. **Page head** (the shell's chips).
2. **Ask the data** (Paper tag): the conversation, oldest first; each question as a bubble with its channel
   (dashboard or Slack /ask) and the time asked; each answer as a bubble with a state badge (green "answered from
   the data", amber "not in the data", paper "declined: no advice on real trades"), the as-of time it read up to, and
   the cited records as chips (kind in words, the id, a tooltip with the stored time, a link to the page where the
   kind lives). The **composer**: a question box limited to the tool's 500 characters with a counter, an Ask button
   (Ctrl/Cmd+Enter too); in the mockup a question is recorded as pending ("mockup: not sent") and nothing is called.
   **Example questions** as chips that fill the box.
3. **How it answers**: six rules in plain words (stored data only, citations and as-of times, "not in the data",
   never advice, the same tool on every page and in Slack, kept 90 days).
4. **Records cited**: the distinct records of the conversation with kind, id and stored time, each with an Open link.
5. **Budget**: the daily budget and the monthly hard cap (F11) as tiles, and the honest note that the spend is not in
   the example data (a data request) while the real panel shows it and says "over budget".
6. **Footer**.

## Data and contract
- `data.json` is composed from three catalogue files only (`notes.md` lists each field): the market status and the
  go-live block for the shell, and the market's Assistant answers with their cited records. The page computes nothing
  but presentation.
- No look-ahead on data: an answer is shown when its `as_of` (the data it read up to) is at or before the cut-off, and
  every cited record was stored at or before the answer's `as_of` (asserted at build time). The example questions
  were asked 10-25 minutes after the noon cut-off about data up to it, as a conversation log shows.
- New data request: the budget state (today's and the month's spend), recorded in `_data_requests`. The budget caps,
  the question length and the retention period are the shell's named constants with their sources (F11,
  `mcp/tools.yaml`).

## Design rules kept
Design system v2 only; light theme; phone and desktop (the columns stack at 1000 px; long record ids wrap, never
clipped); never colour alone (every state badge has words and an icon); keyboard: the composer, the Ask button, the
example chips, the market switch and every record chip and Open link are buttons or links, every tooltip element
focusable; plain language; Paper in the head and the card; research only, said in the head, the rules and the
declined answer.

## Checked
`check_page.js`: no console errors, no overflow, no external requests at 1280 and 390 px. `check_text.js` (twelve
widths, both markets): no clipped, overflowing or overlapping text. A script at 390 and 1280 px in both markets: an
example chip fills the box, the counter counts, the box keeps at most 500 characters, Ask records a pending question
and nothing else changes, the three answer states render as claimed, every tooltip element is focusable, the market
switch re-renders, no page error. Rebuild is byte-identical.

## Decisions taken for the owner (reported to the orchestrator)
- The page shows the conversation as a chat with the sources under each answer rather than a table of answers, since
  that is how the panel on every page will read; the records panel beside it is the "sources" view of the spec.
- Every answer carries a visible state (answered / not in the data / declined), so a reader sees at once when the
  assistant could not or would not answer.
- The budget is shown as the spec's caps with an honest "spend not in the example data" note rather than an invented
  meter.
- Long record ids wrap in full rather than being shortened, so an id can be copied and found.
