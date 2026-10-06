#!/usr/bin/env python3
"""Project one market's data and results into Neo4j (docs/DESIGN.md section 12).

The repo's append-only files under data/ stay the source of truth. Neo4j is a derived copy that
`--full` rebuilds from them at any time, so nothing is lost if the database is emptied. The script
only reads data/ (through the DuckDB views in core.database.connect) and never writes there.

  neo4j_sync.py --market us              incremental: rows recorded since the last sync (minus a
                                         3-day overlap), per kind
  neo4j_sync.py --market us --full       delete this market's nodes in Neo4j, then load everything
  neo4j_sync.py --market us --dry-run    write the Cypher and parameter batches to
                                         work/neo4j_dryrun/<market>/ instead of sending them
  neo4j_sync.py --market us --probe      run `RETURN 1` and report the result

Connection (environment): NEO4J_URI (neo4j+s://<id>.databases.neo4j.io; only the host is used),
NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE (default: the first label of the URI host, which is
the database name on Aura, e.g. 4132bc90; `neo4j` for localhost or an IP address). Statements go
to the HTTPS Query API v2 (POST https://<host>/db/<database>/query/v2, basic auth), not Bolt. NEO4J_QUERY_URL replaces
the base URL derived from NEO4J_URI (e.g. http://127.0.0.1:7474 for a local server or a test).
The password and the URI are never printed; the summary names the host only.

Every statement is static Cypher: values travel only as parameters (`UNWIND $rows AS row`), and
every write is a MERGE on an id, so a re-run changes nothing. Each node and relationship carries
`market`, `source_kind` (the data kind), `source_id` (the record id in the JSONL line),
`recorded_at` (the record's own timestamp) and `synced_at`. Incremental watermarks are stored
in Neo4j itself as (:SyncState {id: '<market>:<kind>'}) nodes, so they survive a fresh container,
and advance only after every batch of a kind succeeded.

Prints one JSON summary (rows read, upserted and failed per kind). Exit 0 = all synced,
1 = any failure, 2 = NEO4J_URI not set (nothing sent)."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core import paths
from marketbrief.sources.neo4j_client import Neo4jClient, Neo4jError
from marketbrief.utils.text import slugify_with_unknown_fallback

BATCH_SIZE = 500
OVERLAP_DAYS = 3          # incremental re-reads this much before the watermark (re-upserts are harmless)
DELETE_BATCH = 5000
SCHEMA_VERSION = "neo4j-v1"
LABELS = ("Market", "Sector", "Company", "Holder", "Source", "Event", "Prediction", "Range", "Outcome",
          "RegimeDay", "FeatureDay", "Judgment", "FinancialPeriod", "FlowDay", "SyncState")
REL_ID_TYPES = ("TRADED", "HOLDS", "CONNECTED_TO")
INDEXES = [("Company", "ticker"), ("Company", "market"), ("Holder", "market"), ("Source", "market"),
           ("Event", "market"), ("Event", "date"), ("Prediction", "market"), ("Range", "market"),
           ("Outcome", "market"), ("SyncState", "market")]


# ---------- HTTP Query API (client: marketbrief/sources/neo4j_client.py) ----------

def default_database(uri: str | None) -> str:
    """NEO4J_DATABASE if set, else the first label of the URI host: on Aura the database is named
    after the instance id (neo4j+s://4132bc90.databases.neo4j.io -> 4132bc90), not `neo4j`.
    A host that is an IP address or localhost falls back to `neo4j`."""
    if os.environ.get("NEO4J_DATABASE"):
        return os.environ["NEO4J_DATABASE"]
    host = urllib.parse.urlparse(uri or "").hostname or ""
    if not host or host == "localhost" or re.fullmatch(r"[0-9.]+|[0-9a-f:]+", host) or "." not in host:
        return "neo4j"
    return host.split(".")[0]


def client_from_env() -> Neo4jClient | None:
    uri = os.environ.get("NEO4J_URI")
    base = os.environ.get("NEO4J_QUERY_URL")
    if not uri and not base:
        return None
    if not base:
        u = urllib.parse.urlparse(uri)
        secure = u.scheme.endswith("+s") or u.scheme.endswith("+ssc") or u.scheme == "https"
        port = f":{u.port}" if u.port and u.port != 7687 else ("" if secure else ":7474")
        base = f"{'https' if secure else 'http'}://{u.hostname}{port}"
    return Neo4jClient(base, default_database(uri or base),
                       (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")))


# ---------- values ----------

def clean(v):
    """A JSON- and Neo4j-safe value: dates as ISO strings, NaN as null, no nested maps."""
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v if x is not None]
    if isinstance(v, dict):
        return json.dumps(v, default=str, sort_keys=True)
    return v


# ---------- Cypher building blocks (static text only; values are parameters) ----------

def prov(v: str) -> str:
    return (f"{v}.market = $market, {v}.source_kind = $kind, {v}.source_id = row.source_id, "
            f"{v}.recorded_at = datetime(row.recorded_at), {v}.synced_at = datetime($synced_at)")


def casts(v: str, dates: tuple = (), datetimes: tuple = ()) -> str:
    """After `SET v += row.props`: turn ISO strings into Neo4j DATE / DATETIME values."""
    parts = [f"{v}.{f} = date(row.props.{f})" for f in dates]
    parts += [f"{v}.{f} = datetime(row.props.{f})" for f in datetimes]
    return "".join(", " + p for p in parts)


COMPANY = ("MERGE (c:Company {id: row.company_id}) ON CREATE SET c.market = $market, c.ticker = row.ticker, "
           "c.watchlist = false, c.source_kind = $kind, c.source_id = row.source_id, c.synced_at = datetime($synced_at)")
MARKET = "MERGE (m:Market {id: $market}) ON CREATE SET m.market = $market"


def holder_statement(rel: str, dates: tuple = (), datetimes: tuple = ()) -> str:
    return f"""UNWIND $rows AS row
MERGE (h:Holder {{id: row.holder_id}})
  ON CREATE SET h.name = row.holder_name, h.market = $market, h.source_kind = $kind, h.source_id = row.source_id,
                h.recorded_at = datetime(row.recorded_at)
SET h.synced_at = datetime($synced_at), h.cik = coalesce(row.holder_cik, h.cik), h.kind = coalesce(h.kind, row.holder_kind)
FOREACH (_ IN CASE WHEN row.holder_person THEN [1] ELSE [] END | SET h:Person)
WITH h, row
{COMPANY}
MERGE (h)-[r:{rel} {{id: row.id}}]->(c)
SET r += row.props{casts('r', dates, datetimes)}, {prov('r')}"""


def node_statement(label: str, dates: tuple = (), datetimes: tuple = (), extra_label: str | None = None) -> str:
    """MERGE (n:<label> {id}) SET n += props, typed dates and provenance (rows: id, props, source_id)."""
    lab = f", n:{extra_label}" if extra_label else ""
    return (f"MERGE (n:{label} {{id: row.id}})\nSET n += row.props{casts('n', dates, datetimes)}, "
            f"n.record_id = row.source_id, n.placeholder = false{lab}, {prov('n')}")


# ---------- kinds ----------

@dataclass
class Kind:
    name: str
    sql: str | None                       # rows come from DuckDB (must expose _ts) ...
    statements: list[tuple[str, Callable[[dict], bool] | None]]
    shape: Callable[[str, dict], dict]    # DuckDB row -> parameter row
    incremental: bool = True              # False: derived view, all rows every run
    rows_fn: Callable | None = None       # ... or from the market config


def base_row(market: str, r: dict, node_id: str, source_id, drop: tuple = ()) -> dict:
    props = {k: clean(v) for k, v in r.items() if k not in ("id", "_ts") + drop}
    return {"id": node_id, "source_id": str(source_id) if source_id is not None else None,
            "recorded_at": clean(r.get("_ts")), "props": props}


def company_id(market: str, ticker: str | None) -> str:
    return f"{market}:{ticker}"


# config: Market, Sector, Company
def config_rows(cfg: dict, _con, _since) -> list[dict]:
    m, src = cfg["market"], f"config/markets/{cfg['market']}.yaml"
    rows = [{"id": m, "source_id": src, "recorded_at": None, "node": "market",
             "props": {k: clean(cfg.get(k)) for k in ("name", "timezone", "currency", "calendar")}}]
    for t, meta in sorted(cfg["tickers"].items()):
        rows.append({"id": company_id(m, t), "ticker": t, "source_id": src, "recorded_at": None, "node": "company",
                     "sector_id": f"{m}:{meta['sector']}" if meta.get("sector") else None,
                     "sector": meta.get("sector"), "sector_etf": meta.get("sector_etf"),
                     "props": {"name": meta.get("name"), "yahoo": meta.get("yahoo"), "sector": meta.get("sector"),
                               "ticker": t, "watchlist": True}})
    return rows


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


def shape_news(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"], drop=("day",))
    row["props"]["outlet"] = row["props"].pop("source", None)
    row["tickers"], row["day"] = row["props"].get("tickers") or [], clean(r.get("day"))
    row["mentions"] = {k: row["props"].get(k) for k in ("sentiment", "relevance", "materiality", "event_type",
                                                         "novelty", "analyzed_at", "prompt_version")}
    return row


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


def shape_source(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row["ticker"], row["company_id"] = r.get("ticker"), company_id(m, r.get("ticker"))
    return row


def source_statement(label: str, dates: tuple, datetimes: tuple) -> str:
    return ("UNWIND $rows AS row\nMERGE (n:Source {id: row.id})\nSET n += row.props" + casts("n", dates, datetimes)
            + f", n:{label}, n.record_id = row.source_id, n.placeholder = false, " + prov("n")
            + "\nWITH n, row WHERE row.ticker IS NOT NULL\n" + COMPANY
            + "\nMERGE (c)-[r:FILED]->(n)\nSET " + prov("r"))


def shape_event(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row["ticker"], row["company_id"] = r.get("ticker"), company_id(m, r.get("ticker"))
    return row


EVENT_NODE = "UNWIND $rows AS row\n" + node_statement("Event", ("date",), ("first_seen_at",))
EVENT_STATEMENTS = [
    (EVENT_NODE + "\nWITH n, row\n" + COMPANY + "\nMERGE (c)-[r:HAS_EVENT]->(n)\nSET " + prov("r"),
     lambda r: r["ticker"] is not None),
    (EVENT_NODE + "\nWITH n, row\n" + MARKET + "\nMERGE (m)-[r:HAS_EVENT]->(n)\nSET " + prov("r"),
     lambda r: r["ticker"] is None),
]


def events_current_rows(cfg: dict, con, _since) -> list[dict]:
    ids = [r[0] for r in con.execute("SELECT id FROM company_events ORDER BY id").fetchall()]
    return [{"id": f"{cfg['market']}:events_current", "ids": ids, "source_id": "company_events", "recorded_at": None}]


# Market-wide events (no ticker) are always current; a company event is current when it is the
# latest known date for its (ticker, type) (view company_events), so a moved date flags the old one.
EVENTS_CURRENT = ("UNWIND $rows AS row\nMATCH (e:Event) WHERE e.market = $market\n"
                  "SET e.current = e.ticker IS NULL OR e.record_id IN row.ids")


PERSON_CATEGORIES = ("director", "key managerial", "kmp", "designated", "employee", "relative")


def holder_id(m: str, cik, name) -> str:
    return f"{m}:cik:{cik}" if cik else f"{m}:name:{slugify_with_unknown_fallback(name)}"


def shape_insider(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:insider:{r['id']}", r["id"], drop=("holder_name", "holder_cik"))
    cat = str(r.get("role") or "").lower()
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, r.get("holder_cik"), r.get("holder_name")), holder_name=r.get("holder_name"),
               holder_cik=r.get("holder_cik"), holder_kind="insider",
               holder_person=bool(r.get("is_director") or r.get("is_officer") or any(p in cat for p in PERSON_CATEGORIES)))
    row["props"]["via"] = "insider"
    return row


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


def shape_deal(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:deal:{r['id']}", r["id"])
    side = str(r.get("side") or "").lower()
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, None, r.get("client")), holder_name=r.get("client"), holder_cik=None,
               holder_kind="deal_client", holder_person=False)
    row["props"].update(via=str(r.get("deal_type") or "deal").lower(),
                        side="buy" if side.startswith("buy") else "sell" if side.startswith("sell") else side or None)
    return row


def shape_stake(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:stake:{r['id']}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, r.get("filer_cik"), r.get("filer_name")), holder_name=r.get("filer_name"),
               holder_cik=r.get("filer_cik"), holder_kind="stake_filer", holder_person=False)
    row["props"]["via"] = r.get("kind") or r.get("form")
    return row


HOLDINGS_13F_SQL = """
WITH h AS (
    SELECT DISTINCT ON (filer_cik, ticker, period) id, filer_cik, ticker, period, accession, url, first_seen_at
    FROM holdings WHERE put_call IS NULL AND ticker IS NOT NULL AND filer_cik IS NOT NULL
    ORDER BY filer_cik, ticker, period, filing_date DESC, first_seen_at
)
SELECT c.*, h.id, h.accession, h.url, h.first_seen_at AS _ts
FROM holdings_change c JOIN h USING (filer_cik, ticker, period)"""


def shape_13f(m: str, r: dict) -> dict:
    key = f"{r['filer_cik']}|{r['ticker']}|{clean(r['period'])}"
    row = base_row(m, r, f"{m}:13f:{key}", r["id"], drop=("filer_name",))
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               holder_id=holder_id(m, r["filer_cik"], r.get("filer_name")), holder_name=r.get("filer_name"),
               holder_cik=r["filer_cik"], holder_kind="13f_filer", holder_person=False)
    row["props"]["via"] = "13F"
    return row


SHAREHOLDING_SQL = """
WITH h AS (
    SELECT DISTINCT ON (ticker, period_end, source) * FROM holdings WHERE source IN ('nse_shp', 'nse_pledge')
    ORDER BY ticker, period_end, source, first_seen_at DESC, filed_at DESC NULLS LAST
), ids AS (
    SELECT ticker, period_end, list(id ORDER BY source) AS source_ids, max(first_seen_at) AS _ts FROM h GROUP BY ALL
)
SELECT q.*, ids.source_ids, ids._ts FROM pledge_changes q JOIN ids USING (ticker, period_end)"""


def shape_shareholding(m: str, r: dict) -> dict:
    key = f"{r['ticker']}|{clean(r['period_end'])}"
    row = base_row(m, r, f"{m}:shp:{key}", ",".join(r["source_ids"] or []))
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]), holder_id=f"{m}:promoters:{r['ticker']}",
               holder_name=f"Promoter group of {r['ticker']}", holder_cik=None, holder_kind="promoter_group",
               holder_person=False)
    row["props"].update(via="shareholding", period=row["props"].get("period_end"))
    return row


def shape_graph(m: str, r: dict) -> dict:
    row = base_row(m, r, r["id"], r["id"])
    row["id"] = f"{m}:graph:{r['id']}"
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]), status=r.get("status") or "active",
               target_ticker=r.get("target_ticker"),
               target_id=company_id(m, r["target_ticker"]) if r.get("target_ticker") else f"{m}:name:{slugify_with_unknown_fallback(r.get('target'))}",
               target_name=r.get("target"), target_person=r.get("target_kind") == "person")
    return row


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


def shape_prediction(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]),
               evidence=[{"id": f"{m}:{e}", "record_id": e} for e in (r.get("evidence_ids") or []) if e])
    return row


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


def shape_outcome(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:call:{r['prediction_id']}", r["prediction_id"])
    row["props"]["kind"] = "call"
    row["parent_id"], row["parent_record"] = f"{m}:{r['prediction_id']}", r["prediction_id"]
    return row


def scored_statement(parent: str, dates: tuple, rel_props: str) -> str:
    return f"""UNWIND $rows AS row
MERGE (p:{parent} {{id: row.parent_id}})
  ON CREATE SET p.market = $market, p.record_id = row.parent_record, p.placeholder = true, p.source_kind = $kind,
                p.source_id = row.source_id, p.synced_at = datetime($synced_at)
WITH p, row
{node_statement("Outcome", dates, ("scored_at",))}
MERGE (p)-[r:SCORED_AS]->(n)
SET {rel_props}{prov('r')}"""


def shape_range(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['id']}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]), prediction_id=f"{m}:{r['id']}")
    return row


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


def shape_range_outcome(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:range:{r['range_id']}", r["range_id"])
    row["props"]["kind"] = "range"
    row["parent_id"], row["parent_record"] = f"{m}:{r['range_id']}", r["range_id"]
    return row


def shape_market_day(key_fields: tuple) -> Callable[[str, dict], dict]:
    def shape(m: str, r: dict) -> dict:
        key = ":".join(str(clean(r.get(k))) for k in key_fields)
        return base_row(m, r, f"{m}:{key}", r.get("id") or key)
    return shape


def market_node_statement(label: str, rel: str, dates: tuple, datetimes: tuple) -> str:
    return ("UNWIND $rows AS row\n" + node_statement(label, dates, datetimes) + "\nWITH n, row\n" + MARKET
            + f"\nMERGE (m)-[r:{rel}]->(n)\nSET " + prov("r"))


def shape_feature(m: str, r: dict) -> dict:
    row = base_row(m, r, f"{m}:{r['ticker']}:{clean(r['as_of_date'])}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]))
    return row


def company_node_statement(label: str, rel: str, dates: tuple, datetimes: tuple) -> str:
    return ("UNWIND $rows AS row\n" + node_statement(label, dates, datetimes) + "\nWITH n, row\n" + COMPANY
            + f"\nMERGE (c)-[r:{rel}]->(n)\nSET " + prov("r"))


def shape_fundamentals(m: str, r: dict) -> dict:
    key = f"{r['ticker']}:sec:{clean(r['period_end'])}"
    row = base_row(m, r, f"{m}:{key}", f"fundamentals_metrics:{r['ticker']}:{clean(r['period_end'])}")
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]))
    row["props"]["basis"] = "sec_xbrl"
    return row


def shape_financials(m: str, r: dict) -> dict:
    key = f"{r['ticker']}:{r.get('basis')}:{clean(r.get('period_start'))}:{clean(r['period_end'])}"
    row = base_row(m, r, f"{m}:{key}", r["id"])
    row.update(ticker=r["ticker"], company_id=company_id(m, r["ticker"]))
    return row


KINDS: list[Kind] = [
    Kind("config", None, CONFIG_STATEMENTS, lambda m, r: r, incremental=False, rows_fn=config_rows),
    Kind("news", NEWS_SQL, [(NEWS_STATEMENT, None)], shape_news),
    Kind("filings", "SELECT DISTINCT ON (id) *, first_seen_at AS _ts FROM filings ORDER BY id, first_seen_at",
         [(source_statement("Filing", ("filing_date",), ("accepted_at", "first_seen_at")), None)], shape_source),
    Kind("announcements", "SELECT *, greatest(first_seen_at, analyzed_at) AS _ts FROM announcements_enriched",
         [(source_statement("Announcement", (), ("published_at", "first_seen_at", "analyzed_at")), None)], shape_source),
    Kind("events", "SELECT DISTINCT ON (id) *, first_seen_at AS _ts FROM events ORDER BY id, first_seen_at",
         EVENT_STATEMENTS, shape_event),
    Kind("events_current", None, [(EVENTS_CURRENT, None)], lambda m, r: r, incremental=False,
         rows_fn=events_current_rows),
    Kind("insiders", INSIDERS_SQL, [(holder_statement("TRADED", ("trade_date", "trade_to", "filing_date"),
                                                      ("disclosed_at", "first_seen_at")), None)], shape_insider),
    Kind("deals", "SELECT *, first_seen_at AS _ts FROM deals_scored",
         [(holder_statement("TRADED", ("date",), ("first_seen_at",)), None)], shape_deal),
    Kind("stakes", "SELECT *, first_seen_at AS _ts FROM stake_filings",
         [(holder_statement("HOLDS", ("filing_date", "event_date"), ("accepted_at", "first_seen_at")), None)],
         shape_stake),
    Kind("holdings_13f", HOLDINGS_13F_SQL,
         [(holder_statement("HOLDS", ("period", "prev_period"), ()), None)], shape_13f, incremental=False),
    Kind("shareholding", SHAREHOLDING_SQL,
         [(holder_statement("HOLDS", ("period", "period_end", "prev_period"), ("filed_at",)), None)],
         shape_shareholding, incremental=False),
    Kind("graph", "SELECT DISTINCT ON (id) *, added_at AS _ts FROM graph ORDER BY id, added_at DESC",
         GRAPH_STATEMENTS, shape_graph),
    Kind("predictions", "SELECT DISTINCT ON (id) *, made_at AS _ts FROM predictions ORDER BY id, made_at",
         [(PREDICTION_STATEMENT, None)], shape_prediction),
    Kind("outcomes", "SELECT DISTINCT ON (prediction_id) *, scored_at AS _ts FROM outcomes "
                     "ORDER BY prediction_id, scored_at",
         [(scored_statement("Prediction", ("base_date", "target_date"), "r.hit = row.props.hit, "), None)],
         shape_outcome),
    Kind("ranges", "SELECT *, made_at AS _ts FROM ranges_latest", [(RANGE_STATEMENT, None)], shape_range),
    Kind("range_outcomes", "SELECT DISTINCT ON (range_id) *, scored_at AS _ts FROM range_outcomes "
                           "ORDER BY range_id, scored_at",
         [(scored_statement("Range", ("target_date",), "r.hit50 = row.props.hit50, r.hit80 = row.props.hit80, "),
           None)], shape_range_outcome),
    Kind("regime", "SELECT *, computed_at AS _ts FROM regime_latest",
         [(market_node_statement("RegimeDay", "HAS_REGIME", ("as_of_date", "session_date"), ("computed_at",)), None)],
         shape_market_day(("as_of_date",))),
    Kind("features", "SELECT *, computed_at AS _ts FROM features_latest",
         [(company_node_statement("FeatureDay", "HAS_FEATURES", ("as_of_date", "ex_dividend_date"),
                                  ("computed_at",)), None)], shape_feature),
    Kind("judgments", "SELECT DISTINCT ON (id) *, recorded_at AS _ts FROM judgments ORDER BY id, recorded_at",
         [(market_node_statement("Judgment", "HAS_JUDGMENT", ("run_date",), ("recorded_at",)), None)],
         shape_market_day(("id",))),
    Kind("fundamentals", "SELECT *, CAST(filing_date AS TIMESTAMPTZ) AS _ts FROM fundamentals_metrics",
         [(company_node_statement("FinancialPeriod", "REPORTED", ("period_end", "filing_date", "yoy_period_end"), ()),
           None)], shape_fundamentals, incremental=False),
    Kind("financials", "SELECT *, first_seen_at AS _ts FROM financials_latest",
         [(company_node_statement("FinancialPeriod", "REPORTED", ("period_start", "period_end"),
                                  ("filed_at", "first_seen_at")), None)], shape_financials),
    Kind("flows", "SELECT *, first_seen_at AS _ts FROM flows_daily",
         [(market_node_statement("FlowDay", "HAS_FLOW", ("date",), ("first_seen_at",)), None)],
         shape_market_day(("date", "category"))),
]

NOT_PROJECTED = {
    "prices": "daily bars stay in DuckDB (FeatureDay nodes carry each day's close and indicators)",
    "price_sources": "provenance of bars filled from another source (view bar_sources), DuckDB only",
    "adjustments": "split/bonus factors applied on read to the bars (views ohlc, bars), DuckDB only",
    "quotes": "intraday snapshots, operational", "options": "implied-vol snapshots, operational",
    "calibration": "range-engine internals", "delivery": "per-session time series (context only)",
    "reviews": "nested JSON tables; the review report is in reports/", "graph_runs": "refresh bookkeeping",
    "news_enriched": "merged into NewsItem / Announcement and MENTIONS (latest analysis wins)",
    "news_articles": "article metadata, extracts and copy signatures (verification inputs), DuckDB only",
    "news_clusters": "per-run cluster snapshots read as of a time (news_clusters_asof), DuckDB only",
}


# ---------- sync ----------

def schema_statements() -> list[str]:
    out = [f"CREATE CONSTRAINT {lab.lower()}_id IF NOT EXISTS FOR (n:{lab}) REQUIRE n.id IS UNIQUE" for lab in LABELS]
    out += [f"CREATE INDEX {lab.lower()}_{prop} IF NOT EXISTS FOR (n:{lab}) ON (n.{prop})" for lab, prop in INDEXES]
    out += [f"CREATE INDEX {t.lower()}_id IF NOT EXISTS FOR ()-[r:{t}]-() ON (r.id)" for t in REL_ID_TYPES]
    return out


class DryRunSink:
    """Writes each statement and its parameters to work/neo4j_dryrun/<market>/NNNN-<name>.json."""

    def __init__(self, out_dir: Path):
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        self.dir, self.n = out_dir, 0

    def run(self, statement: str, parameters: dict | None = None, name: str = "statement") -> dict:
        self.n += 1
        path = self.dir / f"{self.n:04d}-{name}.json"
        path.write_text(json.dumps({"statement": statement, "parameters": parameters or {}}, indent=1,
                                   ensure_ascii=False))
        return {"data": {"fields": [], "values": []}, "counters": {}}


def read_rows(kind: Kind, cfg: dict, con, since: str | None) -> list[dict]:
    m = cfg["market"]
    if kind.rows_fn:
        return kind.rows_fn(cfg, con, since)
    sql, params = f"SELECT * FROM ({kind.sql}) q", []
    if kind.incremental and since:
        sql += f" WHERE q._ts IS NULL OR q._ts >= CAST(? AS TIMESTAMPTZ) - INTERVAL {OVERLAP_DAYS} DAY"
        params = [since]
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [kind.shape(m, dict(zip(cols, r))) for r in cur.fetchall()]
    return sorted(rows, key=lambda r: (str(r["id"]), str(r.get("source_id"))))


def watermarks(client, market: str) -> dict[str, str]:
    res = client.run("MATCH (s:SyncState) WHERE s.market = $market AND s.kind IS NOT NULL "
                     "RETURN s.kind AS kind, s.watermark AS watermark", {"market": market})
    data = res.get("data") or {}
    return {k: w for k, w in (data.get("values") or []) if w}


def add_counters(total: dict, res: dict) -> None:
    for k, v in (res.get("counters") or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total[k] = total.get(k, 0) + v


def run_stmt(sink, statement: str, params: dict, name: str) -> dict:
    return sink.run(statement, params, name=name) if isinstance(sink, DryRunSink) else sink.run(statement, params)


def ensure_schema(sink) -> None:
    if not isinstance(sink, DryRunSink):
        res = sink.run("MATCH (s:SyncState {id: $id}) RETURN s.version AS version", {"id": "_schema"})
        values = (res.get("data") or {}).get("values") or []
        if values and values[0] and values[0][0] == SCHEMA_VERSION:
            return
    for stmt in schema_statements():
        run_stmt(sink, stmt, {}, "schema")
    run_stmt(sink, "MERGE (s:SyncState {id: $id}) SET s.version = $version", {"id": "_schema", "version": SCHEMA_VERSION},
             "schema")


def delete_market(sink, market: str) -> int:
    stmt = ("MATCH (n) WHERE n.market = $market WITH n LIMIT $limit DETACH DELETE n RETURN count(*) AS deleted")
    total = 0
    while True:
        res = run_stmt(sink, stmt, {"market": market, "limit": DELETE_BATCH}, "full-delete")
        values = (res.get("data") or {}).get("values") or []
        n = int(values[0][0]) if values and values[0] else 0
        total += n
        if n < DELETE_BATCH:
            return total


def sync(cfg: dict, con, sink, full: bool = False, since: str | None = None, batch_size: int = BATCH_SIZE,
         only: list[str] | None = None) -> dict:
    market, synced_at = cfg["market"], utc_now()
    dry = isinstance(sink, DryRunSink)
    out = {"step": "neo4j_sync", "market": market, "mode": "full" if full else "incremental", "dry_run": dry,
           "host": None if dry else sink.host,
           "database": None if dry else sink.database, "synced_at": synced_at, "kinds": {}, "counters": {}}
    try:
        ensure_schema(sink)
        if full:
            out["deleted_nodes"] = delete_market(sink, market)
        marks = {} if (full or dry) else watermarks(sink, market)
    except Neo4jError as exc:
        out.update(ok=False, error=str(exc))
        return out
    for kind in KINDS:
        if only and kind.name not in only:
            continue
        start = None if full else (since or marks.get(kind.name))
        rec = {"rows_read": 0, "upserted": 0, "failed": 0}
        if kind.incremental and start:
            rec["since"] = start
        try:
            rows = read_rows(kind, cfg, con, start if kind.incremental else None)
        except Exception as exc:  # a view that cannot be read fails this kind only
            rec.update(error=f"read: {exc}"[:300])
            rec["failed"] = 1
            out["kinds"][kind.name] = rec
            continue
        rec["rows_read"] = len(rows)
        errors = []
        for i in range(0, len(rows), batch_size):
            batch, ok = rows[i:i + batch_size], True
            for j, (stmt, keep) in enumerate(kind.statements):
                part = [r for r in batch if keep is None or keep(r)]
                if not part:
                    continue
                params = {"market": market, "kind": kind.name, "synced_at": synced_at, "rows": part}
                try:
                    add_counters(out["counters"], run_stmt(sink, stmt, params, f"{kind.name}-{j}-b{i // batch_size}"))
                except Neo4jError as exc:
                    ok = False
                    errors.append(str(exc))
            rec["upserted" if ok else "failed"] += len(batch)
        if errors:
            rec["error"] = errors[0][:300]
        elif kind.incremental and rows and not dry:
            marks_ts = [r["recorded_at"] for r in rows if r.get("recorded_at")]
            if marks_ts:
                wm = max(marks_ts, key=lambda s: datetime.fromisoformat(s))
                try:
                    sink.run("MERGE (s:SyncState {id: $id}) SET s.market = $market, s.kind = $kind, "
                             "s.watermark = $watermark, s.rows = $n, s.synced_at = datetime($synced_at)",
                             {"id": f"{market}:{kind.name}", "market": market, "kind": kind.name, "watermark": wm,
                              "n": len(rows), "synced_at": synced_at})
                    rec["watermark"] = wm
                except Neo4jError as exc:
                    rec["error"] = f"watermark: {exc}"[:300]
                    rec["failed"] += 1
        out["kinds"][kind.name] = rec
    out["ok"] = all(not k["failed"] for k in out["kinds"].values())
    return out


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--full", action="store_true", help="delete this market's projection and load everything")
    ap.add_argument("--dry-run", action="store_true", help="write statements to work/neo4j_dryrun/ instead")
    ap.add_argument("--probe", action="store_true", help="only run RETURN 1 against the server")
    ap.add_argument("--since", help="ISO timestamp: override the stored watermark of every incremental kind")
    ap.add_argument("--kinds", help="comma-separated subset of kinds (default: all)")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = ap.parse_args()
    cfg = require_market(args)
    if args.dry_run:
        sink = DryRunSink(paths.ROOT / "work" / "neo4j_dryrun" / cfg["market"])
    else:
        sink = client_from_env()
        if sink is None:
            print(json.dumps({"step": "neo4j_sync", "market": cfg["market"], "ok": False, "skipped": True,
                              "reason": "NEO4J_URI not set"}))
            return 2
    if args.probe:
        if isinstance(sink, DryRunSink):
            raise SystemExit("--probe needs a server, not --dry-run")
        try:
            res = sink.run("RETURN 1 AS ok")
            print(json.dumps({"step": "neo4j_probe", "host": sink.host, "database": sink.database, "ok": True,
                              "result": (res.get("data") or {}).get("values")}))
            return 0
        except Neo4jError as exc:
            print(json.dumps({"step": "neo4j_probe", "host": sink.host, "database": sink.database, "ok": False, "error": str(exc)}))
            return 1
    con = connect(cfg["market"])
    only = [k.strip() for k in args.kinds.split(",")] if args.kinds else None
    out = sync(cfg, con, sink, full=args.full, since=args.since, batch_size=args.batch_size, only=only)
    if args.dry_run:
        out["dry_run_dir"] = str(sink.dir.relative_to(paths.ROOT)) if sink.dir.is_relative_to(paths.ROOT) else str(sink.dir)
        out["statements"] = sink.n
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
