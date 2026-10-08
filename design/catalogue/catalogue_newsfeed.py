"""News items for the News page (data request 8): stored news as of the examples' cut-off, read with the as-of views
(news_asof, news_status_ids_asof, the newest news_enriched and news_articles rows by the cut-off), about 30 items per
market first seen in the 3 days before it. The six invented items of catalogue_news.news_items stay first in the file;
`origin` says which is which. `scope`, `summary`, `summary_source` and `market_moving` are derived for pages here."""
from __future__ import annotations

import json

from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market

CUTOFF = "2026-10-07 12:00:00+00"
WINDOW_START = "2026-10-04 12:00:00+00"
LAST_DAY = "2026-10-06T12:00:00Z"
COMPANY_ITEMS, MARKET_ITEMS = 16, 12   # each half from the last 24 hours, half from the two days before
MIN_MARKET_RELEVANCE = 0.4   # market-wide feeds carry off-topic items; the analyst's relevance filters them
MATERIALITY_RANK = {"high": 0, "medium": 1, "low": 2, None: 3}
ITEMS_SQL = f"""
WITH n AS (SELECT DISTINCT ON (id) * FROM news_asof('{CUTOFF}'::TIMESTAMPTZ) ORDER BY id, first_seen_at),
e AS (SELECT DISTINCT ON (id) * FROM news_enriched WHERE analyzed_at <= '{CUTOFF}'::TIMESTAMPTZ
      ORDER BY id, analyzed_at DESC),
s AS (SELECT DISTINCT ON (news_id) news_id AS id, status, cluster_id, as_of AS status_as_of
      FROM news_status_ids_asof('{CUTOFF}'::TIMESTAMPTZ) ORDER BY news_id, ticker),
v AS (SELECT DISTINCT ON (cluster_id) cluster_id, independent_origins, primary_ids FROM news_verified
      WHERE level = 'cluster' AND as_of <= '{CUTOFF}'::TIMESTAMPTZ ORDER BY cluster_id, as_of DESC),
a AS (SELECT DISTINCT ON (id) id, access, extract FROM news_articles WHERE fetched_at <= '{CUTOFF}'::TIMESTAMPTZ
      ORDER BY id, fetched_at DESC)
SELECT n.id, n.title, n.url, n.source, n.source_domain, n.published_at, n.first_seen_at, n.feed, n.category,
       n.tickers, n.primary_tickers, e.analyzed_at, e.event_type, e.materiality, e.sentiment, e.relevance, e.novelty,
       e.urgency, e.priced_in, e.geopolitical, e.summary AS analyst_summary, s.status, s.cluster_id, s.status_as_of,
       v.independent_origins, v.primary_ids, a.access, a.extract
FROM n JOIN e USING (id) LEFT JOIN s USING (id) LEFT JOIN v USING (cluster_id) LEFT JOIN a USING (id)
WHERE n.first_seen_at >= '{WINDOW_START}'::TIMESTAMPTZ ORDER BY n.first_seen_at DESC, n.id"""
UPDATES_SQL = f"""SELECT news_id, title, seen_at FROM news_updates WHERE seen_at <= '{CUTOFF}'::TIMESTAMPTZ
                  ORDER BY news_id, seen_at"""


def iso(value) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%dT%H:%M:%SZ")


def summary_of(row: dict) -> tuple[str | None, str]:
    """At most two stored key sentences of the read article; else the analyst's summary when it is not the
    templated "<Type> item on <TICKER>: <title>" form; else none."""
    extract = row["extract"]
    sentences = json.loads(extract) if isinstance(extract, str) else [] if extract is None else list(extract)
    if row["access"] in ("full", "partial") and sentences:
        return " ".join(str(s) for s in sentences[:2]), "article"
    text = row["analyst_summary"]
    if text and " item on " not in text.split(":", 1)[0] and text.strip() != row["title"].strip():
        return text, "analyst"
    return None, "none"


def market_moving(scope: str, row: dict) -> bool:
    """W1's proposed rule: a high-materiality market-wide item, or a high-materiality results item of a company."""
    return row["materiality"] == "high" and (scope == "market" or row["event_type"] == "earnings")


