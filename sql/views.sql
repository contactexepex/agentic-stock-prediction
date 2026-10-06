-- Derived views on top of the base views created in scripts/common.py
-- (news, news_enriched, filings, predictions, outcomes, prices, adjustments, ...).
-- Ad hoc aggregation example (swap the interval for 1 day, 1 week, 1 month):
--   SELECT ticker, time_bucket(INTERVAL '2 weeks', day) AS period,
--          count(*) AS articles, avg(sentiment) AS avg_sentiment
--   FROM news_ticker_day GROUP BY ALL ORDER BY period;

-- Splits and bonus issues (issue #31; scripts/adjust.py): one row per corporate action, the
-- first detected wins; a record named by a later row's `supersedes` (a hand-made correction,
-- factor 1.0 to cancel or the right factor) is left out. Applied on read by ohlc and bars below.
CREATE OR REPLACE VIEW price_adjustments AS
SELECT DISTINCT ON (id) * FROM adjustments
WHERE id NOT IN (SELECT supersedes FROM adjustments WHERE supersedes IS NOT NULL)
ORDER BY id, detected_at;

-- Daily bars as stored (one per ticker per date, latest collection wins), for audits.
CREATE OR REPLACE VIEW ohlc_raw AS
SELECT ticker, date, open, high, low, close, adj_close, volume, collected_at
FROM (SELECT DISTINCT ON (ticker, date) * FROM prices ORDER BY ticker, date, collected_at DESC);

-- Price multiplier per stored bar: the product of the factors of the ticker's adjustments with an
-- ex-date after the bar (1 when none), which puts every bar on the newest basis.
CREATE OR REPLACE VIEW bar_factors AS
SELECT o.ticker, o.date, coalesce(product(a.factor), 1.0) AS factor
FROM ohlc_raw o LEFT JOIN price_adjustments a ON a.ticker = o.ticker AND a.ex_date > o.date
GROUP BY o.ticker, o.date;

-- Full daily bars on one basis: prices x factor, volume / factor (rounded). With no adjustment the
-- factor is exactly 1 and the bars are the stored ones. Every price consumer reads this (or bars).
CREATE OR REPLACE VIEW ohlc AS
SELECT o.ticker, o.date, o.open * f.factor AS open, o.high * f.factor AS high, o.low * f.factor AS low,
       o.close * f.factor AS close, CAST(round(o.volume / f.factor) AS BIGINT) AS volume
FROM ohlc_raw o JOIN bar_factors f USING (ticker, date);

-- One bar per ticker per trading day, numbered so horizons count trading days (adjusted basis).
CREATE OR REPLACE VIEW bars AS
SELECT ticker, date, close,
       row_number() OVER (PARTITION BY ticker ORDER BY date) AS rn
FROM ohlc;

-- The same as stored (no split/bonus adjustment), for audits.
CREATE OR REPLACE VIEW bars_raw AS
SELECT ticker, date, close,
       row_number() OVER (PARTITION BY ticker ORDER BY date) AS rn
FROM ohlc_raw;

CREATE OR REPLACE VIEW returns AS
SELECT ticker, date, close,
       close / lag(close, 1)  OVER w - 1 AS ret_1d,
       close / lag(close, 5)  OVER w - 1 AS ret_5d,
       close / lag(close, 20) OVER w - 1 AS ret_20d
FROM bars
WINDOW w AS (PARTITION BY ticker ORDER BY date);

-- News with corrected ticker tags. Tags are derived, and rows are append-only, so rows written
-- before the current tagger (tag_version NULL) are re-tagged on read by news_retag
-- (scripts/news_tags.py, registered in common.connect): headline first with the config's precise
-- names minus `news_exclude` (never from news.google.com links, source names or a query hit
-- alone), split into primary_tickers / mentioned_tickers with tag_confidence. Old wire rows whose
-- title names no company keep their tags as mentioned. `news_stored` is the rows as stored.
CREATE OR REPLACE VIEW news AS
WITH r AS (
    SELECT *, news_retag(feed, title, tickers, primary_tickers, mentioned_tickers, tag_confidence,
                         tag_version) AS t_
    FROM news_stored
)
SELECT * EXCLUDE (t_) REPLACE (t_.tickers AS tickers, t_.primary_tickers AS primary_tickers,
                               t_.mentioned_tickers AS mentioned_tickers, t_.tag_confidence AS tag_confidence)
