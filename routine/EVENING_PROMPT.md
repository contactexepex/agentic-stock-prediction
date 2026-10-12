Run the evening forecast run for MARKET=<india|us> in this repository (owner decision 2026-10-10; docs/ws/b17.md).
Schedule, Mon-Fri: India 21:30 UTC, US 18:30 New York time. Both are after the day's close plus the 120 minutes a
session's bar needs to count as final (`BAR_SETTLE_MINUTES`); crons in docs/DESIGN.md section 2. Follow CLAUDE.md. Work
from the repo root. Export `MB_MARKET=<market>` and `PYTHONPATH=scripts`. Research only: never place trades, never
connect to a broker; nothing here is investment advice.

What this run is: on the day's close it publishes PREVIEW ranges, model scores and the rule strategies' and baselines'
predictions for the next session, for the owner to review in the evening. It runs no AI agents (no news analyst,
researchers, forecaster or AI traders) and posts nothing to Slack. Its rows are never paper trades and never scored:
- ranges go to `data/<market>/ranges_evening/`, predictions to `data/<market>/strategy_predictions_evening/`, both
  marked `run: "evening"`;
- model scores go to `model_scores` with `run: "evening"`.
The next pre-open run (routine/PROMPT.md) adds overnight news and cues and writes the revision of record in `ranges`
and `strategy_predictions`. Only those rows trade: if the pre-open run fails, nothing trades that day. The website
shows the evening and pre-open values side by side (B12's forecast history).

Data rules: files under `data/` are append-only. Only the scripts below write there; you write only under `work/`.
Every step prints a JSON summary: save it under `work/steps/`.

1. Prepare: `mkdir -p work`, `rm -rf work/steps && mkdir -p work/steps`, then `pip install -q -r requirements.txt`.
   If it fails, note it in your final message and carry on.

2. Session check: `python scripts/market_status.py > work/steps/market_status.json`.
   - If `in_session` or `late_run` is true, the day's bar is not final yet: stop, and say so in your final message.
   - Do not stop on `trading_day` false. India's Friday evening run falls on a Saturday local date, and after a day
     without a session the steps below find nothing new, because they skip ids already stored.

3. Close bars and indicators:
   - `python scripts/collect_prices.py > work/steps/collect_prices.json` (the day's final bars);
   - `python scripts/features.py > work/steps/features.json`;
   - `python scripts/calibrate.py > work/steps/calibrate.json`;
   - then the gate `python scripts/validate.py --stage features > work/steps/validate_features.json` (a feature row
     for every ticker's newest bar, a regime row).
   On exit 1, list the failures in your final message: the tickers it names get no previews, and nothing is
   previewed without a regime row.

4. Model scores: `python scripts/model_scores.py --evening > work/steps/model_scores.json`. It appends each
   ticker's P(up) per horizon for the next session, tagged `run: "evening"` (a row only where the probability
   changed). The pre-open run's own model scores are the revision. If it fails, note it and go on; step 5 then uses
   the newest stored scores.

5. Preview ranges: `python scripts/ranges.py --evening > work/steps/ranges.json`. It writes the 50% and 80% ranges
   of every horizon N+1..N+5 to `ranges_evening` (same ids as the pre-open ranges; ids already in `ranges_evening` are
   skipped). They carry no forecaster widening and no overnight cue.

6. Preview predictions: `python scripts/lab.py predict --evening > work/steps/lab_predict.json`. It appends the
   rule strategies' and baselines' predictions for D, the next session, to `strategy_predictions_evening`. Ids
   already stored there are skipped. It writes no abstentions, cost views or picks. Exit 2 (`ok` false, e.g. the
   evening ranges or scores are missing): note its `message` and go on.

7. Save: `git add data && git diff --cached --quiet || git commit -m "<market> evening forecast TODAY"` (TODAY =
   `date -u +%F`), then `git push origin HEAD:main`. If the push is rejected, `git pull --rebase origin main` and push
   again. If that rebase stops on a conflict in an append-only `data/` file (a news run appended to the same day file
   meanwhile), resolve it as step 12 of routine/PROMPT.md says: main's version, then only this run's added lines
   whose `id` is not in it. A conflict outside `data/`, or a second failed push: stop and say so.

8. Warehouse (optional, never blocking): only when step 7 pushed a commit,
   `python scripts/warehouse_sync.py > work/steps/warehouse_sync.json`. It copies the market's stored data as of now
   into MotherDuck, rebuilds the read models whose payload changed (the company pages then show the evening preview)
   and revalidates the app's cache of them. Needs `MOTHERDUCK_TOKEN`; without it the local file under `work/` is
   written instead. Note any failure or skip; never retry and never run `--full`.

9. End with a short message:
   - the session the previews are for (`session_date` of step 2) and the as-of close (`previous_session`);
   - collect, features or gate failures;
   - the counts written by steps 4-6;
   - the warehouse result;
   - the commit hash, or "nothing committed".
   Paper only: no proven edge yet.
