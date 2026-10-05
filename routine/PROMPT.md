Run the daily market-brief pipeline for this repository. Follow CLAUDE.md. Work from the repo
root. TODAY is the output of `date -u +%F`. This is research only: never place trades.

1. Prepare: `mkdir -p work`. If `python -c "import duckdb, feedparser, yfinance"` fails, run
   `pip install -q -r requirements.txt`.

2. Collect: run `python scripts/collect_news.py`, `python scripts/collect_prices.py` and
   `python scripts/collect_filings.py`. Keep each JSON summary. A failed collector is not
   fatal: continue and report what failed.

3. Score: `python scripts/score_predictions.py`.

4. Context: `python scripts/context.py > work/context.md`.

5. News: run the news-analyst subagent on today's news file. Keep its brief.

6. Debate: run bull-researcher and bear-researcher in parallel, passing each the news brief.

7. Forecast: run the forecaster subagent with the news brief and both cases.
   Then run `python scripts/context.py > work/context.md` again so the report shows the new calls.

8. Summaries:
   - Write `summaries/daily/TODAY.md` (max 400 words): per ticker what changed and why,
     macro backdrop, calls made, notable failures in data collection.
   - If `summaries/weekly/<previous ISO week, e.g. 2026-W40>.md` does not exist and daily
     summaries exist for that week, write it from those daily summaries (max 500 words).
   - If `summaries/monthly/<previous month, e.g. 2026-09>.md` does not exist and weekly or
     daily summaries exist for that month, write it (max 600 words).

9. Report: write `reports/TODAY.md` following `templates/report.md`.

10. Save: `git add data summaries reports && git commit -m "daily run TODAY"` then
    `git push origin HEAD:main`. If the push is rejected, `git pull --rebase origin main`
    and push again. Pushing to main is intended: the next run must see today's data.

11. Notify: post to the Slack channel #market-brief, at most 8 lines: a 1-line headline, the
    calls with direction and confidence, the 2 most material news items, the 30-day hit rate
    if any calls were scored, failed collectors if any, and the link
    https://github.com/OWNER/REPO/blob/main/reports/TODAY.md

Never edit or delete existing files under data/. If inputs are missing or thin, say so and
abstain rather than guess.