FROM r;

-- Latest enrichment per article (re-analysis appends a newer row, it never edits).
CREATE OR REPLACE VIEW enriched_latest AS
SELECT DISTINCT ON (id) * FROM news_enriched ORDER BY id, analyzed_at DESC;

-- One row per (ticker, article), dated by publish time (fallback: first seen). role: 'primary'
-- (the item is about the ticker) or 'mentioned'; tag_confidence 'low' marks tags to read with care.
CREATE OR REPLACE VIEW news_ticker_day AS
WITH x AS (
    SELECT unnest(tickers) AS ticker, id, title, source, primary_tickers, tag_confidence,
           coalesce(published_at, first_seen_at) AS ts
    FROM news
)
SELECT x.ticker, CAST(x.ts AS DATE) AS day, x.id, x.title, x.source,
       CASE WHEN list_contains(x.primary_tickers, x.ticker) THEN 'primary' ELSE 'mentioned' END AS role,
       x.tag_confidence,
       e.sentiment, e.relevance, e.materiality
FROM x LEFT JOIN enriched_latest e USING (id);

CREATE OR REPLACE VIEW open_predictions AS
SELECT p.* FROM predictions p
WHERE p.id NOT IN (SELECT prediction_id FROM outcomes);

CREATE OR REPLACE VIEW track_record AS
SELECT p.*, o.base_date, o.target_date, o.actual_return, o.hit, o.scored_at
FROM predictions p JOIN outcomes o ON o.prediction_id = p.id;

-- Where each stored bar came from: 'yahoo' unless data/<market>/price_sources/ names another
-- source (India: 'nse_bhavcopy', bars collect_prices.py filled from NSE's bhavcopy).
CREATE OR REPLACE VIEW bar_sources AS
SELECT o.ticker, o.date, coalesce(s.source, 'yahoo') AS source, s.url, s.filled_at
FROM ohlc_raw o
LEFT JOIN (SELECT DISTINCT ON (ticker, date) * FROM price_sources ORDER BY ticker, date, filled_at) s
USING (ticker, date);

-- Latest known date per (ticker, event type); a moved date is a newer row.
-- Past events backfilled for the range engine (source ending in "_history") are left out here.
CREATE OR REPLACE VIEW company_events AS
SELECT DISTINCT ON (ticker, type) * FROM events
WHERE ticker IS NOT NULL AND NOT ends_with(coalesce(source, ''), '_history')
ORDER BY ticker, type, first_seen_at DESC, date;

-- Every company event ever seen, once per id (past earnings days and dividends for ranges; SEC
-- markets also hold `periodic_report` rows, 10-Q/10-K acceptances with period_end). Not every
-- sec_history earnings row is a results release: read earnings through range_inputs.earnings_events.
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

-- Bulk/block deals sized against the stock's average volume over the 20 sessions before. The
-- deal's shares are as traded on its date; the average (adjusted ohlc volume, newest basis) is put
-- back on that date's basis by the factors of the adjustments after it (1 when none).
CREATE OR REPLACE VIEW deals_scored AS
WITH adv AS (
    SELECT ticker, date, avg(volume) OVER (PARTITION BY ticker ORDER BY date
                                           ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS adv20
    FROM ohlc
), d AS (
    SELECT x.*, coalesce((SELECT product(a.factor) FROM price_adjustments a
                          WHERE a.ticker = x.ticker AND a.ex_date > x.date), 1.0) AS _f
    FROM (SELECT DISTINCT ON (id) * FROM deals ORDER BY id, first_seen_at) x
)
SELECT d.* EXCLUDE (_f), round(d.value / 1e7, 2) AS value_crore,
       round(d.shares / nullif(adv.adv20 * d._f, 0), 3) AS adv_ratio
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

-- Announcements with the news-analyst's latest enrichment (news_enriched rows keyed by the same
-- nse-ann-<seq_id> id); NULL until the analyst has scored the item.
CREATE OR REPLACE VIEW announcements_enriched AS
SELECT a.*, e.sentiment, e.relevance, e.materiality, e.event_type, e.urgency, e.summary AS analyst_summary,
       e.analyzed_at, e.prompt_version
FROM announcements_latest a LEFT JOIN enriched_latest e USING (id);

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

-- ---------- Fundamentals (SEC XBRL company facts, collect_fundamentals.py; US) ----------
-- One value per (ticker, concept, period): the best-ranked tag reported for that period (CONCEPTS
-- in collect_fundamentals.py), from its newest filing, so a restatement or a split
-- adjustment wins. first_filed = when that tag's value for the period was first filed;
-- prev_value = the value before the latest revision (NULL = never revised).
-- Point in time: the *_asof(as_of) macros see only filings known by as_of (a TIMESTAMPTZ; a DATE
-- means 00:00 UTC that day). known_at = accepted_at, or the end of the filing date (UTC) when the
-- acceptance time is unknown. The views without _asof use every stored filing, so a restated
-- value replaces the original there: a backtest must use the _asof macros, e.g.
--   SELECT * FROM fundamentals_metrics_asof(TIMESTAMPTZ '2026-08-01 12:00:00+00')
CREATE OR REPLACE MACRO fundamentals_latest_asof(as_of) AS TABLE
WITH k AS (
    SELECT *, coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ)) AS known_at FROM fundamentals
), f AS (
    SELECT *, min(tag_rank) OVER (PARTITION BY ticker, concept, period_start, period_end) AS best_rank
    FROM k WHERE known_at <= as_of
)
SELECT DISTINCT ON (ticker, concept, period_start, period_end)
       ticker, concept, period, period_start, period_end, fiscal_year, fiscal_period, value, unit, tag,
       form, accession, filing_date, accepted_at, known_at, min(filing_date) OVER fw AS first_filed, prev_value,
       prev_value IS NOT NULL AS revised
