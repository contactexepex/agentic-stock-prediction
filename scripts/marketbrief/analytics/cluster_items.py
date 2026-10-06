"""The inputs of news clustering as of a moment: news items per watchlist ticker and primary candidates."""
from __future__ import annotations

from collections import defaultdict
from typing import NamedTuple
from urllib.parse import urlsplit

import pandas as pd

from marketbrief.analytics.article_pages import canonical_url, host_of
from marketbrief.analytics.news_sources import Sources, label_domains, outlet_key, outlet_of
from marketbrief.analytics.text_measures import distinctive, numbers, sources_say, title_tokens
from marketbrief.constants.news_clusters import (ANNOUNCEMENTS_SQL, ARTICLES_SQL, DEFAULT_LOOKBACK_HOURS,
                                                 DEFAULT_WINDOW_HOURS, FILINGS_SQL, GOOGLE_NEWS_HOST, NEWS_ROWS_SQL,
                                                 READ_ACCESS)


class DisjointSets:
    """Union-find over 0..n-1; the smallest index is the root."""

    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        """The root of i's set."""
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int):
        """Merge the sets of a and b."""
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


class NewsRow(NamedTuple):
    """One stored news row."""
    id: str
    title: str | None
    url: str | None
    source: str | None
    source_domain: str | None
    published_at: object
    first_seen_at: object
    primary_tickers: list | None


def to_utc(v) -> pd.Timestamp | None:
    """A timestamp as UTC (None for missing values)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    t = pd.Timestamp(v)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def iso_seconds(t: pd.Timestamp | None) -> str | None:
    """A timestamp as ISO text rounded down to the second."""
    return None if t is None else t.floor("s").isoformat()


def own_page(article: dict | None, url: str | None, host: str) -> str | None:
    """The article's own page URL: the fetched one, else the row's unless it is a Google News link."""
    return (article or {}).get("final_url") or (url if host != GOOGLE_NEWS_HOST else None)


def resolve_domain(article: dict | None, row: NewsRow, host: str, src: Sources, learned: dict) -> str | None:
    """The outlet domain of a row: the fetched page's, the stored one, the URL host, the source label."""
    listed_host = host if host and host != GOOGLE_NEWS_HOST and src.lookup(host)[0] else None
    other_host = host if host and host != GOOGLE_NEWS_HOST else None
    fetched = (article or {}).get("domain") if article and article.get("final_url") else None
    return fetched or row.source_domain or listed_host or outlet_of(row.source, src, learned) or other_host


def row_fields(row: NewsRow, article: dict | None, src: Sources, learned: dict) -> dict:
    """The per-row item fields shared by all tickers the row is about."""
    host = host_of(row.url)
    domain = resolve_domain(article, row, host, src, learned)
    listed = src.lookup(domain)[0]
    domain = listed or domain
    seen_t, pub_t = to_utc(row.first_seen_at), to_utc(row.published_at)
    art = article or {}
    wire, evidence = (art.get("origin_wire"), art.get("origin_evidence")) if art.get("origin_wire") else \
        src.detect_wire(title=row.title, source=row.source, domain=domain)
    provider = art.get("provider")
    meta = src.lookup(domain)[1] or {}
    news_path = meta.get("opinion_unless_path")
    page = own_page(article, row.url, host)
    # e.g. Seeking Alpha: contributor articles are opinion; only its news desk (/news/) is not
    opinion = bool(news_path) and not (page and urlsplit(page).path.startswith(news_path))
    return {
        "id": row.id, "title": row.title or "", "source": row.source, "domain": domain, "tier": src.tier(domain),
        # vetted: an allowlisted outlet, or the agency itself (its Google News source label). An
        # agency named in an unvetted item's title only joins that agency's group; it never makes
        # the item vetted, so it can never create or count an origin.
        "vetted": bool(listed) or evidence == "source", "read": bool(art.get("access") in READ_ACCESS),
        "opinion": opinion, "t": pub_t if pub_t is not None and pub_t <= seen_t else seen_t, "seen": seen_t,
        "wire": wire, "wire_ev": evidence, "provider": provider if not src.wire_of_name(provider) else None,
        "promo": (art.get("promotional") or src.is_promotional(name=row.source, domain=domain)
                  or src.is_promotional(name=provider) or src.is_promotional(text=row.title)),
        "canon": canonical_url(own_page(article, row.url, host)), "outlet_key": outlet_key(domain, row.source),
        "article": article, "fetched": to_utc(art.get("fetched_at")),
        "say": bool(art.get("sources_say")) or sources_say(row.title), "nums": distinctive(numbers(row.title)),
    }


def load_items(con, cfg: dict, src: Sources, as_of: pd.Timestamp) -> list[dict]:
    """The news items of the lookback window about a watchlist ticker as primary subject, one per ticker."""
    since = as_of - pd.Timedelta(hours=float(src.clusters.get("lookback_hours", DEFAULT_LOOKBACK_HOURS)))
    rows = [NewsRow(*r) for r in con.execute(NEWS_ROWS_SQL, [as_of.to_pydatetime(), since.to_pydatetime()]).fetchall()]
    articles = {r["id"]: r for r in con.execute(ARTICLES_SQL, [as_of.to_pydatetime()]).df().to_dict("records")}
    learned = label_domains(((r.source, r.source_domain) for r in rows), src)
    items = []
    for row in rows:
        tickers = [t for t in (row.primary_tickers or []) if t in cfg["tickers"]]
        if not tickers:
            continue
        a = articles.get(row.id)
        a = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in a.items()} if a else None
        fields = row_fields(row, a, src, learned)
        items.extend({**fields, "ticker": t} for t in tickers)
    return items


def load_primaries(con, src: Sources, as_of: pd.Timestamp) -> dict[str, list[tuple]]:
    """{ticker: [(public time, id)]} of the SEC filings and NSE announcements that may confirm a story."""
    cl = src.clusters
    since = as_of - pd.Timedelta(hours=float(cl.get("lookback_hours", DEFAULT_LOOKBACK_HOURS))
                                 + float(cl.get("window_hours", DEFAULT_WINDOW_HOURS)))
    out: dict[str, list[tuple]] = defaultdict(list)
    forms = list(cl.get("sec_forms") or [])
    for tid, ticker, t in con.execute(FILINGS_SQL, [forms]).fetchall() + con.execute(ANNOUNCEMENTS_SQL).fetchall():
        tt = to_utc(t)
        if tt is not None and since <= tt <= as_of:
            out[ticker].append((tt, tid))
    return out


def drop_tokens(cfg: dict, ticker: str) -> set[str]:
    """The tokens of a company's own names, which carry no information about an event."""
    m = cfg["tickers"][ticker]
    names = [m["name"], *m.get("aliases", []), *(m.get("news_names") or []), ticker]
    return {w for n in names for w in title_tokens(n)} | {ticker.lower()}
