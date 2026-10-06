Run the daily market-brief pipeline for MARKET=<india|us> in this repository. Follow
CLAUDE.md. Work from the repo root. TODAY is the output of `date -u +%F`. Export
`MB_MARKET=<market>` so every script uses this market. Research only: never place trades.

Daily runs are gated by deterministic checks, not by the judge (CLAUDE.md "Judging every
change"): `python scripts/validate.py --stage <stage>` runs after each step below and prints a JSON
summary (`ok`, `failures`, `warnings`, each with a `code`, a `detail` and the affected `tickers`).
It exits 1 on a blocking failure. Save each summary as `work/steps/validate_<stage>.json`. List
every failure and warning in the report's `data_quality` section (one line each: stage, code,
detail, tickers), and never post silently: a blocked part is always named there.
The judge subagent still runs (1) once a week on a sample of the past week's output (step 14a)
and (2) on the monthly graph-builder edges (step 14). What replaces each former per-agent judge
step:
- news-analyst: `--stage news` (schema, ids are today's new news/announcement ids, nothing stored
  twice, scores in range); the weekly spot-check reads enrichment summaries of sampled evidence;
- bull and bear researchers: `--stage forecast` (every cited id exists and was public before the
  call) and the weekly spot-check (reasons match evidence);
- forecaster: `--stage forecast` (every CLAUDE.md prediction rule) and the weekly spot-check;
- summaries, report and Slack draft: `--stage report` (every number in agent-written text is a
  stored or script-written number, no AGENT markers left, every range published or explained)
  and the weekly spot-check (claims are true).
Agent records stay in `work/` until their gate passes; only then append them to `data/`.
Delete `work/enriched.jsonl`, `work/predictions.jsonl` and `work/graph.jsonl` before each agent
runs and right after each append, so a stale file can never be appended twice.
On a blocking failure, fix it once (send the failure list back to the agent, or fix your own
narrative) and run the stage again. The daily run allows ONE retry because it is time-boxed. If it
still fails:
- `collect` (stale or missing bars, bad files or rows, off-source news): tell the forecaster the
  affected tickers; it abstains on each with reason "data failed validation". Off-source or
  malformed news rows are never cited. A failure with no tickers (e.g. a bad file) applies to
  every ticker whose input it names; if unsure, abstain on all;
- `news`: append nothing from the news-analyst; the researchers and the forecaster get no brief
  and must abstain on any call that needs news evidence;
- `features`: no calls for the tickers listed (no feature row) and none at all without a regime
  row; the report says so;
- `context`: rebuild the pack once (`python scripts/context.py > work/context.md`); if it still
  fails, make no calls;
- `forecast`: drop each failing record from `work/predictions.jsonl` (keep the valid ones) and
  list each dropped id with its reason; on `CALLS_NOT_ALLOWED` (late or mid-session run) drop all;
- `report`: replace each section holding an unmatched number with "Narrative withheld: failed
  validation (<code>)"; the numbers, tables and charts written by the scripts stay. A daily
  summary with an unmatched number: correct the number from the pack, or remove the sentence.
Warnings never block: list them in `data_quality`.

1. Prepare: `mkdir -p work`. If
   `python -c "import duckdb, feedparser, yfinance, pandas, exchange_calendars"` fails, run
   `pip install -q -r requirements.txt`.

2. Holiday check: `python scripts/market_status.py`. If `trading_day` is false, post one line
   to Slack #market-brief with
   `python scripts/notify_slack.py --text "<market name>: market closed today, next session <session_date>"`
   (exit code 2 = no bot token and no webhook: use the Slack connector as in step 13) and stop. If `late_run` is
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
   Save each JSON summary as `work/steps/<script name>.json` (e.g.
   `python scripts/collect_prices.py > work/steps/collect_prices.json`; `mkdir -p work/steps` first)
   and list its `warnings` (an endpoint that returned nothing at all) in
   the report's `data_quality` section.
   Macro, flows and short selling (issue #9; a market without the collector's config section
   prints `skipped`): run `collect_macro.py` (US: Treasury yield curve, FRED credit spreads and
   breakeven, Cboe put/call ratios) and `collect_shorts.py` (US: FINRA daily short-sale volume and
   short interest), and `collect_flows_india.py` (India: NSDL FPI investment and NSE index closes
   with P/E, P/B, dividend yield) after `collect_nse_india.py`, never alongside an NSE collector.
   List every `failed` entry of their summaries in `data_quality` (a session file missing for the
   latest session is only a note: it is published after the close).
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
   also reads SEC (US earnings-date backfill) and, for India, NSE results filings (earnings dates;
   only tickers that are due), so never run it alongside the SEC or NSE collectors either. List its
   `sec_failed` / `nse_failed` tickers in `data_quality`.

   Gate: `python scripts/validate.py --stage collect > work/steps/validate_collect.json` (freshness
   of bars against the exchange calendar and of this run's fetches, the collector summaries in
   `work/steps/`, empty or truncated files, schemas, UTC timestamps, duplicate ids, closes, big
   moves, news sources). On exit 1 act as the preamble says.