FROM f WHERE tag_rank = best_rank
WINDOW fw AS (PARTITION BY ticker, concept, period_start, period_end)
ORDER BY ticker, concept, period_start, period_end, filing_date DESC, first_seen_at DESC;

CREATE OR REPLACE VIEW fundamentals_latest AS
SELECT * FROM fundamentals_latest_asof(TIMESTAMPTZ '9999-12-31 00:00:00+00');

-- Quarterly flows per (ticker, concept): reported quarters, plus quarters derived from the
-- cumulative fiscal-year totals where no quarter is reported (Q4 = FY - 9M, and for cash flows,
-- which 10-Qs report year-to-date only, Q2 = H1 - Q1, Q3 = 9M - H1), marked derived. A derived EPS
-- is approximate (the share count differs by period). Share averages are not derived.
CREATE OR REPLACE MACRO fundamentals_quarterly_asof(as_of) AS TABLE
WITH d AS (SELECT * FROM fundamentals_latest_asof(as_of) WHERE period IN ('quarter', 'ytd', 'annual')),
cum AS (
    SELECT d.*, lag(value) OVER cw AS prev_cum, lag(period_end) OVER cw AS prev_end,
           lag(fiscal_period) OVER cw AS prev_fp, lag(filing_date) OVER cw AS prev_filed
    FROM d
    WHERE period <> 'quarter' OR EXISTS (SELECT 1 FROM d y WHERE y.ticker = d.ticker AND y.concept = d.concept
                                         AND y.period <> 'quarter' AND y.period_start = d.period_start)
    WINDOW cw AS (PARTITION BY ticker, concept, period_start ORDER BY period_end)
),
derived AS (
    SELECT ticker, concept, prev_end + 1 AS period_start, period_end, fiscal_year,
           CASE fiscal_period WHEN 'FY' THEN 'Q4' WHEN '9M' THEN 'Q3' WHEN 'H1' THEN 'Q2' END AS fiscal_period,
           round(value - prev_cum, 6) AS value, unit, greatest(filing_date, prev_filed) AS filing_date, accession, form,
           true AS derived, fiscal_period || ' - ' || prev_fp AS derived_from
    FROM cum
    WHERE period <> 'quarter' AND prev_cum IS NOT NULL AND concept <> 'shares_diluted_avg'
      AND period_end - prev_end BETWEEN 70 AND 130
)
SELECT ticker, concept, period_start, period_end, fiscal_year, fiscal_period, value, unit, filing_date,
       accession, form, false AS derived, NULL::VARCHAR AS derived_from
