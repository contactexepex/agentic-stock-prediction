# Notes: queries and inputs behind news.html

Built 2026-10-07 (UTC); repo read only. `python design/news/build.py --out <dir>` (a few seconds).

- Headlines: `news n left join enriched_latest e using(id)` ordered by published_at desc: id, title, url,
  source, source_domain, published_at, tickers, primary_tickers, feed, sentiment, materiality, event_type.
  Kept in the page: the newest 800 plus every high-materiality headline (`n_embedded` on the page; the rest
  stays in data/). India 1920 stored / 890 embedded, US 2911 / 813.
- Stories: `news_clusters_latest` ordered by n_items desc, joined to the latest `news_verified` pass
  (`level='cluster' and as_of = max(as_of)`): status, status_ids, independent_origins,
  unread_vetted_origins, origins, primary_ids, flags, first_reported_at, confirmed_at. A story without a
  verified row shows "not assessed" (US: 161 of 270, clusters the latest pass did not cover).
- Claims: `news_claims` ordered by extracted_at: claim_type, subject, predicate, stance, value_text, value_num,
  unit, period, quote, quote_field, source_kind, attribution, news_ids, source_published_at, attached to
  their cluster_id.
- Sources: `select source, count(*) from news group by 1 order by 2 desc limit 10`; access counts from
  `news_articles` grouped by access; span = min/max published_at of `news`.
- Events: `market_events(cfg, today, today + 56 days)` (config/events.yaml) plus `events` rows of type
  earnings or ex_dividend in the same window for watchlist tickers; a results day's reaction session =
  `next_session(cfg, date + 1)` when timing is after_close, else `next_session(cfg, date)`.
- Prices as of: `max(date) from ohlc` for the watchlist (6 Oct in both markets).
- Status counts on the page (India): confirmed_primary 1, single_source 12, unverified 31, rumour 4,
  promotional 3; (US): single_source 5, unverified 38, not assessed 161, promotional 65, rumour 1.