4. Score: `python scripts/score_predictions.py`.

5. Indicators, regime and calibration: `python scripts/features.py`, then
   `python scripts/calibrate.py`. Keep both JSON summaries. Gate:
   `python scripts/validate.py --stage features > work/steps/validate_features.json` (a feature
   row for every ticker's newest bar, a regime row).

6. Context: `python scripts/context.py > work/context.md`. Gate:
   `python scripts/validate.py --stage context > work/steps/validate_context.json`.

7. News: run the news-analyst subagent on today's `data/<market>/news/` file and, for India,
   also today's `data/india/announcements/YYYY/MM/<today>.jsonl` (NSE exchange filings; ids
   `nse-ann-<seq_id>`, the one exception to the 16-character news id). Keep its brief.
   `work/enriched.jsonl` should hold one record per new news id plus one per new `nse-ann-` id,
   and nothing else. Gate: `python scripts/validate.py --stage news > work/steps/validate_news.json`;
   if it passes, append `work/enriched.jsonl` to `data/<market>/news_enriched/YYYY/MM/TODAY.jsonl`
   with `cat >>` and delete the work file.

8. Debate: run bull-researcher and bear-researcher in parallel, passing each the market and
   the news brief.

9. Forecast and ranges: run the forecaster subagent with the market, the news brief and both
   cases, and the tickers a `collect` or `features` gate blocked (it abstains on them). Gate:
   `python scripts/validate.py --stage forecast > work/steps/validate_forecast.json` (every
   CLAUDE.md prediction rule; evidence ids exist and were public before `made_at`; no calls on a
   late or mid-session run). If it passes (or after the failing records were dropped as the
   preamble says), append `work/predictions.jsonl` to
   `data/<market>/predictions/YYYY/MM/TODAY.jsonl` and delete the work file. Only then run `python scripts/ranges.py`
   (it reads the appended calls and publishes the 50% and 80% price ranges), and
   `python scripts/context.py > work/context.md` again so the report shows calls and ranges.

10. Summaries (in `summaries/<market>/`):
   - Write `daily/TODAY.md` (max 400 words): regime, per ticker what changed and why, macro
     and overnight cues, calls made, notable failures in data collection.
   - If `weekly/<previous ISO week, e.g. 2026-W40>.md` does not exist and daily summaries
     exist for that week, write it from those daily summaries (max 500 words).
   - If `monthly/<previous month, e.g. 2026-09>.md` does not exist and weekly or daily
     summaries exist for that month, write it (max 600 words).
   - Quote numbers only from the context pack or DuckDB: `validate.py --stage report` (step 11)
     also checks every number in `daily/TODAY.md`.

10a. Weekly review (first trading day of each ISO week): `python scripts/review.py --if-due`.
    It reviews the previous ISO week once (it does nothing if that review is already stored, so
    a missed first day is caught up on the next run), writes `reports/<market>/review-<week>.md`
    and appends a record to `data/<market>/reviews/`. Keep its JSON summary. Its proposed
    `config/ranges.yaml` changes are for a human to decide: never edit config in the routine.
    report.py links the review in the report and adds one Slack line on the day it is written.

10b. Neo4j copy (optional, never blocks the run): `python scripts/neo4j_sync.py`. It only reads
    `data/` and sends today's new and corrected records to Neo4j (a rebuildable copy; the repo
    stays the source of truth). Exit 2 (`NEO4J_URI` not set): add the line "Neo4j sync skipped:
    NEO4J_URI not set" to the report's `data_quality`. Exit 1 (server unreachable or a kind
    failed): carry on, and add one `data_quality` line naming the failed kinds and the `error` from
    its JSON summary (never the URI or password). Do not retry and never run `--full` in the routine.

11. Charts and report: `python scripts/charts.py` (single-purpose PNGs: price ranges, sector
    moves, track record), then `python scripts/report.py`. This writes
    `reports/<market>/<session_date>.md` (all numbers, tables and charts; the agent-editable
    source) and the Slack draft `work/slack_<market>.md` (the thread's short summary message:
    regime, top 3, number of calls, link). Fill every `<!-- AGENT:... -->` marker in both files following
    `templates/report.md`, then delete the markers. Never change a number, table or chart
    link written by the script, and keep the `<!-- report-data: ... -->` line (report.py also saves
    the unfilled copies `work/report_<market>_<session_date>.skeleton.md` and
    `work/slack_<market>.skeleton.md`, which tell the gate script lines from agent lines). In
    `data_quality`, list every validate.py failure and warning of this run, and copy every row of the context pack's "Judge FAILs from the previous run not yet in a report"
    section (e.g. a failed monthly graph-builder run or weekly spot-check) as one line. If report.py
    prints `"report_kept": true` (today's report was already filled by an earlier run from the
    same data), keep that report and fill only the Slack draft. If it prints a `warning` with
    `previous_report`, the data changed: fill the rebuilt report, reusing the previous narrative
    only where it still holds. Gate:
    `python scripts/validate.py --stage report > work/steps/validate_report.json` (no AGENT
    markers, every number in the agent-written lines of the report, the Slack draft and
    `summaries/<market>/daily/TODAY.md` is in the context pack, the script-written skeleton, stored
    news text or DuckDB; every ticker and horizon has a range or a calendar reason for none).

