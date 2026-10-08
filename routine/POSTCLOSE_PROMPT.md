Run the post-close run for MARKET=<india|us> in this repository (docs/SPEC.md F6.1; session B3, notes in
docs/ws/b3.md). Schedule: India 17:45 IST, US 18:15 New York time, i.e. at least 120 minutes after the close, when a
session's bar counts as final (`BAR_SETTLE_MINUTES` in `constants/calendar.py`; cron in docs/DESIGN.md section 2). Follow
CLAUDE.md. Work from the repo root. Export `MB_MARKET=<market>` and `PYTHONPATH=scripts`. Research only: never place
trades, never connect to a broker; a paper trade is a record, never an order.

Data rules: files under `data/` are append-only. Only the scripts below write there (`collect_prices.py`, the
inbox imports of step 3a, `lab.py settle`, the `eod-add` gate and `alerts.py`); you and the EOD analyst write only
under `work/`. Delete
`work/eod_analysis.jsonl` before the analyst runs and right after it is stored, so a stale file is never stored twice.
Every step prints a JSON summary: save it under `work/steps/`.

1. Prepare: `mkdir -p work`, `rm -rf work/steps && mkdir -p work/steps`, then
   `pip install -q -r requirements.txt`.

2. Session check: `python scripts/market_status.py > work/steps/market_status.json`. If `trading_day` is false,
   stop: no session closed today (post nothing; the next post-close run settles anything due).

3. Close bars: `python scripts/collect_prices.py > work/steps/collect_prices.json`, then
   `python scripts/validate.py --stage collect > work/steps/validate_collect.json`. On a blocking failure, list it in
   your final message and still run step 4: the engine settles a trade only once its exit session's bar is final
   (a trade with no entry is recorded as `no_entry` or `skipped_price_above_amount` once its exit time has passed);
   a trade whose exit bar is missing settles on the next stored final close, flagged `exit_delayed`.

3a. Inbox (when the web tier is live; needs `MOTHERDUCK_INBOX_TOKEN`, skip both when it is unset):
    `python scripts/company.py import-inbox --slack-reply > work/steps/company_import.json`, then
    `python scripts/portfolio.py import-inbox > work/steps/portfolio_import.json` (paper trades from the dashboard
    or the Claude app, checked against today's stored bars). Commands that `onboard.yml` could not finish (logged
    `failed`) are retried here. Never blocking: a non-zero exit of either (a source down, MotherDuck unreachable)
    or a refused or failed command goes into your final message, and the run goes on to step 4. Step 9's
    `git add data` commits everything they write (watchlist_events, command_log, slack_posts, portfolio_trades and
    an added company's backfilled history). On a holiday step 2 stops before this step; `onboard.yml` imports then.

4. Settle: first deepen a shallow clone, so the lock check (a prediction or pick counts only when its row was
   first committed before D's open) can find each row's first commit:
   `[ "$(git rev-parse --is-shallow-repository)" = true ] && git fetch --shallow-since="$(date -u -d '21 days ago' +%F)" origin main || true`
   (21 days cover N+5 plus the sessions a trade may stay due; a failed fetch never blocks: the lock then checks
   `made_at` only; say so in your final message). Then
   `python scripts/lab.py settle > work/steps/lab_settle.json` (session B2's engine, docs/ws/b2.md). It
   settles every paper trade whose exit bar is final, in both views (accuracy, head-to-head), exactly once, and
   appends the rows to `data/<market>/paper_trades_settled/` and their two cost views to `data/<market>/cost_views/`.
   It refuses a prediction or pick made or first committed at or after D's open (`refused_not_locked` in its
   summary) and re-settles a trade as a new row when a split record changes. On a non-zero exit, stop here and
   report it.

5. EOD facts: `python -m marketbrief.traders eod-prepare > work/steps/eod_prepare.json` writes
   `work/eod_facts.json`: the day's results per family and pick rule, and the items to explain (every head-to-head
   trade settled today, the 5 biggest wins and 5 biggest misses by return %; reasons already stored are left out).
   Its money numbers are the market-cost view (`paper_trades_settled`: costs, net_pnl, return_pct), on which
   strategies are ranked; the your-cost view in `cost_views` is not quoted (owner decision, 2026-10-07).
   - `needs_agent` false (nothing to explain): go to step 7.

6. EOD analyst: run the `eod-analyst` subagent with the market; it reads `work/eod_facts.json` only and writes
   `work/eod_analysis.jsonl`. Gate: `python -m marketbrief.traders eod-validate work/eod_analysis.jsonl >
   work/steps/eod_validate.json` (ids, numbers from the stored facts, enums, word limits, no advice). On exit 1 send
   the errors back to the analyst once and validate again.

7. Store: `python -m marketbrief.traders eod-add work/eod_analysis.jsonl > work/steps/eod_add.json` (an absent file
   is fine when step 5 said `needs_agent` false: a day without settled trades stores the fixed line). If it still fails
   after the retry: `python -m marketbrief.traders eod-add work/eod_analysis.jsonl --valid-only` stores the valid
   reasons and the day's deterministic results (summary withheld when the summary failed); list each dropped line in
   your final message. Delete `work/eod_analysis.jsonl`.

8. Close results (session B6, docs/ws/b6.md): `python scripts/alerts.py close > work/steps/alerts_close.json`, then
   `python scripts/alerts.py corrections > work/steps/alerts_corrections.json`. The first posts rule vs AI, every
   head-to-head trade and the 10 biggest wins and losses settled today into today's #market-brief thread; the second
   replies in an earlier day's thread for each trade re-settled since that day's close post (30-day window). Exit 2
   (neither Slack token nor webhook, or a token without a channel) or exit 1: note it in your final message and go on; never retry by hand.

9. Save: `git add data && git diff --cached --quiet || git commit -m "<market> post-close TODAY"` (TODAY =
   `date -u +%F`; this includes `data/<market>/slack_posts`), then `git push origin HEAD:main`; if the push is
   rejected, `git pull --rebase origin main` and push again. If that rebase stops on a conflict in an append-only
   `data/` file (a news or intraday light run appended to the same day file meanwhile), resolve it as step 12 of
   routine/PROMPT.md says (main's version, then only this run's added lines whose `id` is not in it); a conflict
   outside `data/`, or a second failed push: stop and say so.

10. Warehouse (optional, never blocking): only when step 9 pushed a commit,
    `python scripts/warehouse_sync.py > work/steps/warehouse_sync.json`. It copies the market's stored data as of
    now into MotherDuck and rebuilds the read models whose payload changed, then revalidates the app's cache of
    them (needs `MOTHERDUCK_TOKEN`; without it the local file under `work/` is written instead). Note any failure,
    skip or `revalidate` failure in the final message; never retry and never run `--full`.

11. End with a short message: any collect failure of step 3 and the inbox results of step 3a; from step 4's summary
    the rows appended (`written`), the trades computed per status (`by_status`), `refused_not_locked` and, for the
    US, `waiting_for_eurusd`; the EOD gate result, any dropped lines, the Slack result, the warehouse result and the
    commit hash or "nothing committed".
