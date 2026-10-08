"""News items as the market pages show them (catalogue entity "News item", docs/DATA_CATALOGUE.md; selection of
design/mockups/09-news/notes.md). Every read is as of the cut-off: the item list of `news_asof`, the newest
`news_enriched` and `news_articles` rows by then, the status of `news_status_ids_asof` and the newest cluster row of
`news_verified_asof`, the headline history of `news_updates` seen by then. Nothing stored later reaches a page.
`news_items` is shared with the company page (B12), which filters it per ticker; `news_window` is the News page's
and Home's selection.

The rules are W1's of the catalogue build (design/catalogue/catalogue_newsfeed.py, data request 8): `scope`, the
`summary` line and the `market_moving` flag. The item's status is the one of its first primary ticker; a
market-wide item has none, because verification is per company."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from marketbrief.constants.market_pages import (
    EVENT_EARNINGS,
    HEADLINE_HISTORY_STATUS,
    MATERIALITY_HIGH,
    NEWS_MIN_MARKET_RELEVANCE,
    ORIGIN_STORED,
    READABLE_ACCESS,
    SCOPE_COMPANY,
    SCOPE_MARKET,
    SUMMARY_ANALYST,
    SUMMARY_ARTICLE,
    SUMMARY_NONE,
    TEMPLATED_SUMMARY_MARK,
)
from marketbrief.utils.numbers import json_safe_float

# the items first seen in (from, to], each with its newest enrichment, article read, status and cluster by the cut-off
ITEMS_SQL = """
WITH n AS (SELECT DISTINCT ON (id) * FROM news_asof($cutoff::TIMESTAMPTZ) ORDER BY id, first_seen_at),
w AS (SELECT * FROM n WHERE first_seen_at > $start::TIMESTAMPTZ AND first_seen_at <= $cutoff::TIMESTAMPTZ),
e AS (SELECT DISTINCT ON (id) * FROM news_enriched WHERE analyzed_at <= $cutoff::TIMESTAMPTZ
      ORDER BY id, analyzed_at DESC),
s AS (SELECT * FROM news_status_ids_asof($cutoff::TIMESTAMPTZ)),
v AS (SELECT DISTINCT ON (cluster_id) cluster_id, independent_origins, primary_ids
      FROM news_verified_asof($cutoff::TIMESTAMPTZ) WHERE level = 'cluster' ORDER BY cluster_id, as_of DESC),
a AS (SELECT DISTINCT ON (id) id, access, extract FROM news_articles WHERE fetched_at <= $cutoff::TIMESTAMPTZ
      ORDER BY id, fetched_at DESC)
SELECT w.id, w.title, w.url, w.source, w.source_domain, w.published_at, w.first_seen_at, w.feed, w.category,
       w.tickers, w.primary_tickers, e.analyzed_at, e.event_type, e.materiality, e.sentiment, e.relevance, e.novelty,
       e.urgency, e.priced_in, e.geopolitical, e.summary AS analyst_summary, s.status, s.cluster_id,
       s.as_of AS status_as_of, v.independent_origins, v.primary_ids, a.access, a.extract
FROM w JOIN e USING (id)
LEFT JOIN s ON s.news_id = w.id AND s.ticker = w.primary_tickers[1]
LEFT JOIN v ON v.cluster_id = s.cluster_id
LEFT JOIN a ON a.id = w.id
ORDER BY w.first_seen_at DESC, w.id"""
COUNT_BEFORE_SQL = """SELECT count(DISTINCT id) FROM news_asof($cutoff::TIMESTAMPTZ)
                      WHERE first_seen_at <= $start::TIMESTAMPTZ"""
UPDATES_SQL = """SELECT news_id, title, seen_at FROM news_updates
                 WHERE seen_at <= $cutoff::TIMESTAMPTZ AND list_contains($ids, news_id) ORDER BY news_id, seen_at"""


def iso(value) -> str | None:
    """A UTC time as `YYYY-MM-DDTHH:MM:SSZ`; None for a missing one."""
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def text_or_none(value) -> str | None:
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)


def id_list(value) -> list[str]:
    if value is None or isinstance(value, float):
        return []
    return [str(item) for item in value]


def bool_or_none(value) -> bool | None:
    return None if value is None or pd.isna(value) else bool(value)


def int_or_none(value) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def summary_of(row: dict) -> tuple[str | None, str]:
    """At most two stored key sentences of the read article; else the analyst's summary when it is not the
    templated "<Type> item on <TICKER>: <title>" form; else none."""
    extract = row["extract"]
    if isinstance(extract, str):
        sentences = json.loads(extract)
    else:
        sentences = [] if extract is None or isinstance(extract, float) else list(extract)
    if row["access"] in READABLE_ACCESS and sentences:
        return " ".join(str(sentence) for sentence in sentences[:2]), SUMMARY_ARTICLE
    text = text_or_none(row["analyst_summary"])
    if text and TEMPLATED_SUMMARY_MARK not in text.split(":", 1)[0] and text.strip() != str(row["title"]).strip():
        return text, SUMMARY_ANALYST
    return None, SUMMARY_NONE


def market_moving(scope: str, row: dict) -> bool:
    """W1's rule: a high-materiality market-wide item, or a high-materiality results item of a company."""
    return row["materiality"] == MATERIALITY_HIGH and (scope == SCOPE_MARKET or row["event_type"] == EVENT_EARNINGS)


