Run the daily market-brief pipeline for MARKET=<india|us> in this repository. Follow
CLAUDE.md. Work from the repo root. TODAY is the output of `date -u +%F`. Export
`MB_MARKET=<market>` so every script uses this market. Research only: never place trades.

Judge every agent. After each subagent returns (news-analyst, bull-researcher,
bear-researcher, forecaster) and after you fill the report in step 11, run the judge subagent
with three inputs: the exact instructions given, the agent's report, and where its output
lives. Agent records stay in `work/` until the judge returns PASS. Only then append them to
`data/` (news-analyst: `work/enriched.jsonl`; forecaster: `work/predictions.jsonl`). On FAIL,
send the judge's fix list back to the same agent once (fix step 11 yourself) and judge again.
If it still fails, do not use that output: append nothing (no calls, no enrichment), continue,
and list each FAIL with its reason in the report's `data_quality` section and the daily summary.

1. Prepare: `mkdir -p work`. If
   `python -c "import duckdb, feedparser, yfinance, pandas, exchange_calendars"` fails, run
   `pip install -q -r requirements.txt`.

2. Holiday check: `python scripts/market_status.py`. If `trading_day` is false, post one line
   to Slack #market-brief with
   `python scripts/notify_slack.py --text "<market name>: market closed today, next session <session_date>"`
   (exit code 2 = no webhook: use the Slack connector as in step 13) and stop. If `late_run` is
   true (the run started after the close of `session_date`, at `session_close_utc`), carry on,
   but tell the forecaster it is a late run: it abstains on every ticker with reason "late run".
   `ranges.py` then skips ranges whose target session has closed and ignores cues quoted after
   it. Say so in the report's `data_quality` section.

3. Collect: run `python scripts/collect_prices.py`, `collect_quotes.py`, `collect_events.py`,
   `collect_news.py`, `collect_filings.py` and `collect_options.py` (all in `scripts/`;
   options are US only, India skips), and for India also
   `collect_relations_india.py` (insider/promoter trades, bulk and block deals, shareholding and
   pledges from NSE). Keep each JSON summary.
   A failed collector is not fatal: continue and report what failed (an `allowlist_needed`
   entry names a domain the environment's network settings must allow).
   Relationships (SEC, US; other markets print `skipped`): also run `collect_insiders.py`
   (Form 4) and `collect_stakes.py` (13D/13G) every day, and `collect_holdings.py` (13F): it
   downloads only when a new quarter's 13F filings exist and otherwise prints `skipped`.
   Run the four SEC collectors (`collect_filings`, `collect_insiders`, `collect_stakes`,
   `collect_holdings`) one after another, never in parallel: each throttles only its own
   requests, and together they must stay under SEC's 10 requests/second. `collect_events`
   also reads SEC (US earnings-date backfill), so never run it alongside them either.

4. Score: `python scripts/score_predictions.py`.

5. Indicators, regime and calibration: `python scripts/features.py`, then
   `python scripts/calibrate.py`. Keep both JSON summaries.

6. Context: `python scripts/context.py > work/context.md`.

7. News: run the news-analyst subagent on today's `data/<market>/news/` file. Keep its brief.

8. Debate: run bull-researcher and bear-researcher in parallel, passing each the market and
   the news brief.

9. Forecast and ranges: run the forecaster subagent with the market, the news brief and both
   cases. Then `python scripts/ranges.py` (publishes the 50% and 80% price ranges), and
   `python scripts/context.py > work/context.md` again so the report shows calls and ranges.

10. Summaries (in `summaries/<market>/`):
   - Write `daily/TODAY.md` (max 400 words): regime, per ticker what changed and why, macro
     and overnight cues, calls made, notable failures in data collection.
   - If `weekly/<previous ISO week, e.g. 2026-W40>.md` does not exist and daily summaries
     exist for that week, write it from those daily summaries (max 500 words).
   - If `monthly/<previous month, e.g. 2026-09>.md` does not exist and weekly or daily
     summaries exist for that month, write it (max 600 words).

11. Charts and report: `python scripts/charts.py`, then `python scripts/report.py`. This writes
    `reports/<market>/<session_date>.md` (all numbers, tables and charts) and the Slack draft
    `work/slack_<market>.md`. Fill every `<!-- AGENT:... -->` marker in both files following
    `templates/report.md`, then delete the markers. Never change a number, table or chart
    link written by the script, and keep the `<!-- report-data: ... -->` line. If report.py
    prints `"report_kept": true` (today's report was already filled by an earlier run from the
    same data), keep that report and fill only the Slack draft. If it prints a `warning` with
    `previous_report`, the data changed: fill the rebuilt report, reusing the previous narrative
    only where it still holds.

12. Save (only after the judge passed the report, or its failures are listed in `data_quality`): `git add data summaries reports && git commit -m "<market> daily run TODAY"` then
    `git push origin HEAD:main`. If the push is rejected, `git pull --rebase origin main`
    and push again. Pushing to main is intended: the next run must see today's data.

13. Notify: run `python scripts/notify_slack.py`. It posts the filled `work/slack_<market>.md`
    as ONE message to #market-brief through the incoming webhook in `SLACK_WEBHOOK_URL`. If it
    exits with code 2 (no webhook configured) and a Slack connector is available in this
    session, post the same text as one message to #market-brief (channel id in
    `config/settings.yaml`) with the connector instead. Nothing else is posted.

14. Connection map (monthly): if `python scripts/graph.py status` reports `refresh_due: true`
    (no refresh attempt yet this month), run the graph-builder subagent with the market, then
    always record the attempt, even if it added nothing:
    `python scripts/graph.py attempt --note "<one line from its summary>"`. Then commit only what
    exists and changed, and push as in step 12:
    `git add data/<market>/graph_runs; [ -d data/<market>/graph ] && git add data/<market>/graph;`
    `git diff --cached --quiet || git commit -m "<market> connection map TODAY"`.
    It runs after the brief so it never delays it; new edges feed the "Connections" section
    from the next run.

Never edit or delete existing files under data/. If inputs are missing or thin, say so and
abstain rather than guess.
