Run the weekly research run for MARKET=<india|us> in this repository (docs/SPEC.md F6.2; session B3, notes in
docs/ws/b3.md). Schedule: Saturday 10:00 local (India 10:00 IST, US 10:00 New York time; cron in docs/DESIGN.md
section 2). It is separate from the existing weekly review (step 10a of the first pre-open run of the ISO week), which
stays as it is. Follow CLAUDE.md. Work from the repo root. Export `MB_MARKET=<market>` and `PYTHONPATH=scripts`.
Research only: never place trades; the director's proposals change nothing until the owner applies them. Run every
step below even on a week without a session: each script says when it has nothing to do.

Data rules: files under `data/` are append-only. Only the scripts below write there: `lab.py news-impact`
(`data/<market>/news_impact/`), `lab.py backtest --store` (`data/<market>/lab_backtests/`), `director-add` (one
`research_reviews` row, plus `reports/<market>/research-<iso_week>.md`) and `alerts.py weekly`
(`data/<market>/slack_posts/`); you and the director write only under `work/`. Never apply a proposed diff:
a config change is the owner's, through a judged change. Delete `work/research_review.json` before the director runs
and right after it is stored. Save every step's JSON summary under `work/steps/`.

1. Prepare: `mkdir -p work`, `rm -rf work/steps && mkdir -p work/steps`, then
   `pip install -q -r requirements.txt`.

2. News-impact study (F3, session B2): `python scripts/lab.py news-impact > work/steps/lab_news_impact.json`. It
   appends the ISO week's `news_impact` rows (docs/SPEC.md F3: per event type, verification status and materiality,
   the abnormal move over N+1..N+5), from stored data as of now; row ids already stored are skipped. On a non-zero exit, carry on: the director then sees no
   news-impact rows and says so; note it in your final message.

2b. Stored back-tests (session B2, docs/ws/b2.md; read by the Strategy-lab page): optional, never blocking.
   `python scripts/model_history.py --market <market> > work/steps/model_history.json` (Yahoo daily history into the
   gitignored cache `work/model_history/<market>/`; network; writes only under `work/`). If its summary's
   `<market>.rows` is 0 (nothing fetched), skip the back-test: a stored run without the history would block a correct
   rerun for that date. Otherwise run `python scripts/lab.py --market <market> backtest --history --store >
   work/steps/lab_backtest.json` (appends the back-test rows to `data/<market>/lab_backtests/`, skipping ids already
   stored; the US run needs EUR/USD bars, from data/ or the cache, and exits 2 without them). On a non-zero exit of
   either, a skipped back-test or a non-empty `failed` list, note it in your final message and go on to step 3.

3. Inputs: `python -m marketbrief.traders director-prepare > work/steps/director_prepare.json` writes
   `work/research_inputs.json` (the ISO week of the last completed session; leaders per family to date and this
   week, news-impact rows, the week's EOD analyses, AI reasons and lessons, the registry and the current text of each
   config file a proposal may change).

4. Director: run the `research-director` subagent with the market; it reads `work/research_inputs.json` only and
   writes `work/research_review.json`. Gate: `python -m marketbrief.traders director-validate
   work/research_review.json > work/steps/director_validate.json` (cited ids from the inputs, numbers from the cited
   records, proposal ids and kinds, allowed files, each diff applies to the file as it is now, no live strategy
   changed, no trade advice). On exit 1 send the errors back to the director once and validate again; if it still
   fails, store nothing this week and report the errors.

5. Store: `python -m marketbrief.traders director-add work/research_review.json > work/steps/director_add.json`. It
   writes `reports/<market>/research-<iso_week>.md` and appends the `research_reviews` row with every proposal as
   `proposed`. A week already stored is refused. Delete `work/research_review.json`.

6. Weekly post (session B6, docs/ws/b6.md): `python scripts/alerts.py weekly > work/steps/alerts_weekly.json` posts
   the week's research report as its own #market-brief post. Exit 2 (neither Slack token nor webhook, or a token without a channel) or exit 1: note it
   and go on; never retry by hand.

7. Save: `git add data reports && git diff --cached --quiet || git commit -m "<market> weekly research <iso_week>"`
   (this includes `data/<market>/slack_posts`), then `git push origin HEAD:main`; if the push is rejected,
   `git pull --rebase origin main` and push again. If that rebase stops on a conflict in an append-only `data/` file
   (a news light run appended to the same day file meanwhile), resolve it as step 12 of routine/PROMPT.md says; a
   conflict outside `data/`, or a second failed push: stop and say so.

8. Warehouse (optional, never blocking): only when step 7 pushed a commit,
   `python scripts/warehouse_sync.py > work/steps/warehouse_sync.json` (the market's copy in MotherDuck as of now,
   the read models whose payload changed and their revalidation; needs `MOTHERDUCK_TOKEN`). Note any failure or skip;
   never retry and never run `--full`.

9. End with a short message: the leaders, the number of findings and proposals, the report path, the Slack result,
   any step 2 or 2b failure, the warehouse result and the commit hash or "nothing committed".
