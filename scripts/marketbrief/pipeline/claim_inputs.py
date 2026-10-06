"""Which clusters the claim-checker reads in a run, and the input record it gets for each (claims.py prepare)."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics.claim_rules import ClusterSources
from marketbrief.constants.verification import FIELD_EXTRACT, FIELD_PRIMARY, SOURCE_ARTICLE
from marketbrief.pipeline.claim_sources import cluster_ids, iso, item_rows

CHECKED_SQL = "SELECT DISTINCT cluster_row_id FROM news_claims WHERE extracted_at <= ?::TIMESTAMPTZ"
STORED_SQL = """
SELECT cluster_id, fact_key, quote_source_id FROM news_claims
WHERE list_contains(?, cluster_id) AND extracted_at <= ?::TIMESTAMPTZ ORDER BY cluster_id, fact_key, quote_source_id"""
GROUP_KEYS = ("origin", "news_ids", "verified", "promotional", "opinion", "unread_vetted")


def select_clusters(con, clusters: list[dict], src, conf: dict, now: pd.Timestamp) -> tuple[list[dict], dict]:
    """The run's high-materiality clusters: highest `material_terms` weight of an item title >= min_priority,
    not yet checked at this cluster row, highest weight then newest first, at most max_clusters_per_run."""
    ids = sorted({cluster_news_id for cluster in clusters for cluster_news_id in cluster.get("news_ids") or []})
    titles = {news_id: item.get("title") or "" for news_id, item in item_rows(con, ids, now).items()}
    checked = {checked_row[0] for checked_row in con.execute(CHECKED_SQL, [now.isoformat()]).fetchall()}
    floor, cap = int(conf.get("min_priority", 3)), int(conf.get("max_clusters_per_run", 15))
    eligible, already = [], 0
    for cluster in clusters:
        weight = max(
            (src.priority(titles.get(cluster_news_id, "")) for cluster_news_id in cluster.get("news_ids") or []),
            default=0,
        )
        if weight < floor:
            continue
        if cluster["id"] in checked:
            already += 1
            continue
        eligible.append((weight, cluster))
    eligible.sort(
        key=lambda entry: (
            -entry[0],
            -pd.Timestamp(entry[1]["last_reported_at"]).value,
            -int(entry[1]["n_items"] or 0),
            entry[1]["cluster_id"],
        )
    )
    chosen = [cluster for _weight, cluster in eligible[:cap]]
    return chosen, {
        "clusters_current": len(clusters),
        "eligible": len(eligible),
        "already_checked": already,
        "over_cap": max(0, len(eligible) - cap),
    }


def input_records(
    con, cfg: dict, clusters: list[dict], sources: dict[str, ClusterSources], conf: dict, now: pd.Timestamp
) -> list[dict]:
    """One input record per selected cluster: the cluster's origins and flags, each item (title, outlet,
    article extract), each primary source's stored text (cut to input_max_chars for reading; quotes
    are checked against the full stored text) and the statements already stored for the cluster."""
    per_doc, per_cluster = int(conf.get("input_max_chars", 12000)), int(conf.get("items_per_cluster", 20))
    items = item_rows(con, sorted({news_id for cluster in clusters for news_id in cluster_ids(cluster)}), now)
    stored: dict[str, list[dict]] = {}
    for cluster_id, fact_key, source_id in con.execute(
        STORED_SQL, [[cluster["cluster_id"] for cluster in clusters], now.isoformat()]
    ).fetchall():
        stored.setdefault(cluster_id, []).append({"fact_key": fact_key, "quote_source_id": source_id})
    out = []
    for cluster in clusters:
        found = sources[cluster["cluster_id"]]
        listed = []
        for nid in cluster_ids(cluster)[:per_cluster]:
            row, src = items.get(nid), found.sources.get(nid)
            if row is None or src is None or src.kind != SOURCE_ARTICLE:
                continue
            article = row.get("article") or {}
            listed.append(
                {
                    "id": nid,
                    "title": row["title"],
                    "source": row["source"],
                    "first_seen_at": iso(row["first_seen_at"]),
                    "access": article.get("access"),
                    "domain": article.get("domain"),
                    "extract": src.fields.get(FIELD_EXTRACT),
                }
            )
        primaries = [
            {
                "id": pid,
                "kind": found.sources[pid].kind,
                "available_at": found.sources[pid].available_at,
                "text": found.sources[pid].fields[FIELD_PRIMARY][:per_doc],
            }
            for pid in cluster.get("primary_ids") or []
            if pid in found.sources
        ]
        out.append(
            {
                "cluster_id": cluster["cluster_id"],
                "cluster_row_id": cluster["id"],
                "ticker": cluster["ticker"],
                "company": cfg["tickers"].get(cluster["ticker"], {}).get("name", cluster["ticker"]),
                "first_reported_at": iso(cluster["first_reported_at"]),
                "last_reported_at": iso(cluster["last_reported_at"]),
                "independent_origins": cluster["independent_origins"],
                "unread_vetted_origins": cluster["unread_vetted_origins"],
                "flags": cluster.get("flags") or [],
                "origin_groups": [
                    {key: origin_group.get(key) for key in GROUP_KEYS}
                    for origin_group in cluster.get("origin_groups") or []
                ],
                "items": listed,
                "primary_sources": primaries,
                "primary_without_text": [
                    primary_id for primary_id in cluster.get("primary_ids") or [] if primary_id not in found.sources
                ],
                "stored_claims": stored.get(cluster["cluster_id"], []),
            }
        )
    return out
