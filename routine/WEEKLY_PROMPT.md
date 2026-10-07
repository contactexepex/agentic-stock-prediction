Run the weekly research run for MARKET=<india|us> in this repository (docs/SPEC.md F6.2; session B3, notes in
docs/ws/b3.md). Schedule: Saturday 10:00 local (India 10:00 IST, US 10:00 New York time); Wave 5 creates the
schedules. It is separate from the existing weekly review (step 10a of the first pre-open run of the ISO week), which
stays as it is. Follow CLAUDE.md. Work from the repo root. Export `MB_MARKET=<market>` and `PYTHONPATH=scripts`.
Research only: never place trades; the director's proposals change nothing until the owner applies them.

Data rules: files under `data/` are append-only. Only `director-add` writes there (one `research_reviews` row) and to
`reports/<market>/research-<iso_week>.md`; you and the director write only under `work/`. Never apply a proposed diff:
a config change is the owner's, through a judged change. Delete `work/research_review.json` before the director runs
and right after it is stored. Save every step's JSON summary under `work/steps/`.

1. Prepare: `mkdir -p work`, `rm -rf work/steps && mkdir -p work/steps`, then
   `pip install -q -r requirements.txt`.

2. News-impact study (F3, session B2; wired in Wave 5): run B2's weekly news-impact step so the week's
   `news_impact` rows exist as of now. If it is not available or fails, carry on: the director then sees no
   news-impact rows and says so.

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
   the week's research report as its own #market-brief post. Exit 2 (no Slack token or webhook) or exit 1: note it
   and go on; never retry by hand.

7. Save: `git add data reports && git commit -m "<market> weekly research <iso_week>"` (this includes
   `data/<market>/slack_posts`), then `git push origin HEAD:main`; if the push is rejected,
   `git pull --rebase origin main` and push again.

8. Optional, never blocking (wired in Wave 5): the warehouse sync. End with a short message: the leaders, the number
   of findings and proposals, the report path and the Slack result.