FROM d WHERE period = 'quarter'
UNION ALL
SELECT * FROM derived x
WHERE NOT EXISTS (SELECT 1 FROM d q WHERE q.ticker = x.ticker AND q.concept = x.concept AND q.period = 'quarter'
                  AND abs(q.period_end - x.period_end) <= 3);

CREATE OR REPLACE VIEW fundamentals_quarterly AS
SELECT * FROM fundamentals_quarterly_asof(TIMESTAMPTZ '9999-12-31 00:00:00+00');

-- One row per ticker and fiscal quarter: headline numbers, margins, free cash flow and growth
-- against the same quarter a year earlier (the quarter ending 350-380 days before). Growth uses
-- |previous| as the base so a loss shrinking reads as positive. gross_profit falls back to
-- revenue - cost of revenue when no gross profit is tagged (gross_profit_computed).
-- `derived` = a headline value (revenue, net income or EPS) is derived from year-to-date totals.
CREATE OR REPLACE MACRO fundamentals_metrics_asof(as_of) AS TABLE
WITH p AS (
    SELECT ticker, period_end, mode(fiscal_year) AS fiscal_year, mode(fiscal_period) AS fiscal_period,
           max(value) FILTER (WHERE concept = 'revenue') AS revenue,
           max(value) FILTER (WHERE concept = 'gross_profit') AS gross_profit_reported,
           max(value) FILTER (WHERE concept = 'cost_of_revenue') AS cost_of_revenue,
           max(value) FILTER (WHERE concept = 'operating_income') AS operating_income,
           max(value) FILTER (WHERE concept = 'net_income') AS net_income,
           max(value) FILTER (WHERE concept = 'eps_diluted') AS eps_diluted,
           max(value) FILTER (WHERE concept = 'operating_cash_flow') AS operating_cash_flow,
           max(value) FILTER (WHERE concept = 'capex') AS capex,
           coalesce(bool_or(derived) FILTER (WHERE concept IN ('revenue', 'net_income', 'eps_diluted')), false) AS derived,
           list(DISTINCT concept ORDER BY concept) FILTER (WHERE derived) AS derived_concepts,
           max(filing_date) AS filing_date
    FROM fundamentals_quarterly_asof(as_of) GROUP BY ticker, period_end
), m AS (
    SELECT *, coalesce(gross_profit_reported, revenue - cost_of_revenue) AS gross_profit,
           gross_profit_reported IS NULL AND revenue IS NOT NULL AND cost_of_revenue IS NOT NULL AS gross_profit_computed,
           operating_cash_flow - capex AS fcf, period_end - 350 AS yoy_key
    FROM p
)
SELECT m.ticker, m.period_end, m.fiscal_year, m.fiscal_period, m.filing_date, m.revenue, m.gross_profit,
       m.gross_profit_computed, m.operating_income, m.net_income, m.eps_diluted, m.operating_cash_flow, m.capex, m.fcf,
       round(m.gross_profit / nullif(m.revenue, 0), 4) AS gross_margin,
       round(m.operating_income / nullif(m.revenue, 0), 4) AS operating_margin,
       round(m.net_income / nullif(m.revenue, 0), 4) AS net_margin,
       CASE WHEN m.period_end - y.period_end <= 380 THEN y.period_end END AS yoy_period_end,
       CASE WHEN m.period_end - y.period_end <= 380 THEN round((m.revenue - y.revenue) / nullif(abs(y.revenue), 0), 4) END AS revenue_yoy,
       CASE WHEN m.period_end - y.period_end <= 380 THEN round((m.net_income - y.net_income) / nullif(abs(y.net_income), 0), 4) END AS net_income_yoy,
       CASE WHEN m.period_end - y.period_end <= 380 THEN round((m.eps_diluted - y.eps_diluted) / nullif(abs(y.eps_diluted), 0), 4) END AS eps_yoy,
       CASE WHEN m.period_end - y.period_end <= 380 THEN round((m.operating_income - y.operating_income) / nullif(abs(y.operating_income), 0), 4) END AS operating_income_yoy,
       m.derived, m.derived_concepts
