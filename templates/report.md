# Filling the daily report

`scripts/report.py` writes `reports/<market>/<session_date>.md` and `work/slack_<market>.md`
with every number, table and chart link. Replace each `<!-- AGENT:... -->` marker with short
narrative from the context pack, the news brief, the bull/bear cases and the forecaster, then
delete the marker. Keep the `<!-- report-data: ... -->` line (report.py uses it to tell whether
a filled report is still current). Never change a number, table or chart link the script wrote; quote numbers
only from those tables or the context pack. Plain, short sentences. Every news id must support the exact
claim it is attached to (its headline or summary says it); never carry over background or causes
from the bull/bear cases unless they cite evidence for them. The judge checks each id and number.

Report markers:
- `headline`: 1-2 sentences, the most important thing for today's session.
- `yesterday`: 2-4 lines: how the market and the watchlist moved and why (news ids), and what
  the ranges scored table says (which misses, likely reason).
- `calls`: one line per call (ticker, horizon, rationale, evidence ids), then abstentions with
  a 1-line reason each, including hard blocks (earnings within 1 day, BLOCKED data).
- `outlook`: the key risks for tomorrow and this week (events table, overnight cues, regime).
- `sector:<name>`: 2-3 lines per sector pair: what moved each stock, bull vs bear in one line,
  whether both moved together (sector news) or apart (company news).
- `data_quality`: failed collectors and feeds (and `stale` news feeds) from the run's JSON
  summaries; "none" if clean.
  On a late run (`market_status.py` `late_run: true`) say so first: the run started after the
  session closed, so no calls were made and closed-session ranges were not published.
  Then the judge's verdicts: one line per agent (PASS, or FAIL with the reason and what was dropped).
  Then one line per row of the context pack's "Judge FAILs from the previous run not yet in a
  report" section (e.g. the monthly graph-builder, judged after the previous brief was posted):
  run date, agent, reason, what was dropped. Leave it out if that section shows `_none_`.

Slack draft markers (the whole message stays at most 12 lines):
- `headline`: one line.
- `news`: the 2 most material items, one line each.
- `failures`: failed collectors in one line, or delete the line if none failed.
