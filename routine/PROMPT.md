Run the daily market-brief pipeline for MARKET=<india|us> in this repository. Follow
CLAUDE.md. Work from the repo root. TODAY is the output of `date -u +%F`. Export
`MB_MARKET=<market>` so every script uses this market. Research only: never place trades.

Judge every agent and every narrative (CLAUDE.md "Judging every change"). Run the judge
subagent with three inputs: the exact instructions you gave, the output's claims, and where the
output lives. Judge:
- the news-analyst (`work/enriched.jsonl` plus its brief);
- each researcher (its returned case text; save it to `work/bull.md` / `work/bear.md` first);
- the forecaster (`work/predictions.jsonl` plus its table);
- the summaries you write in step 10;
- the filled report and Slack draft in step 11;
- the graph-builder (`work/graph.jsonl`) in step 14.
Agent records stay in `work/` until the judge returns PASS; only then append them to `data/`.
Delete `work/enriched.jsonl`, `work/predictions.jsonl` and `work/graph.jsonl` before each agent
runs and right after each append, so a stale file can never be appended twice.
On FAIL, send the fix list back once (to the agent, or fix your own narrative) and judge again.
The daily run allows ONE retry because it is time-boxed; build work repeats until PASS. If it
still fails:
- append nothing from that agent;
- news brief failed: the researchers and the forecaster get no brief and must abstain on any
  call that needs news evidence;
- one researcher failed: the forecaster gets only the passing case and must abstain unless both
  sides were heard;
- your narrative failed (summary or report): replace each failed section with "Narrative withheld:
  failed review (<reason>)"; the numbers, tables and charts written by the scripts stay.
Record every FAIL with its reason where it can still be read before the next commit: FAILs from
steps 7-10 in both the report's `data_quality` section and the daily summary; a step 11 FAIL only
in `data_quality` (the summary was already judged in step 10); a step 14 FAIL only in
`data/<market>/judgments/` (the brief is already posted), and the next run lists it in its
`data_quality`: the context pack's section "Judge FAILs from the previous run not yet in a
report" shows it (step 11).
Append each verdict, PASS or FAIL, as one line to `data/<market>/judgments/YYYY/MM/TODAY.jsonl`
(via a work/ file and `cat >>`): `id` = `TODAY-<agent>-<round>-<HHMMSS UTC>` (unique on a same-day rerun),
`run_date`, `agent` (one of news-analyst, bull-researcher, bear-researcher, forecaster, summaries,
report, slack, graph-builder), `round`, `verdict`, `summary` (max 40 words), `dropped` (what was not
used, or null), `recorded_at` (ISO UTC). Verdicts from steps 10-11 are listed in `data_quality` and
committed in step 12; the step 14 verdict is committed in step 14 (the brief is already posted).

1. Prepare: `mkdir -p work`. If
   `python -c "import duckdb, feedparser, yfinance, pandas, exchange_calendars"` fails, run
   `pip install -q -r requirements.txt`.

2. Holiday check: `python scripts/market_status.py`. If `trading_day` is false, post one line
   to Slack #market-brief with
   `python scripts/notify_slack.py --text "<market name>: market closed today, next session <session_date>"`
   (exit code 2 = no webhook: use the Slack connector as in step 13) and stop. If `late_run` is
   true (the run started after the close of `session_date`, at `session_close_utc`), carry on,
   but tell the forecaster it is a late run: it abstains on every ticker with reason "late run".
   `ranges.py` then skips ranges whose target session has closed, labels the others late (never
   scored) and ignores cues quoted after that session's open. Say so in the report's `data_quality` section. If `in_session` is true (a manual run
   after the open of `session_date`, at `session_open_utc`), carry on, but tell the forecaster
   it is a mid-session run: it abstains on every ticker and horizon with reason "mid-session run".
   `ranges.py` then publishes no 1-day ranges and labels the 5-day ranges late (shown for the
   record, never scored), and ignores cues and option snapshots quoted after the open. Say so in
   `data_quality` too.

3. Collect: run `python scripts/collect_prices.py`, `collect_quotes.py`, `collect_events.py`,
   `collect_news.py`, `collect_filings.py` and `collect_options.py` (all in `scripts/`;
   options are US only, India skips), and for India also
   `collect_relations_india.py` (insider/promoter trades, bulk and block deals, shareholding and
   pledges from NSE) and then `collect_nse_india.py` (announcements, quarterly results, FII/DII
   flows, delivery %), one after the other, never in parallel (NSE throttles each session).
   Keep each JSON summary; list its `warnings` (an endpoint that returned nothing at all) in
   the report's `data_quality` section.
   A failed collector is not fatal: continue and report what failed (an `allowlist_needed`
   entry names a domain the environment's network settings must allow).
   Relationships (SEC, US; other markets print `skipped`): also run `collect_insiders.py`
   (Form 4) and `collect_stakes.py` (13D/13G) every day, and `collect_holdings.py` (13F): it
   downloads only when a new quarter's 13F filings exist and otherwise prints `skipped`.
   Fundamentals (SEC XBRL, US; other markets print `skipped`): run `collect_fundamentals.py`
   every day. It downloads a company's financial data only when a new 10-Q/10-K is listed, so
   only new filings add rows; `new_filings` in its summary names them.
   Run the five SEC collectors (`collect_filings`, `collect_insiders`, `collect_stakes`,
   `collect_holdings`, `collect_fundamentals`) one after another, never in parallel: each
   throttles only its own requests, and together they must stay under SEC's 10 requests/second. `collect_events`
   also reads SEC (US earnings-date backfill), so never run it alongside them either.

4. Score: `python scripts/score_predictions.py`.

5. Indicators, regime and calibration: `python scripts/features.py`, then
   `python scripts/calibrate.py`. Keep both JSON summaries.

6. Context: `python scripts/context.py > work/context.md`.

7. News: run the news-analyst subagent on today's `data/<market>/news/` file and, for India,
   also today's `data/india/announcements/YYYY/MM/<today>.jsonl` (NSE exchange filings; ids
   `nse-ann-<seq_id>`, the one exception to the 16-character news id). Keep its brief. Give the
   judge both input files: `work/enriched.jsonl` should hold one record per new news id plus
   one per new `nse-ann-` id, and nothing else.

