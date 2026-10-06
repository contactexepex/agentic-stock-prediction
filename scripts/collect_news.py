#!/usr/bin/env python3
"""Collect RSS headlines (Google News queries + outlet feeds from the market config's `news`
section) into data/<market>/news/YYYY/MM/<today>.jsonl. Append-only; de-duplicates against the
last 7 days. Prints a JSON summary; outlet feeds that answer but carry nothing from the last
3 days are listed as `stale`. Tags come from scripts/news_tags.py, headline first: companies
named in the title (a ticker's `news_names`, default name and aliases, whole words,
case-insensitive, minus its `news_exclude` phrases); only when the title names none, the
plain-text summary (no HTML, URLs or outlet name). Each row stores `tickers`, `primary_tickers`
(title companies, unless compared "X vs Y" or listed), `mentioned_tickers` (listed, compared or
summary-only) and `tag_confidence` (high: exactly one title company, primary; else low). A
Google News company query does not tag by itself. Rows carry `tag_version`; older rows are
re-tagged on read by the `news` view. An item's id is its normalized title + source domain
(Google News <source url>), so one article under two source labels is stored once.
An outlet with `watchlist_only: true` (press-release wires) keeps only items whose title or
summary names a watchlist company: case-insensitive whole-word matching on each ticker's
`wire_names` (full company names; default its name and aliases) after removing the
`news.wire_exclude` phrases; `skipped_off_watchlist` counts the rest.
Exit code 1 only if every feed failed."""
from __future__ import annotations

import json
import re
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from common import append_jsonl, day_file, market_arg, recent_ids, require_market, utc_now, utc_today
from marketbrief.sources.rss import fetch_feed
from news_tags import TAG_VERSION, Tagger, article_id, company_queries, item_id, source_domain

MAX_AGE = timedelta(days=3)
socket.setdefaulttimeout(20)


def google_news_url(query: str, g: dict) -> str:
    q = f"{query} when:{g.get('window', '1d')}"
    params = "&".join(f"{k}={quote_plus(str(v))}" for k, v in g.get("params", {}).items())
    return f"{g['base']}?q={quote_plus(q)}&{params}"


def build_jobs(feeds: dict, watchlist: dict) -> list[dict]:
    jobs = []
    g = feeds.get("google_news")
    if g:
        template = g.get("query_template", '"{name}" stock')
        for _ticker, q in company_queries(watchlist, template):
            # the query only finds candidates: many results never name the company
            jobs.append({"url": google_news_url(q, g), "feed": f"gnews:{q}", "category": "company"})
        for cat, queries in feeds.get("categories", {}).items():
            for q in queries:
                jobs.append({"url": google_news_url(q, g), "feed": f"gnews:{q}", "category": cat})
    for o in feeds.get("outlets", []):
        jobs.append({"url": o["url"], "feed": o["name"], "category": o.get("category", "general"),
                     "watchlist_only": bool(o.get("watchlist_only"))})
    return jobs


def wire_patterns(watchlist: dict) -> dict[str, re.Pattern]:
    """The wire matching on its own (main() uses the same names and exclusions through
    news_tags.Tagger's wire rules, which also split primary/mentioned).
    For `watchlist_only` (press-release wire) feeds: a ticker's `wire_names` (full company
    names, so single ambiguous words such as "Apple" or "Meta" are left out), else its name and
    aliases; case-insensitive, whole words ("NVIDIA", "JPMORGAN CHASE" match)."""
    pats = {}
    for ticker, meta in watchlist.get("tickers", {}).items():
        names = meta.get("wire_names") or [meta["name"], *meta.get("aliases", [])]
        pats[ticker] = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.I)
    return pats


def wire_exclusions(feeds: dict) -> re.Pattern | None:
    """`news.wire_exclude`: regexes for phrases that name another company or no company at all
    ("Apple Hospitality", "Merck KGaA", "meta-analysis"); removed from wire text before matching."""
    pats = feeds.get("wire_exclude") or []
    return re.compile("|".join(f"(?:{p})" for p in pats), re.I) if pats else None


def wire_tickers(text: str, pats: dict[str, re.Pattern], exclude: re.Pattern | None) -> set[str]:
    if exclude:
        text = exclude.sub(" ", text)
    return {t for t, p in pats.items() if p.search(text)}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(entry) -> datetime | None:
    tm = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*tm[:6], tzinfo=timezone.utc) if tm else None


def main() -> int:
    watchlist = require_market(market_arg(__doc__).parse_args())
    feeds, market = watchlist.get("news", {}), watchlist["market"]
    tagger = Tagger(watchlist)
    seen = recent_ids(market, "news", days=7)
    now, now_dt = utc_now(), now_utc()
    items: dict[str, dict] = {}
    failed, stale = [], []
    skipped_off_watchlist = 0

    jobs = build_jobs(feeds, watchlist)
    for job in jobs:
        for attempt in range(2):  # one retry: Google News occasionally fails a single query
            parsed = fetch_feed(job["url"])
            status = parsed.get("status", 200)
            if not (status >= 400 or (parsed.bozo and not parsed.entries)) or status in (401, 403, 404):
                break
            time.sleep(2)
        if status >= 400 or (parsed.bozo and not parsed.entries):
            failed.append({"feed": job["feed"], "status": status,
                           "error": str(parsed.get("bozo_exception", ""))[:200]})
            continue
        times = [parse_time(e) for e in parsed.entries]
        if not job["feed"].startswith("gnews:") and not any(t is None or now_dt - t <= MAX_AGE for t in times):
            # an outlet feed that answers but has nothing recent has stopped updating
            newest = max((t for t in times if t), default=None)
            stale.append({"feed": job["feed"], "entries": len(times),
                          "newest": newest.isoformat() if newest else None})
        for e in parsed.entries:
            title = (e.get("title") or "").strip()
            if not title:
                continue
            src = e.get("source") or {}
            source = src.get("title") or job["feed"]
            if source and title.endswith(f" - {source}"):
                title = title[: -len(f" - {source}")]
            published = parse_time(e)
            if published and now_dt - published > MAX_AGE:
                continue
            domain = source_domain(src.get("href"))
            aid = item_id(title, source, domain)
            if aid in seen or article_id(title, source) in seen:   # also ids stored before domains
                continue
            # headline first; the plain-text summary only when the title names no company
            tags = tagger.classify_item(title, e.get("summary"), source, wire=job.get("watchlist_only", False))
            if job.get("watchlist_only") and not tags["tickers"]:
                skipped_off_watchlist += 1   # wire feeds: keep only releases naming a watchlist company
                continue
            if aid in items:  # same article from several feeds: tags come from its text, keep the first
                continue
            items[aid] = {
                "id": aid, "title": title, "url": e.get("link"), "source": source,
                "published_at": published.isoformat() if published else None,
                "first_seen_at": now, "feed": job["feed"], "category": job["category"],
                **tags, "source_domain": domain, "tag_version": TAG_VERSION,
            }

    written = append_jsonl(day_file(market, "news", utc_today()), items.values())
    print(json.dumps({"collector": "news", "market": market, "feeds": len(jobs), "failed": failed,
                      "stale": stale, "new_items": written,
                      "skipped_off_watchlist": skipped_off_watchlist}, indent=2))
    return 1 if jobs and len(failed) == len(jobs) else 0


if __name__ == "__main__":
    sys.exit(main())