def item(market: str, row: dict, history: dict[str, list[dict]]) -> dict:
    """One News item record (catalogue fields)."""
    primary = id_list(row["primary_tickers"])
    scope = SCOPE_COMPANY if primary else SCOPE_MARKET
    summary, summary_source = summary_of(row)
    return {
        "id": row["id"],
        "market": market,
        "tickers": id_list(row["tickers"]),
        "primary_tickers": primary,
        "title": row["title"],
        "source": text_or_none(row["source"]),
        "source_domain": text_or_none(row["source_domain"]),
        "url": text_or_none(row["url"]),
        "published_at": iso(row["published_at"]),
        "first_seen_at": iso(row["first_seen_at"]),
        "enrichment": {
            "event_type": text_or_none(row["event_type"]),
            "materiality": text_or_none(row["materiality"]),
            "sentiment": json_safe_float(row["sentiment"]),
            "relevance": json_safe_float(row["relevance"]),
            "novelty": json_safe_float(row["novelty"]),
            "urgency": text_or_none(row["urgency"]),
            "priced_in": bool_or_none(row["priced_in"]),
            "geopolitical": bool_or_none(row["geopolitical"]),
            "analyzed_at": iso(row["analyzed_at"]),
        },
        "status": text_or_none(row["status"]),
        "status_as_of": iso(row["status_as_of"]),
        "cluster_id": text_or_none(row["cluster_id"]),
        "independent_origins": int_or_none(row["independent_origins"]),
        "primary_ids": id_list(row["primary_ids"]),
        "headline_history": history.get(row["id"], []),
        "headline_history_status": HEADLINE_HISTORY_STATUS,
        "scope": scope,
        "category": text_or_none(row["category"]),
        "feed": text_or_none(row["feed"]),
        "summary": summary,
        "summary_source": summary_source,
        "market_moving": market_moving(scope, row),
        "origin": ORIGIN_STORED,
    }


def shown(row: dict, tickers: set[str]) -> bool:
    """A company item about a collected company, or a market-wide item the analyst scored relevant."""
    primary = id_list(row["primary_tickers"])
    if primary:
        return primary[0] in tickers
    relevance = json_safe_float(row["relevance"])
    return relevance is not None and relevance >= NEWS_MIN_MARKET_RELEVANCE


def priority(record: dict) -> tuple:
    """Which items the cap keeps first within a scope: market movers, then high materiality, then the newest."""
    high = record["enrichment"]["materiality"] == MATERIALITY_HIGH
    return (not record["market_moving"], not high, -pd.Timestamp(record["first_seen_at"]).timestamp(), record["id"])


def newest_first(record: dict) -> tuple:
    """The pages' order: newest first seen first, then by id (as ITEMS_SQL orders)."""
    return -pd.Timestamp(record["first_seen_at"]).timestamp(), record["id"]


def capped(records: list[dict], max_items: int) -> list[dict]:
    """At most `max_items`: half for company items and half for market-wide ones, each by `priority`, a share one
    scope leaves unused going to the other; newest first."""
    company = sorted((r for r in records if r["scope"] == SCOPE_COMPANY), key=priority)
    market = sorted((r for r in records if r["scope"] == SCOPE_MARKET), key=priority)
    company_share = max(max_items // 2, max_items - len(market))
    kept = company[:company_share]
    kept += market[: max_items - len(kept)]
    return sorted(kept, key=newest_first)


EARLIEST = datetime(1970, 1, 1, tzinfo=timezone.utc)


def news_items(cfg: dict, con, cutoff: datetime, tickers: list[str] | None = None,
               since: datetime | None = None) -> list[dict]:
    """Every News item record first seen in (since, cutoff] (since None: from the first stored item) that the
    analyst scored by the cut-off, about a collected company or market-wide and relevant (`shown`); with `tickers`,
    only items tagged with one of them. Newest first, uncapped."""
    params = {"cutoff": cutoff.isoformat(), "start": (since or EARLIEST).isoformat()}
    collected = set(cfg["tickers"])
    rows = [row for row in con.execute(ITEMS_SQL, params).df().to_dict("records") if shown(row, collected)]
    if tickers is not None:
        wanted = set(tickers)
        rows = [row for row in rows if wanted & set(id_list(row["tickers"]))]
    history: dict[str, list[dict]] = {}
    ids = [row["id"] for row in rows]
    if ids:
        for news_id, title, seen_at in con.execute(UPDATES_SQL, {"cutoff": params["cutoff"], "ids": ids}).fetchall():
            history.setdefault(news_id, []).append({"seen_at": iso(seen_at), "title": title})
    return [item(cfg["market"], row, history) for row in rows]


def news_window(cfg: dict, con, cutoff: datetime, days: int, max_items: int) -> tuple[list[dict], dict]:
    """(items, window) of a market: `news_items` first seen in the `days` before the cut-off, at most `max_items`
    (`capped`), newest first; `window` is the selection's record (from, to, counts)."""
    start = cutoff - timedelta(days=days)
    records = news_items(cfg, con, cutoff, since=start)
    older = con.execute(COUNT_BEFORE_SQL, {"cutoff": cutoff.isoformat(), "start": start.isoformat()}).fetchone()[0]
    window = {
        "days": days,
        "from": iso(start),
        "to": iso(cutoff),
        "max_items": max_items,
        "stored_in_window": len(records),
        "older_hidden": int(older),
    }
    return capped(records, max_items), window
