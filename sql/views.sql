-- Derived views on top of the base views created in scripts/common.py
-- (news, news_enriched, filings, predictions, outcomes, prices).
-- Ad hoc aggregation example (swap the interval for 1 day, 1 week, 1 month):
--   SELECT ticker, time_bucket(INTERVAL '2 weeks', day) AS period,
--          count(*) AS articles, avg(sentiment) AS avg_sentiment
--   FROM news_ticker_day GROUP BY ALL ORDER BY period;

-- One bar per ticker per trading day, numbered so horizons count trading days.
CREATE OR REPLACE VIEW bars AS
SELECT ticker, date, close,
       row_number() OVER (PARTITION BY ticker ORDER BY date) AS rn
FROM (SELECT DISTINCT ON (ticker, date) * FROM prices ORDER BY ticker, date, collected_at DESC);

CREATE OR REPLACE VIEW returns AS
SELECT ticker, date, close,
       close / lag(close, 1)  OVER w - 1 AS ret_1d,
       close / lag(close, 5)  OVER w - 1 AS ret_5d,
       close / lag(close, 20) OVER w - 1 AS ret_20d
FROM bars
WINDOW w AS (PARTITION BY ticker ORDER BY date);

-- Latest enrichment per article (re-analysis appends a newer row, it never edits).
CREATE OR REPLACE VIEW enriched_latest AS
SELECT DISTINCT ON (id) * FROM news_enriched ORDER BY id, analyzed_at DESC;

-- One row per (ticker, article), dated by publish time (fallback: first seen).
CREATE OR REPLACE VIEW news_ticker_day AS
WITH x AS (
    SELECT unnest(tickers) AS ticker, id, title, source,
           coalesce(published_at, first_seen_at) AS ts
    FROM news
)
SELECT x.ticker, CAST(x.ts AS DATE) AS day, x.id, x.title, x.source,
       e.sentiment, e.relevance, e.materiality
FROM x LEFT JOIN enriched_latest e USING (id);

CREATE OR REPLACE VIEW open_predictions AS
SELECT p.* FROM predictions p
WHERE p.id NOT IN (SELECT prediction_id FROM outcomes);

CREATE OR REPLACE VIEW track_record AS
SELECT p.*, o.base_date, o.target_date, o.actual_return, o.hit, o.scored_at
FROM predictions p JOIN outcomes o ON o.prediction_id = p.id;

-- Full daily bars (one per ticker per date, latest collection wins).
CREATE OR REPLACE VIEW ohlc AS
SELECT ticker, date, open, high, low, close, volume
FROM (SELECT DISTINCT ON (ticker, date) * FROM prices ORDER BY ticker, date, collected_at DESC);

-- Latest known date per (ticker, event type); a moved date is a newer row.
CREATE OR REPLACE VIEW company_events AS
SELECT DISTINCT ON (ticker, type) * FROM events
WHERE ticker IS NOT NULL ORDER BY ticker, type, first_seen_at DESC, date;

-- Latest quote per symbol per UTC day.
CREATE OR REPLACE VIEW quotes_latest AS
SELECT DISTINCT ON (symbol, CAST(collected_at AS DATE)) *, CAST(collected_at AS DATE) AS day
FROM quotes ORDER BY symbol, CAST(collected_at AS DATE), collected_at DESC;

-- Latest indicator snapshot per ticker per as-of date, and the latest regime per as-of date.
CREATE OR REPLACE VIEW features_latest AS
SELECT DISTINCT ON (ticker, as_of_date) * FROM features ORDER BY ticker, as_of_date, computed_at DESC;

CREATE OR REPLACE VIEW regime_latest AS
SELECT DISTINCT ON (as_of_date) * FROM regime ORDER BY as_of_date, computed_at DESC;
