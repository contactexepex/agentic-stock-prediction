"""What the claim-checker may read and cite, loaded from data/ as of a time: current clusters, the
stored text of their items (title, article extract) and of their primary sources (SEC filing text in
primary_texts, NSE announcement subjects). Only rows available by that time are used."""
from __future__ import annotations

import json

import pandas as pd

from marketbrief.analytics.claim_rules import ClusterSources, SourceText
from marketbrief.constants.verification import (FIELD_EXTRACT, FIELD_PRIMARY, FIELD_TITLE, SOURCE_ANNOUNCEMENT,
                                                SOURCE_ARTICLE, SOURCE_FILING)
from marketbrief.utils.timefmt import as_utc_timestamp

READ_ACCESS = ("full", "partial", "paywalled")
CLUSTERS_SQL = """
SELECT * FROM news_clusters_asof(?::TIMESTAMPTZ)
WHERE last_reported_at >= ?::TIMESTAMPTZ ORDER BY cluster_id"""
ITEMS_SQL = """
SELECT DISTINCT ON (id) id, title, source, first_seen_at, coalesce(published_at, first_seen_at) AS published_at
FROM news
WHERE list_contains(?, id) AND first_seen_at <= ?::TIMESTAMPTZ ORDER BY id, first_seen_at"""
ARTICLES_SQL = """
SELECT id, access, domain, extract, fetched_at FROM news_articles_asof(?::TIMESTAMPTZ)
WHERE list_contains(?, id) ORDER BY id"""
TEXTS_SQL = """
SELECT DISTINCT ON (id) id, primary_id, form, doc, text, available_at, fetched_at FROM primary_texts
WHERE list_contains(?, primary_id) AND fetched_at <= ?::TIMESTAMPTZ AND available_at <= ?::TIMESTAMPTZ
ORDER BY id, fetched_at"""
ANNOUNCEMENTS_SQL = """
SELECT id, category, subject, coalesce(published_at, first_seen_at) AS available_at FROM announcements_latest
WHERE list_contains(?, id) AND coalesce(published_at, first_seen_at) <= ?::TIMESTAMPTZ ORDER BY id"""


def iso(value) -> str | None:
    """A timestamp as ISO 8601 UTC text (seconds), or None."""
    stamp = as_utc_timestamp(value)
    return None if stamp is None else stamp.floor("s").isoformat()


def clean_row(row: dict) -> dict:
    """A DuckDB row as plain values: NaN/NaT as None, JSON columns parsed, arrays as lists."""
    out = {}
    for key, value in row.items():
        if isinstance(value, float) and pd.isna(value):
            value = None
        elif value is pd.NaT:
            value = None
        elif key == "origin_groups" and isinstance(value, str):
            value = json.loads(value)
        elif hasattr(value, "tolist"):
            value = value.tolist()
        out[key] = value
    return out


def current_clusters(con, now: pd.Timestamp, window_hours: float) -> list[dict]:
    """Cluster rows as of now (news_clusters_asof) whose last item was reported in the last window_hours."""
    since = now - pd.Timedelta(hours=window_hours)
    df = con.execute(CLUSTERS_SQL, [now.isoformat(), since.isoformat()]).df()
    return [clean_row(r) for r in df.to_dict("records")]


def cluster_ids(cluster: dict) -> list[str]:
    """Every news id of a cluster: its items and their duplicates."""
    return [*(cluster.get("news_ids") or []), *(cluster.get("duplicate_ids") or [])]


def item_rows(con, ids: list[str], now: pd.Timestamp) -> dict[str, dict]:
    """News rows (title, source, first seen) and their article rows fetched by now, by id."""
    items = {r["id"]: clean_row(r) for r in con.execute(ITEMS_SQL, [ids, now.isoformat()]).df().to_dict("records")}
    for r in con.execute(ARTICLES_SQL, [now.isoformat(), ids]).df().to_dict("records"):
        if r["id"] in items:
            items[r["id"]]["article"] = clean_row(r)
    return items


def primary_rows(con, ids: list[str], now: pd.Timestamp) -> dict[str, dict]:
    """Primary sources by id: filings with stored text (documents joined) and NSE announcements."""
    out: dict[str, dict] = {}
    texts = con.execute(TEXTS_SQL, [ids, now.isoformat(), now.isoformat()]).df().to_dict("records")
    for r in sorted((clean_row(x) for x in texts), key=lambda x: x["id"]):
        entry = out.setdefault(r["primary_id"], {"kind": SOURCE_FILING, "label": r["form"], "docs": [],
                                                 "available_at": iso(r["available_at"]),
                                                 "published_at": iso(r["available_at"])})
        entry["docs"].append(r["text"] or "")
        entry["available_at"] = max(entry["available_at"], iso(r["fetched_at"]))
    for r in con.execute(ANNOUNCEMENTS_SQL, [ids, now.isoformat()]).df().to_dict("records"):
        out[r["id"]] = {"kind": SOURCE_ANNOUNCEMENT, "label": r["category"], "docs": [r["subject"] or ""],
                        "available_at": iso(r["available_at"]), "published_at": iso(r["available_at"])}
    return out


def build_sources(cluster: dict, items: dict[str, dict], primaries: dict[str, dict]) -> ClusterSources:
    """The citable sources of one cluster (claim_rules.ClusterSources)."""
    ids = cluster_ids(cluster)
    found = ClusterSources(cluster_row_id=cluster["id"], ticker=cluster["ticker"], news_ids=set(ids))
    for nid in ids:
        item = items.get(nid)
        if item is None:
            continue
        fields = {FIELD_TITLE: item["title"] or ""}
        available = iso(item["first_seen_at"])
        article = item.get("article")
        if article and article.get("access") in READ_ACCESS and article.get("extract"):
            fields[FIELD_EXTRACT] = " ".join(article["extract"])
            available = max(available, iso(article["fetched_at"]))
        found.sources[nid] = SourceText(SOURCE_ARTICLE, fields, available,
                                        min(available, iso(item["published_at"]) or available))
    for pid in cluster.get("primary_ids") or []:
        entry = primaries.get(pid)
        if entry is not None:
            found.sources[pid] = SourceText(entry["kind"], {FIELD_PRIMARY: "\n".join(entry["docs"])},
                                            entry["available_at"], entry["published_at"])
    return found


def sources_by_cluster(con, clusters: list[dict], now: pd.Timestamp) -> dict[str, ClusterSources]:
    """cluster_id -> its citable sources, all available by now."""
    ids = sorted({i for c in clusters for i in cluster_ids(c)})
    primary = sorted({p for c in clusters for p in c.get("primary_ids") or []})
    items, primaries = item_rows(con, ids, now), primary_rows(con, primary, now)
    return {c["cluster_id"]: build_sources(c, items, primaries) for c in clusters}