8. Debate: run bull-researcher and bear-researcher in parallel, passing each the market and
   the news brief.

9. Forecast and ranges: run the forecaster subagent with the market, the news brief and both
   cases (only what passed the judge). Judge its output; on PASS append `work/predictions.jsonl`
   to `data/<market>/predictions/` and delete the work file. Only then run `python scripts/ranges.py`
   (it reads the appended calls and publishes the 50% and 80% price ranges), and
   `python scripts/context.py > work/context.md` again so the report shows calls and ranges.

10. Summaries (in `summaries/<market>/`):
   - Write `daily/TODAY.md` (max 400 words): regime, per ticker what changed and why, macro
     and overnight cues, calls made, notable failures in data collection.
   - If `weekly/<previous ISO week, e.g. 2026-W40>.md` does not exist and daily summaries
     exist for that week, write it from those daily summaries (max 500 words).
   - If `monthly/<previous month, e.g. 2026-09>.md` does not exist and weekly or daily
     summaries exist for that month, write it (max 600 words).
   - Judge every summary you wrote (each id must support its claim; each number must match the
     context pack or DuckDB) before step 12.

10a. Weekly review (first trading day of each ISO week): `python scripts/review.py --if-due`.
    It reviews the previous ISO week once (it does nothing if that review is already stored, so
    a missed first day is caught up on the next run), writes `reports/<market>/review-<week>.md`
    and appends a record to `data/<market>/reviews/`. Keep its JSON summary. Its proposed
    `config/ranges.yaml` changes are for a human to decide: never edit config in the routine.
    report.py links the review in the report and adds one Slack line on the day it is written.

11. Charts and report: `python scripts/charts.py`, then `python scripts/report.py`. This writes
    `reports/<market>/<session_date>.md` (all numbers, tables and charts) and the Slack draft
    `work/slack_<market>.md`. Fill every `<!-- AGENT:... -->` marker in both files following
    `templates/report.md`, then delete the markers. Never change a number, table or chart
    link written by the script, and keep the `<!-- report-data: ... -->` line. In `data_quality`,
    copy every row of the context pack's "Judge FAILs from the previous run not yet in a report"
    section (e.g. a failed monthly graph-builder run) as one line. If report.py
    prints `"report_kept": true` (today's report was already filled by an earlier run from the
    same data), keep that report and fill only the Slack draft. If it prints a `warning` with
    `previous_report`, the data changed: fill the rebuilt report, reusing the previous narrative
    only where it still holds.

12. Save (only after the judge passed the summaries, report and Slack draft, or each failed section was
    replaced as above and listed in `data_quality`): `git add data summaries reports && git commit -m "<market> daily run TODAY"` then
    `git push origin HEAD:main`. If the push is rejected, `git pull --rebase origin main`
    and push again. Pushing to main is intended: the next run must see today's data.

13. Notify: run `python scripts/notify_slack.py`. It posts the filled `work/slack_<market>.md`
    as ONE message to #market-brief through the incoming webhook in `SLACK_WEBHOOK_URL`. If it
    exits with code 2 (no webhook configured) and a Slack connector is available in this
    session, post the same text as one message to #market-brief (channel id in
    `config/settings.yaml`) with the connector instead. Nothing else is posted.

14. Connection map (monthly): if `python scripts/graph.py status` reports `refresh_due: true`
    (no refresh attempt yet this month), delete `work/graph.jsonl`, run the graph-builder subagent
    with the market, and judge `work/graph.jsonl` (each edge against its cited source). On PASS
    run `python scripts/graph.py add work/graph.jsonl`; on FAIL (after one retry) add nothing.
    Delete `work/graph.jsonl`, then always record the attempt, even if it added nothing:
    `python scripts/graph.py attempt --note "<one line from its summary>"`. Then commit only what
    exists and changed, and push as in step 12:
    `git add data/<market>/graph_runs data/<market>/judgments; [ -d data/<market>/graph ] && git add data/<market>/graph;`
    `git diff --cached --quiet || git commit -m "<market> connection map TODAY"`.
    It runs after the brief so it never delays it; new edges feed the "Connections" section
    from the next run.

Never edit or delete existing files under data/. If inputs are missing or thin, say so and
abstain rather than guess.
