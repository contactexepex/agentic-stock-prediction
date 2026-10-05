#!/usr/bin/env python3
"""Collect RSS headlines (Google News queries + outlet feeds from the market config's `news`
section) into data/<market>/news/YYYY/MM/<today>.jsonl. Append-only; de-duplicates against the
last 7 days. Prints a JSON summary; outlet feeds that answer but carry nothing from the last
3 days are listed as `stale`. An outlet with `watchlist_only: true` (press-release wires) keeps
only items whose title or summary names a watchlist company: case-insensitive whole-word
matching on each ticker's `wire_names` (full company names; default its name and aliases) after
removing the `news.wire_exclude` phrases; `skipped_off_watchlist` counts the rest.
Exit code 1 only if every feed failed."""
from __future__ import annotations

import hashlib
import json
import re
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser

from common import append_jsonl, day_file, market_arg, recent_ids, require_market, utc_now, utc_today

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
        template = g.get("query_template", '"{name}" stock')
        for ticker, meta in watchlist.get("tickers", {}).items():
            for q in meta.get("queries", [template.format(name=meta["name"])]):
                jobs.append({"url": google_news_url(q, g), "feed": f"gnews:{q}",
                             "category": "company", "tickers": [ticker]})
        for cat, queries in feeds.get("categories", {}).items():
            for q in queries:
                jobs.append({"url": google_news_url(q, g), "feed": f"gnews:{q}",
                             "category": cat, "tickers": []})
    for o in feeds.get("outlets", []):
        jobs.append({"url": o["url"], "feed": o["name"], "category": o.get("category", "general"),
                     "tickers": [], "watchlist_only": bool(o.get("watchlist_only"))})
    return jobs


def alias_patterns(watchlist: dict) -> dict[str, re.Pattern]:
    pats = {}
    for ticker, meta in watchlist.get("tickers", {}).items():
        names = [meta["name"], *meta.get("aliases", [])]
        pats[ticker] = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.I)
    return pats


def wire_patterns(watchlist: dict) -> dict[str, re.Pattern]:
    """For `watchlist_only` (press-release wire) feeds: a ticker's `wire_names` (full company
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
    pats, wire, exclude = alias_patterns(watchlist), wire_patterns(watchlist), wire_exclusions(feeds)
    seen = recent_ids(market, "news", days=7)
    now, now_dt = utc_now(), now_utc()
    items: dict[str, dict] = {}
    failed, stale = [], []
    skipped_off_watchlist = 0

    jobs = build_jobs(feeds, watchlist)
    for job in jobs:
        for attempt in range(2):  # one retry: Google News occasionally fails a single query
            parsed = feedparser.parse(job["url"], agent=USER_AGENT)
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
            if job.get("watchlist_only"):
                tickers = set(job["tickers"]) | wire_tickers(text, wire, exclude)
            else:
                tickers = set(job["tickers"]) | {t for t, p in pats.items() if p.search(text)}
            if job.get("watchlist_only") and not tickers:
                skipped_off_watchlist += 1   # wire feeds: keep only releases naming a watchlist company
                continue
            if aid in items:  # same article from several feeds: merge tags
                items[aid]["tickers"] = sorted(set(items[aid]["tickers"]) | tickers)
                continue
            items[aid] = {
                "id": aid, "title": title, "url": e.get("link"), "source": source,
                "published_at": published.isoformat() if published else None,
                "first_seen_at": now, "feed": job["feed"], "category": job["category"],
                "tickers": sorted(tickers),
            }

    written = append_jsonl(day_file(market, "news", utc_today()), items.values())
    print(json.dumps({"collector": "news", "market": market, "feeds": len(jobs), "failed": failed,
                      "stale": stale, "new_items": written,
                      "skipped_off_watchlist": skipped_off_watchlist}, indent=2))
    return 1 if jobs and len(failed) == len(jobs) else 0


if __name__ == "__main__":
    sys.exit(main())
