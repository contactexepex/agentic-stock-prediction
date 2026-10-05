#!/usr/bin/env python3
"""Collect RSS headlines (Google News queries + outlet feeds) into
data/news/YYYY/MM/<today>.jsonl. Append-only; de-duplicates against the last 7 days.
Prints a JSON summary. Exit code 1 only if every feed failed."""
from __future__ import annotations

import hashlib
import json
import re
import socket
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import yaml

from common import CONFIG, append_jsonl, day_file, recent_ids, utc_now, utc_today

USER_AGENT = "market-brief/1.0 (personal research; RSS reader)"
MAX_AGE = timedelta(days=3)
socket.setdefaulttimeout(20)


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def article_id(title: str, source: str) -> str:
    # Google News links are redirect URLs, so title + source is the stable identity.
    return hashlib.sha256(f"{norm(title)}|{norm(source)}".encode()).hexdigest()[:16]


def google_news_url(query: str, g: dict) -> str:
    q = f"{query} when:{g.get('window', '1d')}"
    params = "&".join(f"{k}={quote_plus(str(v))}" for k, v in g.get("params", {}).items())
    return f"{g['base']}?q={quote_plus(q)}&{params}"


def build_jobs(feeds: dict, watchlist: dict) -> list[dict]:
    jobs = []
    g = feeds.get("google_news")
    if g:
        for ticker, meta in watchlist.get("tickers", {}).items():
            for q in meta.get("queries", [f'"{meta["name"]}" stock']):
                jobs.append({"url": google_news_url(q, g), "feed": f"gnews:{q}",
                             "category": "company", "tickers": [ticker]})
        for cat, queries in feeds.get("categories", {}).items():
            for q in queries:
                jobs.append({"url": google_news_url(q, g), "feed": f"gnews:{q}",
                             "category": cat, "tickers": []})
    for o in feeds.get("outlets", []):
        jobs.append({"url": o["url"], "feed": o["name"],
                     "category": o.get("category", "general"), "tickers": []})
    return jobs


def alias_patterns(watchlist: dict) -> dict[str, re.Pattern]:
    pats = {}
    for ticker, meta in watchlist.get("tickers", {}).items():
        names = [meta["name"], *meta.get("aliases", [])]
        pats[ticker] = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.I)
    return pats


def parse_time(entry) -> datetime | None:
    tm = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*tm[:6], tzinfo=timezone.utc) if tm else None


def main() -> int:
    feeds = yaml.safe_load((CONFIG / "feeds.yaml").read_text())
    watchlist = yaml.safe_load((CONFIG / "watchlist.yaml").read_text())
    pats = alias_patterns(watchlist)
    seen = recent_ids("news", days=7)
    now, now_dt = utc_now(), datetime.now(timezone.utc)
    items: dict[str, dict] = {}
    failed = []

    jobs = build_jobs(feeds, watchlist)
    for job in jobs:
        parsed = feedparser.parse(job["url"], agent=USER_AGENT)
        status = parsed.get("status", 200)
        if status >= 400 or (parsed.bozo and not parsed.entries):
            failed.append({"feed": job["feed"], "status": status,
                           "error": str(parsed.get("bozo_exception", ""))[:200]})
            continue
        for e in parsed.entries:
            title = (e.get("title") or "").strip()
            if not title:
                continue
            source = (e.get("source") or {}).get("title") or job["feed"]
            if source and title.endswith(f" - {source}"):
                title = title[: -len(f" - {source}")]
            published = parse_time(e)
            if published and now_dt - published > MAX_AGE:
                continue
            aid = article_id(title, source)
            if aid in seen:
                continue
            text = f"{title} {e.get('summary', '')}"
            tickers = set(job["tickers"]) | {t for t, p in pats.items() if p.search(text)}
            if aid in items:  # same article from several feeds: merge tags
                items[aid]["tickers"] = sorted(set(items[aid]["tickers"]) | tickers)
                continue
            items[aid] = {
                "id": aid, "title": title, "url": e.get("link"), "source": source,
                "published_at": published.isoformat() if published else None,
                "first_seen_at": now, "feed": job["feed"], "category": job["category"],
                "tickers": sorted(tickers),
            }

    written = append_jsonl(day_file("news", utc_today()), items.values())
    print(json.dumps({"collector": "news", "feeds": len(jobs), "failed": failed,
                      "new_items": written}, indent=2))
    return 1 if jobs and len(failed) == len(jobs) else 0


if __name__ == "__main__":
    sys.exit(main())