11a. HTML report: only after the report gate passed (or each failed section was replaced as
    above and listed in `data_quality`), run `python scripts/html_report.py`. It refuses a report that
    still has AGENT markers. It builds `reports/<market>/<session_date>.html` (the reader's view:
    filters by sector and company, a price chart and plain-language range per company, reasons,
    track record) and `reports/<market>/index.html` from the validated report plus the stored data,
    and lists the files for Slack in `work/slack_<market>_files.json`. It adds no narrative of its
    own (numbers come from the data, text is copied from the validated report), so it needs no
    further check. If it fails, list the failure in the Slack failures line and post anyway.

12. Save (only after the report gate passed, or each failed section was
    replaced as above and listed in `data_quality`): `git add data summaries reports && git commit -m "<market> daily run TODAY"` then
    `git push origin HEAD:main`. If the push is rejected, `git pull --rebase origin main`
    and push again. Pushing to main is intended: the next run must see today's data.

13. Notify: run `python scripts/notify_slack.py`. With `SLACK_BOT_TOKEN` set it posts a thread
    to #market-brief (channel id in `config/settings.yaml`): the filled `work/slack_<market>.md`
    as the first message, then the chart images as one reply, then the HTML report file as a
    reply. Without the token it posts the summary text as ONE message through the incoming
    webhook in `SLACK_WEBHOOK_URL`. If it exits with code 2 (neither configured) and a Slack
    connector is available in this session, post the same text as one message to #market-brief
    with the connector instead. Nothing else is posted.

14. Connection map (monthly): if `python scripts/graph.py status` reports `refresh_due: true`
    (no refresh attempt yet this month), delete `work/graph.jsonl`, run the graph-builder subagent
    with the market, and run the judge subagent on `work/graph.jsonl` (each edge against its cited
    source; give it the exact instructions, the graph-builder's claims and the file). On PASS
    run `python scripts/graph.py add work/graph.jsonl` (it validates every row again); on FAIL
    (after one retry) add nothing. Record the verdict as in step 14a (`agent` graph-builder).
    Delete `work/graph.jsonl`, then always record the attempt, even if it added nothing:
    `python scripts/graph.py attempt --note "<one line from its summary>"`. Then commit only what
    exists and changed, and push as in step 12:
    `git add data/<market>/graph_runs data/<market>/judgments; [ -d data/<market>/graph ] && git add data/<market>/graph;`
    `git diff --cached --quiet || git commit -m "<market> connection map TODAY"`.
    It runs after the brief so it never delays it; new edges feed the "Connections" section
    from the next run.

14a. Weekly spot-check (first trading day of each ISO week, after the brief so it never delays
    it): `python scripts/spotcheck.py --if-due`. If it prints `due: false`, skip this step. If
    `empty` is true (no calls and no filled report in the previous ISO week), append its `record`
    as printed (verdict SKIP). Otherwise run the judge subagent on its sample (2 forecasts with
    their evidence rows and outcome, 1 filled report of that week; the sample is seeded by market
    and week, so a rerun picks the same items) with the instructions "Weekly spot-check
    (.claude/agents/judge.md): check every item of `checklist`", the sample JSON as the claims,
    and the report path and `data/<market>/` as where the work lives. One round only (no
    retry: the output is already published). Append one verdict line to
    `data/<market>/judgments/YYYY/MM/TODAY.jsonl` (via a work/ file and `cat >>`), using the
    printed `record` with `verdict` PASS or FAIL and a `summary` of at most 40 words. Judgment
    records (schema `judgments` in `scripts/common.py`): `id` = `TODAY-<agent>-<round>-<HHMMSS UTC>`
    (spot-check: `TODAY-spotcheck-<week>-<round>-<HHMMSS UTC>`), `run_date`, `agent`
    (graph-builder or spotcheck), `round`, `verdict`, `summary`, `dropped` (what was not used, or
    null), `recorded_at` (ISO UTC). A FAIL is listed in the next run's `data_quality` through the
    context pack's "Judge FAILs from the previous run" section; if it shows a rule broken in the
    daily output, open a GitHub issue so the gates or the agent instructions get fixed. Commit
    and push as in step 14: `git add data/<market>/judgments` and
    `git diff --cached --quiet || git commit -m "<market> spot-check <week>"`.

15. Neo4j catch-up (final step, optional, non-blocking): `python scripts/neo4j_sync.py` again, so
    the verdicts and connection-map edges appended after step 10b reach Neo4j today. Whatever it
    returns, the run is finished: the report is already posted, so a failure here is not added to
    it. Each kind's watermark advances only after it synced, so the next run's step 10b re-sends
    anything this step missed and lists any failure in that run's `data_quality`.

Never edit or delete existing files under data/. If inputs are missing or thin, say so and
abstain rather than guess.
