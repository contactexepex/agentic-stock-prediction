Run the post-close run for MARKET=<india|us> in this repository (docs/SPEC.md F6.1; session B3, notes in
docs/ws/b3.md). Schedule: India 17:45 IST, US 18:15 New York time, i.e. at least 120 minutes after the close, when a
session's bar counts as final (`BAR_SETTLE_MINUTES` in `constants/calendar.py`); Wave 5 creates the schedules. Follow
CLAUDE.md. Work from the repo root. Export `MB_MARKET=<market>` and `PYTHONPATH=scripts`. Research only: never place
trades, never connect to a broker; a paper trade is a record, never an order.

Data rules: files under `data/` are append-only. Only the scripts below write there (`collect_prices.py`, the
settlement step and the `eod-add` gate); you and the EOD analyst write only under `work/`. Delete
`work/eod_analysis.jsonl` before the analyst runs and right after it is stored, so a stale file is never stored twice.
Every step prints a JSON summary: save it under `work/steps/`.

1. Prepare: `mkdir -p work`, `rm -rf work/steps && mkdir -p work/steps`, then
   `pip install -q -r requirements.txt`.

2. Session check: `python scripts/market_status.py > work/steps/market_status.json`. If `trading_day` is false,
   stop: no session closed today (post nothing; the next post-close run settles anything due).

3. Close bars: `python scripts/collect_prices.py > work/steps/collect_prices.json`, then
   `python scripts/validate.py --stage collect > work/steps/validate_collect.json`. On a blocking failure settle
   nothing for the tickers it lists: they settle on the next stored close (flagged `exit_delayed` by the engine).

4. Settle: `python -m marketbrief.traders settle > work/steps/traders_settle.json`. It settles, through session
   B2's engine interface (`marketbrief.contracts.protocol.settle`), every paper trade whose exit session closed by
   now, in both views (accuracy, head-to-head), and appends the rows to `data/<market>/paper_trades_settled/`. A
   trade already settled is skipped (re-runnable); `pending` lists trades the engine cannot settle yet. Exit 2 = the
   engine is not available: stop here and report it; nothing was written.

5. EOD facts: `python -m marketbrief.traders eod-prepare > work/steps/eod_prepare.json` writes
   `work/eod_facts.json`: the day's results per family and pick rule, and the items to explain (every head-to-head
   trade settled today, the 5 biggest wins and 5 biggest misses by return %; reasons already stored are left out).
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

8. Save: `git add data && git commit -m "<market> post-close TODAY"` (TODAY = `date -u +%F`), then
   `git push origin HEAD:main`; if the push is rejected, `git pull --rebase origin main` and push again.

9. Optional, never blocking (wired in Wave 5): the warehouse sync (`python scripts/warehouse_sync.py`) and the Slack
   close results of session B6. Until then, end with a short message: settled trades per view, pending trades, the
   EOD gate result and any dropped lines.
