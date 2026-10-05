#!/usr/bin/env python3
"""Print a compact Markdown context pack for the agents: prices and returns, news activity
and sentiment by window, recent filings, open predictions and the track record.
The agents read this instead of raw files, which keeps each run small."""
from __future__ import annotations

from common import connect, md_table, utc_today

SECTIONS = [
    ("Latest prices and returns (%)", """
        SELECT ticker, date, round(close, 2) AS close,
               round(ret_1d * 100, 2) AS d1, round(ret_5d * 100, 2) AS d5, round(ret_20d * 100, 2) AS d20
        FROM returns QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
        ORDER BY ticker"""),
    ("News activity and sentiment by window", """
        SELECT ticker,
               count(*) FILTER (WHERE day >= current_date - 1)  AS n_1d,
               count(*) FILTER (WHERE day >= current_date - 7)  AS n_7d,
               count(*) FILTER (WHERE day >= current_date - 30) AS n_30d,
               round(avg(sentiment) FILTER (WHERE day >= current_date - 7), 2)  AS sent_7d,
               round(avg(sentiment) FILTER (WHERE day >= current_date - 30), 2) AS sent_30d,
               count(*) FILTER (WHERE materiality = 'high' AND day >= current_date - 7) AS high_7d
        FROM news_ticker_day GROUP BY ticker ORDER BY ticker"""),
    ("SEC filings, last 14 days", """
        SELECT ticker, form, filing_date, description, url
        FROM filings WHERE filing_date >= current_date - 14 ORDER BY filing_date DESC, ticker"""),
    ("Open predictions", """
        SELECT id, ticker, as_of_date, horizon_days, direction, confidence FROM open_predictions
        ORDER BY as_of_date, ticker"""),
    ("Track record by horizon (all time)", """
        SELECT horizon_days, count(*) AS n, round(avg(hit::INT), 3) AS hit_rate,
               round(avg(confidence), 3) AS avg_confidence
        FROM track_record GROUP BY horizon_days ORDER BY horizon_days"""),
    ("Track record by confidence band, last 90 days", """
        SELECT CASE WHEN confidence < 0.6 THEN '0.50-0.59'
                    WHEN confidence < 0.7 THEN '0.60-0.69' ELSE '0.70+' END AS band,
               count(*) AS n, round(avg(hit::INT), 3) AS hit_rate
        FROM track_record WHERE target_date >= current_date - 90 GROUP BY band ORDER BY band"""),
]


def main() -> None:
    con = connect()
    print(f"# Context pack for {utc_today()} (UTC)\n")
    for title, sql in SECTIONS:
        print(f"## {title}\n")
        print(md_table(con.execute(sql)))


if __name__ == "__main__":
    main()
