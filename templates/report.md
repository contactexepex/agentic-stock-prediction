# Filling the daily report

`scripts/report.py` writes `reports/<market>/<session_date>.md` and `work/slack_<market>.md`
with every number, table and chart link. Replace each `<!-- AGENT:... -->` marker with short
narrative from the context pack, the news brief, the bull/bear cases and the forecaster, then
delete the marker. Keep the `<!-- report-data: ... -->` line (report.py uses it to tell whether
a filled report is still current). Never change a number, table or chart link the script wrote; quote numbers
only from those tables or the context pack. Plain, short sentences. Every news id must support the exact
claim it is attached to (its headline or summary says it); never carry over background or causes
from the bull/bear cases unless they cite evidence for them. `scripts/validate.py --stage report`
checks each number against the same kind of number (percent or plain) for the companies or symbols
its sentence names, the market level, and the news ids it cites, so name the company and cite the id
in the sentence that quotes their number. It cannot tell an invented number that equals a real one;
the weekly spot-check judge reads a sample for claims, ids and numbers.

The filled report is also the source of the HTML report (`scripts/html_report.py`, run after the
report gate passes): it copies the narrative below verbatim from under each heading and turns every
cited id into a link to its source. So write each section only under its own heading, cite ids
in parentheses as usual, and keep it readable for a novice (explain any jargon in a few words).
Numbers, ranges, charts and per-company news and events in the HTML come from the data, never
from this text.

Report markers:
- `headline`: 1-2 sentences, the most important thing for today's session.
- `top3`: exactly three bullet lines (`- ...`), the three things that matter most today, one
  short sentence each with its evidence id(s). The HTML shows them at the top, and the Slack
  draft's `top3` repeats the same three points.
- `yesterday`: 2-4 lines: how the market and the watchlist moved and why (news ids), and what
  the ranges scored table says (which misses, likely reason).
- `calls`: one line per call (ticker, horizon, rationale, evidence ids), then abstentions with
  a 1-line reason each, including hard blocks (earnings within 1 day, BLOCKED data).
- `outlook`: the key risks for tomorrow and this week (events table, overnight cues, regime).
- `sector:<name>`: 2-3 lines per sector pair: what moved each stock, bull vs bear (start them
  with `Bull:` and `Bear:`; the HTML highlights both on each company's card in the sector),
  whether both moved together (sector news) or apart (company news).
- `data_quality`: failed collectors and feeds (and `stale` news feeds) from the run's JSON
  summaries; "none" if clean.
  On a late run (`market_status.py` `late_run: true`) say so first: the run started after the
  session closed, so no calls were made and closed-session ranges were not published. On a
  mid-session run (`in_session: true`) say first that the run started after the session opened,
  so no calls or 1-day ranges were made and the 5-day ranges are late (shown, never scored).
  Then the validation gates (`validate.py`, routine/PROMPT.md): one line per failure or warning
  (stage, code, detail, tickers, and what was dropped or withheld); "validation: all gates passed"
  if there were none.
  Then one line per row of the context pack's "Judge FAILs from the previous run not yet in a
  report" section (e.g. the monthly graph-builder or the weekly spot-check, judged after the previous brief was posted):
  run date, agent, reason, what was dropped. Leave it out if that section shows `_none_`.

Slack draft markers (the draft is the first message of the day's thread and stays at most 12
lines; the chart images and the HTML file follow as replies, posted by `notify_slack.py`):
- `top3`: three lines, each starting with `• `, the same three points as the report's `top3`
  (ids may be left out here; keep each line short).
- `failures`: failed collectors in one line (and a failed `html_report.py`), or delete the line
  if nothing failed.
