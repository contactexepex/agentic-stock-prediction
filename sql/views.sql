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
-- Past events backfilled for the range engine (source ending in "_history") are left out here.
CREATE OR REPLACE VIEW company_events AS
SELECT DISTINCT ON (ticker, type) * FROM events
WHERE ticker IS NOT NULL AND NOT ends_with(coalesce(source, ''), '_history')
ORDER BY ticker, type, first_seen_at DESC, date;

-- Every company event ever seen, once per id (past earnings days and dividends for ranges).
CREATE OR REPLACE VIEW event_history AS
SELECT DISTINCT ON (id) * FROM events WHERE ticker IS NOT NULL ORDER BY id, first_seen_at;

-- Latest quote per symbol per UTC day.
CREATE OR REPLACE VIEW quotes_latest AS
SELECT DISTINCT ON (symbol, CAST(collected_at AS DATE)) *, CAST(collected_at AS DATE) AS day
FROM quotes ORDER BY symbol, CAST(collected_at AS DATE), collected_at DESC;

-- Latest indicator snapshot per ticker per as-of date, and the latest regime per as-of date.
CREATE OR REPLACE VIEW features_latest AS
SELECT DISTINCT ON (ticker, as_of_date) * FROM features ORDER BY ticker, as_of_date, computed_at DESC;

CREATE OR REPLACE VIEW regime_latest AS
SELECT DISTINCT ON (as_of_date) * FROM regime ORDER BY as_of_date, computed_at DESC;

-- Ranges: latest per id, open ones (not yet scored), scored ones with outcomes.
CREATE OR REPLACE VIEW ranges_latest AS
SELECT DISTINCT ON (id) * FROM ranges ORDER BY id, made_at;

CREATE OR REPLACE VIEW open_ranges AS
SELECT r.* FROM ranges_latest r WHERE r.id NOT IN (SELECT range_id FROM range_outcomes);

CREATE OR REPLACE VIEW range_record AS
SELECT r.*, o.actual_close, o.z, o.hit50, o.hit80, o.naive_hit50, o.naive_hit80, o.is80_pct,
       o.naive_is80_pct, o.width80_pct, o.naive_width80_pct, o.center_err_pct, o.naive_center_err_pct
FROM ranges_latest r JOIN (SELECT DISTINCT ON (range_id) * FROM range_outcomes ORDER BY range_id, scored_at) o
  ON o.range_id = r.id;

CREATE OR REPLACE VIEW calibration_latest AS
SELECT DISTINCT ON (horizon_days) * FROM calibration ORDER BY horizon_days, as_of_date DESC, computed_at DESC;

-- Latest implied-volatility snapshot per ticker, expiry and UTC day (collect_options.py).
CREATE OR REPLACE VIEW options_latest AS
SELECT DISTINCT ON (ticker, expiry, CAST(collected_at AS DATE)) *, CAST(collected_at AS DATE) AS day
FROM options ORDER BY ticker, expiry, CAST(collected_at AS DATE), collected_at DESC;

-- Relationships (DESIGN.md phase 5). India: collect_relations_india.py; graph: graph-builder.
CREATE OR REPLACE VIEW insider_trades AS
SELECT DISTINCT ON (id) * FROM insiders ORDER BY id, first_seen_at;