FROM m ASOF LEFT JOIN m AS y ON m.ticker = y.ticker AND m.yoy_key >= y.period_end;

CREATE OR REPLACE VIEW fundamentals_metrics AS
SELECT * FROM fundamentals_metrics_asof(TIMESTAMPTZ '9999-12-31 00:00:00+00');

-- Balance sheet per ticker and date: cash and total debt. Debt is tagged differently by each
-- company. total_debt adds up the parts found (debt_basis says which), NULL when none is tagged.
CREATE OR REPLACE VIEW fundamentals_balance AS
WITH b AS (
    SELECT ticker, period_end, mode(fiscal_year) AS fiscal_year, mode(fiscal_period) AS fiscal_period,
           max(value) FILTER (WHERE concept = 'cash') AS cash,
           max(value) FILTER (WHERE concept = 'debt_combined') AS debt_combined,
           max(value) FILTER (WHERE concept = 'debt_long_term_total') AS debt_long_term_total,
           max(value) FILTER (WHERE concept = 'debt_noncurrent') AS debt_noncurrent,
           max(value) FILTER (WHERE concept = 'debt_current') AS debt_current,
           max(value) FILTER (WHERE concept = 'long_term_debt_current') AS long_term_debt_current,
           max(value) FILTER (WHERE concept = 'short_term_borrowings') AS short_term_borrowings,
           max(filing_date) AS filing_date
    FROM fundamentals_latest WHERE period = 'instant' AND concept NOT LIKE 'shares%' GROUP BY ticker, period_end
)
SELECT *,
       CASE WHEN debt_combined IS NOT NULL THEN debt_combined
            WHEN debt_noncurrent IS NOT NULL THEN debt_noncurrent + coalesce(debt_current,
                 coalesce(long_term_debt_current, 0) + coalesce(short_term_borrowings, 0))
            WHEN debt_long_term_total IS NOT NULL THEN debt_long_term_total + coalesce(short_term_borrowings, 0)
       END AS total_debt,
       CASE WHEN debt_combined IS NOT NULL THEN 'combined'
            WHEN debt_noncurrent IS NOT NULL AND debt_current IS NOT NULL THEN 'noncurrent + current'
            WHEN debt_noncurrent IS NOT NULL THEN 'noncurrent + current LTD + short-term'
            WHEN debt_long_term_total IS NOT NULL THEN 'long-term incl. current + short-term'
       END AS debt_basis
FROM b;

-- Latest 10-Q/10-K per ticker that added values, with its own reporting period and filed
-- date (days_since_filed) so analysts know what is fresh.
CREATE OR REPLACE VIEW fundamentals_latest_report AS
WITH a AS (
    SELECT ticker, accession, any_value(form) AS form, min(filing_date) AS filing_date,
           max(accepted_at) AS accepted_at, max(period_end) FILTER (WHERE period <> 'instant') AS period_end
    FROM fundamentals GROUP BY ticker, accession
), lab AS (
    SELECT DISTINCT ON (ticker, accession) ticker, accession, fiscal_year, fiscal_period
    FROM fundamentals f
    WHERE period = CASE WHEN form LIKE '10-K%' THEN 'annual' ELSE 'quarter' END
    ORDER BY ticker, accession, period_end DESC
)
SELECT DISTINCT ON (a.ticker) a.ticker, a.form, a.accession, a.filing_date, a.accepted_at, a.period_end,
       lab.fiscal_year, lab.fiscal_period, current_date - a.filing_date AS days_since_filed
