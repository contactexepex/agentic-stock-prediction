"""Which clusters the claim-checker reads in a run, and the input record it gets for each (claims.py prepare)."""
from __future__ import annotations

import pandas as pd

from marketbrief.analytics.claim_rules import ClusterSources
from marketbrief.constants.verification import FIELD_EXTRACT, FIELD_PRIMARY, SOURCE_ARTICLE
from marketbrief.pipeline.claim_sources import cluster_ids, iso, item_rows

CHECKED_SQL = "SELECT DISTINCT cluster_row_id FROM news_claims WHERE extracted_at <= ?::TIMESTAMPTZ"
GROUP_KEYS = ("origin", "news_ids", "verified", "promotional", "opinion", "unread_vetted")


def select_clusters(con, clusters: list[dict], src, conf: dict, now: pd.Timestamp) -> tuple[list[dict], dict]:
    """The run's high-materiality clusters: highest `material_terms` weight of an item title >= min_priority,
    not yet checked at this cluster row, highest weight then newest first, at most max_clusters_per_run."""
    ids = sorted({i for c in clusters for i in c.get("news_ids") or []})
    titles = {k: v.get("title") or "" for k, v in item_rows(con, ids, now).items()}
    checked = {r[0] for r in con.execute(CHECKED_SQL, [now.isoformat()]).fetchall()}
    floor, cap = int(conf.get("min_priority", 3)), int(conf.get("max_clusters_per_run", 15))
    eligible, already = [], 0
    for c in clusters:
        weight = max((src.priority(titles.get(i, "")) for i in c.get("news_ids") or []), default=0)
        if weight < floor:
            continue
        if c["id"] in checked:
            already += 1
            continue
        eligible.append((weight, c))
    eligible.sort(key=lambda x: (-x[0], -pd.Timestamp(x[1]["last_reported_at"]).value, -int(x[1]["n_items"] or 0),
                                 x[1]["cluster_id"]))
    chosen = [c for _w, c in eligible[:cap]]
    return chosen, {"clusters_current": len(clusters), "eligible": len(eligible), "already_checked": already,
                    "over_cap": max(0, len(eligible) - cap)}


def input_records(con, cfg: dict, clusters: list[dict], sources: dict[str, ClusterSources], conf: dict,
                  now: pd.Timestamp) -> list[dict]:
    """One input record per selected cluster: the cluster's origins and flags, each item (title, outlet,
    article extract) and each primary source's stored text (cut to input_max_chars for reading; quotes
    are checked against the full stored text)."""
    per_doc, per_cluster = int(conf.get("input_max_chars", 12000)), int(conf.get("items_per_cluster", 20))
    items = item_rows(con, sorted({i for c in clusters for i in cluster_ids(c)}), now)
    out = []
    for c in clusters:
        found = sources[c["cluster_id"]]
        listed = []
        for nid in cluster_ids(c)[:per_cluster]:
            row, src = items.get(nid), found.sources.get(nid)
            if row is None or src is None or src.kind != SOURCE_ARTICLE:
                continue
            article = row.get("article") or {}
            listed.append({"id": nid, "title": row["title"], "source": row["source"],
                           "first_seen_at": iso(row["first_seen_at"]), "access": article.get("access"),
                           "domain": article.get("domain"),
                           "extract": src.fields.get(FIELD_EXTRACT)})
        primaries = [{"id": pid, "kind": found.sources[pid].kind, "available_at": found.sources[pid].available_at,
                      "text": found.sources[pid].fields[FIELD_PRIMARY][:per_doc]}
                     for pid in c.get("primary_ids") or [] if pid in found.sources]
        out.append({
            "cluster_id": c["cluster_id"], "cluster_row_id": c["id"], "ticker": c["ticker"],
            "company": cfg["tickers"].get(c["ticker"], {}).get("name", c["ticker"]),
            "first_reported_at": iso(c["first_reported_at"]), "last_reported_at": iso(c["last_reported_at"]),
            "independent_origins": c["independent_origins"], "unread_vetted_origins": c["unread_vetted_origins"],
            "flags": c.get("flags") or [],
            "origin_groups": [{k: g.get(k) for k in GROUP_KEYS} for g in c.get("origin_groups") or []],
            "items": listed, "primary_sources": primaries,
            "primary_without_text": [p for p in c.get("primary_ids") or [] if p not in found.sources],
        })
    return out