-- Bulk/block deals sized against the stock's average volume over the 20 sessions before.
CREATE OR REPLACE VIEW deals_scored AS
WITH adv AS (
    SELECT ticker, date, avg(volume) OVER (PARTITION BY ticker ORDER BY date
                                           ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS adv20
    FROM ohlc
), d AS (SELECT DISTINCT ON (id) * FROM deals ORDER BY id, first_seen_at)
SELECT d.*, round(d.value / 1e7, 2) AS value_crore, round(d.shares / nullif(adv.adv20, 0), 3) AS adv_ratio
FROM d ASOF LEFT JOIN adv ON d.ticker = adv.ticker AND d.date >= adv.date;

-- One row per ticker and quarter (latest record per source wins). promoter_pct is the
-- company-filed shareholding pattern (nse_shp); the pledge dataset (nse_pledge) is depository
-- system-driven data whose own promoter figure is kept apart as sdd_promoter_pct.
CREATE OR REPLACE VIEW holdings_quarterly AS
WITH h AS (
    SELECT DISTINCT ON (ticker, period_end, source) * FROM holdings
    WHERE source IN ('nse_shp', 'nse_pledge')
    ORDER BY ticker, period_end, source, first_seen_at DESC, filed_at DESC NULLS LAST
)
SELECT ticker, period_end,
       max(promoter_pct) FILTER (WHERE source = 'nse_shp') AS promoter_pct,
       max(public_pct) FILTER (WHERE source = 'nse_shp') AS public_pct,
       max(pledged_pct_of_promoter) AS pledged_pct_of_promoter,
       max(pledged_pct_of_total) AS pledged_pct_of_total, max(sdd_promoter_pct) AS sdd_promoter_pct,
       max(depository_pledged_pct) AS depository_pledged_pct,
       -- the shareholding filing date; the pledge dataset re-stamps its date on every daily refresh
       coalesce(max(filed_at) FILTER (WHERE source = 'nse_shp'), max(filed_at)) AS filed_at
FROM h GROUP BY ticker, period_end;

CREATE OR REPLACE VIEW pledge_changes AS
SELECT *, lag(period_end) OVER wq AS prev_period,
       pledged_pct_of_promoter - lag(pledged_pct_of_promoter) OVER wq AS pledge_change_pp,
       promoter_pct - lag(promoter_pct) OVER wq AS promoter_change_pp
FROM holdings_quarterly WINDOW wq AS (PARTITION BY ticker ORDER BY period_end);

-- Connection map: latest version of each edge; an edge retracted with status 'removed' drops out.
CREATE OR REPLACE VIEW graph_edges AS
SELECT * FROM (SELECT DISTINCT ON (id) * FROM graph ORDER BY id, added_at DESC)
WHERE coalesce(status, 'active') = 'active';

-- ---------- Smart money (phase 5): insiders (Form 4), stakes (13D/13G), holdings (13F) ----------
-- insider_trades (one row per transaction line, first copy wins) is defined above.

-- Open-market insider flow per ticker (code P = purchase, S = sale; awards, exercises, tax
-- withholding and gifts are not discretionary and are left out). Values in USD, by trade date.
-- cluster_buy: 3 or more different insiders bought in the last 30 days.
CREATE OR REPLACE VIEW insider_flow AS
WITH t AS (
    SELECT *, transaction_date >= current_date - 30 AS d30, transaction_date >= current_date - 90 AS d90
    FROM insider_trades WHERE NOT derivative AND code IN ('P', 'S')
)
SELECT ticker,
       coalesce(sum(value) FILTER (WHERE code = 'P' AND d30), 0) AS buy_value_30d,
       coalesce(sum(value) FILTER (WHERE code = 'S' AND d30), 0) AS sell_value_30d,
       coalesce(sum(CASE code WHEN 'P' THEN value ELSE -value END) FILTER (WHERE d30), 0) AS net_value_30d,
       coalesce(sum(CASE code WHEN 'P' THEN value ELSE -value END) FILTER (WHERE d90), 0) AS net_value_90d,
       count(DISTINCT insider_name) FILTER (WHERE code = 'P' AND d30) AS buyers_30d,
       count(DISTINCT insider_name) FILTER (WHERE code = 'S' AND d30) AS sellers_30d,
       round(coalesce(sum(value) FILTER (WHERE code = 'S' AND d30 AND plan_10b5_1), 0)
             / nullif(sum(value) FILTER (WHERE code = 'S' AND d30), 0), 2) AS planned_sell_share_30d,
       count(DISTINCT insider_name) FILTER (WHERE code = 'P' AND d30) >= 3 AS cluster_buy,
       max(transaction_date) FILTER (WHERE code = 'P') AS last_buy,
       max(transaction_date) FILTER (WHERE code = 'S') AS last_sale
FROM t WHERE d90 GROUP BY ticker;

-- Cluster buys over history: each purchase date on which 3+ different insiders of the same
-- company had bought within the 30 days up to that date.
CREATE OR REPLACE VIEW insider_cluster_buys AS
WITH b AS (SELECT DISTINCT ticker, insider_name, transaction_date FROM insider_trades
           WHERE code = 'P' AND NOT derivative)
SELECT b1.ticker, b1.transaction_date AS window_end, count(DISTINCT b2.insider_name) AS buyers_30d,
       list(DISTINCT b2.insider_name) AS insiders
FROM b b1 JOIN b b2 ON b2.ticker = b1.ticker
     AND b2.transaction_date BETWEEN b1.transaction_date - 30 AND b1.transaction_date
GROUP BY b1.ticker, b1.transaction_date HAVING count(DISTINCT b2.insider_name) >= 3;

-- 13D/13G filings naming a watchlist company (first copy wins). kind 13D = active holder.
CREATE OR REPLACE VIEW stake_filings AS
SELECT DISTINCT ON (id) * FROM stakes ORDER BY id, first_seen_at;

-- New activist stakes: original Schedule 13D filings (amendments excluded).
CREATE OR REPLACE VIEW activist_stakes AS
SELECT ticker, filing_date, accepted_at, event_date, filer_name, percent, shares, purpose, url, id
FROM stake_filings WHERE kind = '13D' AND NOT amendment;

-- 13F filings processed (one row each): report type, completeness and notes such as
-- "reported by <manager>" for a 13F notice or why a filing cannot show exits.
CREATE OR REPLACE VIEW holdings_filings AS
SELECT filer_cik, filer_name, period, filing_date, accession, report_type, n_lines, complete, note, url
FROM holdings WHERE ticker IS NULL;

-- 13F holdings: one row per (filer, ticker, period) of common shares (options excluded; the
-- latest original filing per period wins), with the change against the filer's previous period.
-- Zero rows (exits) exist only for complete filings, so an incomplete filing (combination
-- report, confidential or partial table) never fakes an exit. A change where either quarter
-- comes from an incomplete filing is action 'incomplete' (a position moved to another
-- manager would otherwise look like a trim) and is left out of holdings_quarter's change math.
CREATE OR REPLACE VIEW holdings_change AS
WITH h AS (
    SELECT DISTINCT ON (filer_cik, ticker, period) * EXCLUDE (complete), coalesce(complete, true) AS complete
    FROM holdings WHERE put_call IS NULL AND ticker IS NOT NULL
    ORDER BY filer_cik, ticker, period, filing_date DESC, first_seen_at
)
SELECT filer_cik, filer_name, ticker, period, shares, value_usd, complete,
       lag(complete) OVER hw AS prev_complete,
       lag(period) OVER hw AS prev_period, lag(shares) OVER hw AS prev_shares,
       shares - lag(shares) OVER hw AS change_shares,
       CASE WHEN lag(shares) OVER hw IS NULL THEN 'first'
            WHEN NOT complete OR NOT lag(complete) OVER hw THEN 'incomplete'
            WHEN lag(shares) OVER hw = 0 AND shares > 0 THEN 'new'
            WHEN lag(shares) OVER hw > 0 AND shares = 0 THEN 'exit'
            WHEN shares > lag(shares) OVER hw THEN 'add'
            WHEN shares < lag(shares) OVER hw THEN 'trim'
            ELSE 'hold' END AS action
FROM h WINDOW hw AS (PARTITION BY filer_cik, ticker ORDER BY period);

-- 13F by ticker and quarter across the tracked filers. Holdings (filers_holding, shares,
-- value) count every filing; change_shares, change_pct and the action counts use only filers
-- whose filings for this and their previous period are both complete. filers_incomplete
-- counts the filers whose filing this quarter is incomplete (e.g. combination reports).
CREATE OR REPLACE VIEW holdings_quarter AS
SELECT ticker, period, count(*) AS filers_reporting,
       count(*) FILTER (WHERE shares > 0) AS filers_holding,
       count(*) FILTER (WHERE NOT complete) AS filers_incomplete,
       sum(shares) AS shares, sum(value_usd) AS value_usd,
       sum(change_shares) FILTER (WHERE action NOT IN ('first', 'incomplete')) AS change_shares,
       round(sum(change_shares) FILTER (WHERE action NOT IN ('first', 'incomplete'))
             / nullif(sum(prev_shares) FILTER (WHERE action NOT IN ('first', 'incomplete')), 0), 4) AS change_pct,
       count(*) FILTER (WHERE action = 'new') AS n_new, count(*) FILTER (WHERE action = 'exit') AS n_exit,
       count(*) FILTER (WHERE action = 'add') AS n_add, count(*) FILTER (WHERE action = 'trim') AS n_trim
FROM holdings_change GROUP BY ticker, period;

-- Weekly reviews (review.py): latest record per ISO week; a rerun appends a newer record.
CREATE OR REPLACE VIEW review_latest AS
SELECT DISTINCT ON (id) * FROM reviews ORDER BY id, computed_at DESC;

-- ---------- India primary sources from NSE (collect_nse_india.py) ----------
CREATE OR REPLACE VIEW announcements_latest AS
SELECT DISTINCT ON (id) * FROM announcements ORDER BY id, first_seen_at;

-- Latest filing per ticker, basis and period (a revised filing is a newer row).
CREATE OR REPLACE VIEW financials_latest AS
SELECT DISTINCT ON (ticker, basis, period_start, period_end) * FROM financials
ORDER BY ticker, basis, period_start, period_end, filed_at DESC NULLS LAST, first_seen_at DESC;

-- Quarterly results with the same quarter a year earlier (same basis) for y/y growth.
CREATE OR REPLACE VIEW financials_quarterly_yoy AS
SELECT q.*, p.revenue AS revenue_prev_year, p.net_profit AS net_profit_prev_year,
       q.revenue / nullif(p.revenue, 0) - 1 AS revenue_yoy,
       q.net_profit / nullif(abs(p.net_profit), 0) - sign(p.net_profit) AS net_profit_yoy
FROM financials_latest q
LEFT JOIN financials_latest p ON p.ticker = q.ticker AND p.basis = q.basis AND p.period_type = 'quarterly'
     AND p.period_end = q.period_end - INTERVAL 1 YEAR
WHERE q.period_type = 'quarterly';

CREATE OR REPLACE VIEW flows_daily AS
SELECT DISTINCT ON (date, category) * FROM flows ORDER BY date, category, first_seen_at DESC;

-- Delivery % per ticker and session, with the 20-session average before it.
CREATE OR REPLACE VIEW delivery_stats AS
WITH d AS (SELECT DISTINCT ON (date, ticker) * FROM delivery ORDER BY date, ticker, first_seen_at DESC)
SELECT *, avg(delivery_pct) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
          AS delivery_pct_avg20,
       count(*) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS n_prior
FROM d;