FROM a LEFT JOIN lab USING (ticker, accession)
ORDER BY a.ticker, a.filing_date DESC, a.period_end DESC NULLS LAST;

-- ---------- Free market-wide sources (issue #9; collect_macro, collect_shorts, collect_flows_india) ----------
-- Per series and date the complete row first, then the newest (a revision is a newer row),
-- plus two Treasury curve spreads from the same day's par yields (10y-2y, 10y-3m; source 'derived').
CREATE OR REPLACE VIEW macro_series AS
WITH m AS (SELECT DISTINCT ON (series, date) * FROM macro ORDER BY series, date, complete DESC NULLS LAST, first_seen_at DESC),
s AS (SELECT date, max(value) FILTER (WHERE series = 'UST_10Y') AS y10, max(value) FILTER (WHERE series = 'UST_2Y') AS y2,
             max(value) FILTER (WHERE series = 'UST_3M') AS m3, max(first_seen_at) AS first_seen_at
      FROM m WHERE source = 'treasury' GROUP BY date)
SELECT date, series, name, value, unit, source, first_seen_at FROM m
UNION ALL
SELECT date, 'UST_10Y_2Y', 'Treasury 10y minus 2y', round(y10 - y2, 4), 'pct', 'derived', first_seen_at
FROM s WHERE y10 IS NOT NULL AND y2 IS NOT NULL
UNION ALL
SELECT date, 'UST_10Y_3M', 'Treasury 10y minus 3m', round(y10 - m3, 4), 'pct', 'derived', first_seen_at
FROM s WHERE y10 IS NOT NULL AND m3 IS NOT NULL;

-- Latest value per series with its change versus 1 and 5 observations earlier (the series' own
-- previous dates, i.e. sessions for daily series); chg_* are in the series' unit.
CREATE OR REPLACE VIEW macro_latest AS
WITH r AS (SELECT *, row_number() OVER (PARTITION BY series ORDER BY date DESC) AS k FROM macro_series)
SELECT a.series, a.name, a.unit, a.source, a.date, a.value,
       a.value - b.value AS chg_1, b.date AS date_1, a.value - c.value AS chg_5, c.date AS date_5
FROM r a LEFT JOIN r b ON b.series = a.series AND b.k = 2
         LEFT JOIN r c ON c.series = a.series AND c.k = 6
WHERE a.k = 1;

-- FINRA daily short-sale volume: per session and ticker the complete row first, then the newest;
-- the latest session per ticker with the 5-session average and the average of the up to 20
-- sessions before it (n_prior = how many there were; short_pct in %).
CREATE OR REPLACE VIEW shorts_daily AS
SELECT DISTINCT ON (date, ticker) * FROM shorts ORDER BY date, ticker, complete DESC NULLS LAST, first_seen_at DESC;

CREATE OR REPLACE VIEW shorts_latest AS
WITH d AS (
    SELECT *, avg(short_pct) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS short_pct_5d,
           avg(short_pct) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS short_pct_prior_avg,
           count(*) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS n_prior
    FROM shorts_daily)
SELECT * FROM d QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1;

-- FINRA short interest: newest row per settlement and ticker; the latest settlement per ticker.
CREATE OR REPLACE VIEW short_interest_daily AS
SELECT DISTINCT ON (settlement_date, ticker) * FROM short_interest ORDER BY settlement_date, ticker, first_seen_at DESC;

CREATE OR REPLACE VIEW short_interest_latest AS
SELECT * FROM short_interest_daily QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY settlement_date DESC) = 1;

-- NSDL FPI investment: newest row per report, asset class and route; the latest report.
CREATE OR REPLACE VIEW fpi_daily AS
SELECT DISTINCT ON (reporting_date, asset_class, route) * FROM fpi
ORDER BY reporting_date, asset_class, route, first_seen_at DESC;

