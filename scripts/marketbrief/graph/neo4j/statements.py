"""The Cypher statements and read queries of each projected kind."""
from __future__ import annotations

from marketbrief.graph.neo4j.cypher import COMPANY, MARKET, casts, node_statement, prov


CONFIG_STATEMENTS = [
    ("UNWIND $rows AS row\nMERGE (m:Market {id: row.id})\nSET m += row.props, " + prov("m"),
     lambda r: r["node"] == "market"),
    ("""UNWIND $rows AS row
MERGE (m:Market {id: $market})
MERGE (c:Company {id: row.id})
SET c += row.props, """ + prov("c") + """
MERGE (c)-[l:LISTED_ON]->(m) SET """ + prov("l") + """
WITH c, m, row WHERE row.sector_id IS NOT NULL
MERGE (s:Sector {id: row.sector_id})
SET s.name = row.sector, s.sector_etf = row.sector_etf, """ + prov("s") + """
MERGE (s)-[im:IN_MARKET]->(m) SET """ + prov("im") + """
MERGE (c)-[r:IN_SECTOR]->(s) SET """ + prov("r"), lambda r: r["node"] == "company"),
]

NEWS_SQL = """
SELECT n.*, e.analyzed_at, e.relevance, e.sentiment, e.novelty, e.materiality, e.event_type, e.urgency,
       e.geopolitical, e.priced_in, e.summary, e.prompt_version,
       CAST(coalesce(n.published_at, n.first_seen_at) AS DATE) AS day,
       greatest(n.first_seen_at, e.analyzed_at) AS _ts
FROM (SELECT DISTINCT ON (id) * FROM news ORDER BY id, first_seen_at) n LEFT JOIN enriched_latest e USING (id)"""

NEWS_STATEMENT = """UNWIND $rows AS row
MERGE (n:Source {id: row.id})
SET n += row.props""" + casts("n", (), ("published_at", "first_seen_at", "analyzed_at")) + """, n:NewsItem,
    n.record_id = row.source_id, n.placeholder = false, """ + prov("n") + """
WITH n, row
UNWIND row.tickers AS t
MERGE (c:Company {id: $market + ':' + t})
  ON CREATE SET c.market = $market, c.ticker = t, c.watchlist = false, c.source_kind = $kind,
                c.source_id = row.source_id, c.synced_at = datetime($synced_at)
MERGE (n)-[r:MENTIONS]->(c)
SET r += row.mentions, r.analyzed_at = datetime(row.mentions.analyzed_at), r.day = date(row.day), """ + prov("r")

EVENT_NODE = "UNWIND $rows AS row\n" + node_statement("Event", ("date",), ("first_seen_at",))

EVENT_STATEMENTS = [
    (EVENT_NODE + "\nWITH n, row\n" + COMPANY + "\nMERGE (c)-[r:HAS_EVENT]->(n)\nSET " + prov("r"),
     lambda r: r["ticker"] is not None),
    (EVENT_NODE + "\nWITH n, row\n" + MARKET + "\nMERGE (m)-[r:HAS_EVENT]->(n)\nSET " + prov("r"),
     lambda r: r["ticker"] is None),
]

# Market-wide events (no ticker) are always current; a company event is current when it is the
# latest known date for its (ticker, type) (view company_events), so a moved date flags the old one.
EVENTS_CURRENT = ("UNWIND $rows AS row\nMATCH (e:Event) WHERE e.market = $market\n"
                  "SET e.current = e.ticker IS NULL OR e.record_id IN row.ids")

INSIDERS_SQL = """
SELECT id, ticker, coalesce(insider_name, person) AS holder_name, insider_cik AS holder_cik,
       coalesce(role, person_category) AS role, is_director, is_officer, is_ten_pct_owner,
       coalesce(source, CASE WHEN accession IS NOT NULL THEN 'sec_form4' END) AS source, form, accession,
       code, acquired_disposed, "transaction" AS transaction, mode, security, security_type, derivative,
       shares, price, value, shares_after, holding_before_pct, holding_after_pct, plan_10b5_1, ownership,
       coalesce(transaction_date, trade_from) AS trade_date, trade_to,
       coalesce(accepted_at, disclosed_at) AS disclosed_at, filing_date, url, first_seen_at,
       CASE WHEN code = 'P' THEN 'buy' WHEN code = 'S' THEN 'sell'
            WHEN regexp_matches(lower(coalesce("transaction", '')), '^(buy|acqui|purchase)') THEN 'buy'
            WHEN regexp_matches(lower(coalesce("transaction", '')), '^(sell|sale|dispos)') THEN 'sell' END AS side,
       first_seen_at AS _ts
FROM insider_trades WHERE ticker IS NOT NULL"""