def item(market: str, row: dict, history: dict[str, list[dict]]) -> dict:
    scope = "company" if row["primary_tickers"] else "market"
    summary, source = summary_of(row)
    return {"id": row["id"], "market": market, "tickers": list(row["tickers"] or []),
            "primary_tickers": list(row["primary_tickers"] or []), "title": row["title"], "source": row["source"],
            "source_domain": row["source_domain"], "url": row["url"], "published_at": iso(row["published_at"]),
            "first_seen_at": iso(row["first_seen_at"]),
            "enrichment": {"event_type": row["event_type"], "materiality": row["materiality"],
                           "sentiment": row["sentiment"], "relevance": row["relevance"], "novelty": row["novelty"],
                           "urgency": row["urgency"], "priced_in": row["priced_in"],
                           "geopolitical": row["geopolitical"], "analyzed_at": iso(row["analyzed_at"])},
            "status": row["status"], "status_as_of": iso(row["status_as_of"]), "cluster_id": row["cluster_id"],
            "independent_origins": row["independent_origins"], "primary_ids": list(row["primary_ids"] or []),
            "headline_history": history.get(row["id"], []), "headline_history_status": "exists (kind news_updates)",
            "origin": "stored", "scope": scope, "category": row["category"], "feed": row["feed"],
            "summary": summary, "summary_source": source, "market_moving": market_moving(scope, row)}


def rank(row: dict) -> tuple:
    relevance = row["relevance"] if isinstance(row["relevance"], float) and row["relevance"] == row["relevance"] else 0
    return MATERIALITY_RANK.get(row["materiality"], 3), -relevance, -row["first_seen_at"].timestamp(), row["id"]


def by_day(rows: list[dict], key, limit: int) -> list[dict]:
    """Half of `limit` from the last 24 hours, the rest from before (round robin over `key` in each part)."""
    last = [r for r in rows if iso(r["first_seen_at"]) >= LAST_DAY]
    chosen = round_robin(last, key, limit // 2)
    chosen += round_robin([r for r in rows if r not in last], key, limit - len(chosen))
    return chosen + round_robin([r for r in rows if r not in chosen], key, limit - len(chosen))


def round_robin(rows: list[dict], key, limit: int) -> list[dict]:
    """Up to `limit` rows, taking the best-ranked row of each group in turn."""
    groups: dict = {}
    for row in sorted(rows, key=rank):
        groups.setdefault(key(row), []).append(row)
    out = []
    while len(out) < limit and any(groups.values()):
        for name in sorted(groups):
            if groups[name] and len(out) < limit:
                out.append(groups[name].pop(0))
    return out


def stored_items(market: str) -> list[dict]:
    cfg, con = load_market(market), connect(market)
    rows = con.execute(ITEMS_SQL).df().to_dict("records")
    for row in rows:
        for column in ("tickers", "primary_tickers", "primary_ids"):
            value = row[column]
            row[column] = [] if value is None or isinstance(value, float) else [str(x) for x in value]
        for column in ("published_at", "first_seen_at", "analyzed_at", "status_as_of"):
            row[column] = None if row[column] is None or str(row[column]) == "NaT" else row[column].to_pydatetime()
        if isinstance(row["extract"], float):
            row["extract"] = None
        for column in ("status", "cluster_id", "access", "analyst_summary", "independent_origins"):
            if row[column] is not None and str(row[column]) in ("nan", "NaN", "<NA>"):
                row[column] = None
    history: dict[str, list[dict]] = {}
    for news_id, title, seen in con.execute(UPDATES_SQL).fetchall():
        history.setdefault(news_id, []).append({"title": title, "seen_at": iso(seen)})
    active = set(cfg["active_tickers"]) - {"INDIGO", "DAL"}   # the examples' inactive companies
    company = [r for r in rows if r["primary_tickers"] and r["primary_tickers"][0] in active and r["status"]]
    chosen = by_day(company, lambda r: r["status"], COMPANY_ITEMS // 2)
    rest = [r for r in company if r not in chosen]
    chosen += by_day(rest, lambda r: r["primary_tickers"][0], COMPANY_ITEMS - len(chosen))
    market_wide = [r for r in rows if not r["primary_tickers"] and (r["relevance"] or 0) >= MIN_MARKET_RELEVANCE]
    chosen += by_day(market_wide, lambda r: r["category"], MARKET_ITEMS)
    chosen.sort(key=lambda r: (-r["first_seen_at"].timestamp(), r["id"]))
    return [item(market, row, history) for row in chosen]


def news_page_items(invented: list[dict]) -> list[dict]:
    """The six invented items (with the page fields added) followed by the stored items of both markets."""
    out = []
    for news in invented:
        scope = "company" if news["primary_tickers"] else "market"
        enrichment = news["enrichment"]
        out.append({**news, "origin": "invented", "scope": scope, "category": None, "feed": None, "summary": None,
                    "summary_source": "none", "market_moving": market_moving(scope, enrichment)})
    return out + stored_items("india") + stored_items("us")
