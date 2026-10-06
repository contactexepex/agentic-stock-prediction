"""Cypher building blocks: static statement text (values are always parameters)."""

from __future__ import annotations


def prov(variable: str) -> str:
    return (
        f"{variable}.market = $market, {variable}.source_kind = $kind, {variable}.source_id = row.source_id, "
        f"{variable}.recorded_at = datetime(row.recorded_at), {variable}.synced_at = datetime($synced_at)"
    )


def casts(variable: str, dates: tuple = (), datetimes: tuple = ()) -> str:
    """After `SET v += row.props`: turn ISO strings into Neo4j DATE / DATETIME values."""
    parts = [f"{variable}.{field} = date(row.props.{field})" for field in dates]
    parts += [f"{variable}.{field} = datetime(row.props.{field})" for field in datetimes]
    return "".join(", " + part for part in parts)


COMPANY = (
    "MERGE (c:Company {id: row.company_id}) ON CREATE SET c.market = $market, c.ticker = row.ticker, "
    "c.watchlist = false, c.source_kind = $kind, c.source_id = row.source_id, c.synced_at = datetime($synced_at)"
)

MARKET = "MERGE (m:Market {id: $market}) ON CREATE SET m.market = $market"


def holder_statement(rel: str, dates: tuple = (), datetimes: tuple = ()) -> str:
    return f"""UNWIND $rows AS row
MERGE (h:Holder {{id: row.holder_id}})
  ON CREATE SET h.name = row.holder_name, h.market = $market, h.source_kind = $kind, h.source_id = row.source_id,
                h.recorded_at = datetime(row.recorded_at)
SET h.synced_at = datetime($synced_at), h.cik = coalesce(row.holder_cik, h.cik), h.kind = coalesce(h.kind, \
row.holder_kind)
FOREACH (_ IN CASE WHEN row.holder_person THEN [1] ELSE [] END | SET h:Person)
WITH h, row
{COMPANY}
MERGE (h)-[r:{rel} {{id: row.id}}]->(c)
SET r += row.props{casts("r", dates, datetimes)}, {prov("r")}"""


def node_statement(label: str, dates: tuple = (), datetimes: tuple = (), extra_label: str | None = None) -> str:
    """MERGE (n:<label> {id}) SET n += props, typed dates and provenance (rows: id, props, source_id)."""
    lab = f", n:{extra_label}" if extra_label else ""
    return (
        f"MERGE (n:{label} {{id: row.id}})\nSET n += row.props{casts('n', dates, datetimes)}, "
        f"n.record_id = row.source_id, n.placeholder = false{lab}, {prov('n')}"
    )


def scored_statement(parent: str, dates: tuple, rel_props: str) -> str:
    return f"""UNWIND $rows AS row
MERGE (p:{parent} {{id: row.parent_id}})
  ON CREATE SET p.market = $market, p.record_id = row.parent_record, p.placeholder = true, p.source_kind = $kind,
                p.source_id = row.source_id, p.synced_at = datetime($synced_at)
WITH p, row
{node_statement("Outcome", dates, ("scored_at",))}
MERGE (p)-[r:SCORED_AS]->(n)
SET {rel_props}{prov("r")}"""


def source_statement(label: str, dates: tuple, datetimes: tuple) -> str:
    return (
        "UNWIND $rows AS row\nMERGE (n:Source {id: row.id})\nSET n += row.props"
        + casts("n", dates, datetimes)
        + f", n:{label}, n.record_id = row.source_id, n.placeholder = false, "
        + prov("n")
        + "\nWITH n, row WHERE row.ticker IS NOT NULL\n"
        + COMPANY
        + "\nMERGE (c)-[r:FILED]->(n)\nSET "
        + prov("r")
    )


def market_node_statement(label: str, rel: str, dates: tuple, datetimes: tuple) -> str:
    return (
        "UNWIND $rows AS row\n"
        + node_statement(label, dates, datetimes)
        + "\nWITH n, row\n"
        + MARKET
        + f"\nMERGE (m)-[r:{rel}]->(n)\nSET "
        + prov("r")
    )


def company_node_statement(label: str, rel: str, dates: tuple, datetimes: tuple) -> str:
    return (
        "UNWIND $rows AS row\n"
        + node_statement(label, dates, datetimes)
        + "\nWITH n, row\n"
        + COMPANY
        + f"\nMERGE (c)-[r:{rel}]->(n)\nSET "
        + prov("r")
    )