HOLDINGS_13F_SQL = """
WITH h AS (
    SELECT DISTINCT ON (filer_cik, ticker, period) id, filer_cik, ticker, period, accession, url, first_seen_at
    FROM holdings WHERE put_call IS NULL AND ticker IS NOT NULL AND filer_cik IS NOT NULL
    ORDER BY filer_cik, ticker, period, filing_date DESC, first_seen_at
)
SELECT c.*, h.id, h.accession, h.url, h.first_seen_at AS _ts
FROM holdings_change c JOIN h USING (filer_cik, ticker, period)"""

SHAREHOLDING_SQL = """
WITH h AS (
    SELECT DISTINCT ON (ticker, period_end, source) * FROM holdings WHERE source IN ('nse_shp', 'nse_pledge')
    ORDER BY ticker, period_end, source, first_seen_at DESC, filed_at DESC NULLS LAST
), ids AS (
    SELECT ticker, period_end, list(id ORDER BY source) AS source_ids, max(first_seen_at) AS _ts FROM h GROUP BY ALL
)
SELECT q.*, ids.source_ids, ids._ts FROM pledge_changes q JOIN ids USING (ticker, period_end)"""

# An edge whose target moved (e.g. a target_ticker added later) loses its old relationship first.
GRAPH_DROP = ("UNWIND $rows AS row\nOPTIONAL MATCH ()-[old:CONNECTED_TO {id: row.id}]->(t0) WHERE t0.id <> row.target_id\n"
              "DELETE old\nWITH DISTINCT row\n")

GRAPH_REL = ("MERGE (c)-[r:CONNECTED_TO {id: row.id}]->(t)\nSET r += row.props"
             + casts("r", ("as_of",), ("added_at",)) + ", " + prov("r"))

GRAPH_STATEMENTS = [
    (GRAPH_DROP + COMPANY + """
WITH c, row
MERGE (t:Company {id: row.target_id}) ON CREATE SET t.market = $market, t.ticker = row.target_ticker, t.name = row.target_name,
      t.watchlist = false, t.source_kind = $kind, t.source_id = row.source_id, t.synced_at = datetime($synced_at)
""" + GRAPH_REL, lambda r: r["status"] == "active" and r["target_ticker"]),
    (GRAPH_DROP + COMPANY + """
WITH c, row
MERGE (t:Holder {id: row.target_id}) ON CREATE SET t.market = $market, t.name = row.target_name, t.kind = 'graph_target',
      t.source_kind = $kind, t.source_id = row.source_id, t.recorded_at = datetime(row.recorded_at)
SET t.synced_at = datetime($synced_at)
FOREACH (_ IN CASE WHEN row.target_person THEN [1] ELSE [] END | SET t:Person)
""" + GRAPH_REL, lambda r: r["status"] == "active" and not r["target_ticker"]),
    ("UNWIND $rows AS row\nOPTIONAL MATCH ()-[old:CONNECTED_TO {id: row.id}]->()\nDELETE old",
     lambda r: r["status"] != "active"),
]

PREDICTION_STATEMENT = "UNWIND $rows AS row\n" + node_statement("Prediction", ("as_of_date",), ("made_at",)) + """
WITH n, row
""" + COMPANY + """
MERGE (n)-[r:PREDICTS]->(c)
SET r.direction = row.props.direction, r.confidence = row.props.confidence, r.horizon_days = row.props.horizon_days,
    r.as_of_date = date(row.props.as_of_date), """ + prov("r") + """
WITH n, row
UNWIND row.evidence AS ev
MERGE (s:Source {id: ev.id})
  ON CREATE SET s.market = $market, s.record_id = ev.record_id, s.placeholder = true, s.source_kind = $kind,
                s.source_id = row.source_id, s.synced_at = datetime($synced_at)
MERGE (n)-[ci:CITES]->(s)
SET """ + prov("ci")

RANGE_STATEMENT = "UNWIND $rows AS row\n" + node_statement(
    "Range", ("as_of_date", "session_date", "target_date"), ("made_at",)) + """
WITH n, row
""" + COMPANY + """
MERGE (n)-[r:RANGE_FOR]->(c)
SET r.horizon_days = row.props.horizon_days, r.target_date = date(row.props.target_date), """ + prov("r") + """
WITH n, row
OPTIONAL MATCH (p:Prediction {id: row.prediction_id})
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
  MERGE (p)-[h:HAS_RANGE]->(n)
  SET """ + prov("h") + ")"
