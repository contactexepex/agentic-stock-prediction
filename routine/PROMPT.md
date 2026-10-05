Run the daily market-brief pipeline for MARKET=<india|us> in this repository. Follow
CLAUDE.md. Work from the repo root. TODAY is the output of `date -u +%F`. Export
`MB_MARKET=<market>` so every script uses this market. Research only: never place trades.

1. Prepare: `mkdir -p work`. If
   `python -c "import duckdb, feedparser, yfinance, pandas, exchange_calendars"` fails, run
   `pip install -q -r requirements.txt`.

2. Holiday check: `python scripts/market_status.py`. If `trading_day` is false, post one line
   to Slack #market-brief ("<market name>: market closed today, next session <session_date>")
   and stop.

3. Collect: run `python scripts/collect_prices.py`, `collect_quotes.py`, `collect_events.py`,
   `collect_news.py` and `collect_filings.py` (all in `scripts/`). Keep each JSON summary.
   A failed collector is not fatal: continue and report what failed.

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

11. Report: write `reports/<market>/TODAY.md` following `templates/report.md`.

12. Save: `git add data summaries reports && git commit -m "<market> daily run TODAY"` then
    `git push origin HEAD:main`. If the push is rejected, `git pull --rebase origin main`
    and push again. Pushing to main is intended: the next run must see today's data.

13. Notify: post ONE message to the Slack channel #market-brief, at most 12 lines: market name
    and regime, a 1-line headline, the 1-day 80% ranges for the tickers with calls (ticker,
    range, direction, confidence), yesterday's ranges hit/miss (80% and 50%), the 2 most
    material news items, failed collectors if any, and the link
    https://github.com/contactexepex/agentic-stock-prediction/blob/main/reports/<market>/TODAY.md

Never edit or delete existing files under data/. If inputs are missing or thin, say so and
abstain rather than guess.