CREATE OR REPLACE VIEW fpi_latest AS
SELECT * FROM fpi_daily WHERE reporting_date = (SELECT max(reporting_date) FROM fpi_daily);

-- NSE index closes: per session and index the complete row first, then the newest; the latest
-- session per index with the return versus 1 and 5 stored sessions earlier (in %).
CREATE OR REPLACE VIEW indices_daily AS
SELECT DISTINCT ON (date, index_name) * FROM indices ORDER BY date, index_name, complete DESC NULLS LAST, first_seen_at DESC;

CREATE OR REPLACE VIEW indices_latest AS
WITH r AS (SELECT *, row_number() OVER (PARTITION BY index_name ORDER BY date DESC) AS k FROM indices_daily)
SELECT a.* EXCLUDE (k), (a.close / b.close - 1) * 100 AS ret_1_pct, b.date AS date_1,
       (a.close / c.close - 1) * 100 AS ret_5_pct, c.date AS date_5
FROM r a LEFT JOIN r b ON b.index_name = a.index_name AND b.k = 2
         LEFT JOIN r c ON c.index_name = a.index_name AND c.k = 6
WHERE a.k = 1;

-- News verification phase A (docs/DESIGN.md 3a). Articles fetched by a time (collect_articles.py
-- writes one row per news id; the latest fetch wins should a later version ever add one).
CREATE OR REPLACE MACRO news_articles_asof(ts) AS TABLE
SELECT DISTINCT ON (id) * FROM news_articles WHERE fetched_at <= ts ORDER BY id, fetched_at DESC;

-- Cluster state as of a time, without look-ahead: only rows computed by then (as_of <= ts) whose
-- inputs were all known by then (inputs_until <= ts: item first_seen_at, article fetched_at, filing
-- accepted_at, NSE dissemination time) and whose news ids were all first seen by then. Each news
-- id belongs to the newest such row that lists it (a cluster that merged into another, or
-- changed, is superseded); a cluster is that row.
CREATE OR REPLACE MACRO news_cluster_items_asof(ts) AS TABLE
WITH r AS (
    SELECT c.* FROM news_clusters c
    WHERE c.as_of <= ts AND coalesce(c.inputs_until, c.as_of) <= ts
      AND NOT EXISTS (SELECT 1 FROM news_stored n
                      WHERE list_contains(c.news_ids, n.id) AND n.first_seen_at > ts)
),
i AS (SELECT unnest(news_ids) AS news_id, id AS row_id, cluster_id, ticker, as_of FROM r)
SELECT DISTINCT ON (news_id, ticker) news_id, ticker, cluster_id, row_id, as_of
FROM i ORDER BY news_id, ticker, as_of DESC, row_id;

-- A cluster is its newest row still holding an item (above). Ids a newer row of another cluster
-- took over are removed from news_ids (and n_items) and listed in moved_ids; the other columns
-- (origins, counts, flags) stay as computed at that row's as_of. Ids can move only when a
-- cluster's earliest items left the builder's lookback (news_clusters.py), so this is rare.
-- Clusters that stopped changing keep their last row: they are history, not stale state.
CREATE OR REPLACE MACRO news_clusters_asof(ts) AS TABLE
WITH m AS (SELECT * FROM news_cluster_items_asof(ts)),
k AS (SELECT row_id, list(news_id) AS cur FROM m GROUP BY row_id),
r AS (SELECT c.*, k.cur FROM news_clusters c JOIN k ON k.row_id = c.id)
SELECT DISTINCT ON (cluster_id) * EXCLUDE (cur)
    REPLACE (list_filter(news_ids, x -> list_contains(cur, x)) AS news_ids,
             len(list_filter(news_ids, x -> list_contains(cur, x))) AS n_items),
    list_filter(news_ids, x -> NOT list_contains(cur, x)) AS moved_ids
FROM r ORDER BY cluster_id, as_of DESC;

CREATE OR REPLACE VIEW news_clusters_latest AS
SELECT * FROM news_clusters_asof(TIMESTAMPTZ '9999-12-31 00:00:00+00');
