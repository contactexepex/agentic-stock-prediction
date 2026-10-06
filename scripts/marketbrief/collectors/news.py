"""Collect RSS headlines (Google News queries + outlet feeds from the market config's `news`
section) into data/<market>/news/YYYY/MM/<today>.jsonl. Append-only; de-duplicates against the
last 7 days. Prints a JSON summary; outlet feeds that answer but carry nothing from the last
3 days are listed as `stale`. Tags come from marketbrief/analytics/news_tags.py, headline first: companies
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
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from marketbrief.analytics.news_tags import (TAG_VERSION, Tagger, article_id, company_queries, item_id,
                                             source_domain)
from marketbrief.constants.columns import COL_ID, COL_TITLE
from marketbrief.constants.config_keys import CFG_MARKET, CFG_NEWS
from marketbrief.constants.kinds import KIND_NEWS
from marketbrief.constants.news import (COLLECTOR_NEWS, DEFAULT_CATEGORY, DEFAULT_QUERY_TEMPLATE, DEFAULT_WINDOW,
                                        FEED_PREFIX_GNEWS, FETCH_ATTEMPTS, MAX_AGE_DAYS, PERMANENT_STATUSES,
                                        RETRY_PAUSE_SECONDS, SEEN_LOOKBACK_DAYS, SOCKET_TIMEOUT_SECONDS,
                                        TITLE_SEPARATOR)
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_FAILED, SUMMARY_MARKET
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file, recent_ids
from marketbrief.sources.rss import fetch_feed

MAX_AGE = timedelta(days=MAX_AGE_DAYS)
socket.setdefaulttimeout(SOCKET_TIMEOUT_SECONDS)


def google_news_url(query: str, settings: dict) -> str:
    """The Google News RSS search URL of a query (window and parameters from the config)."""
    query = f"{query} when:{settings.get('window', DEFAULT_WINDOW)}"
    params = "&".join(f"{k}={quote_plus(str(v))}" for k, v in settings.get("params", {}).items())
    return f"{settings['base']}?q={quote_plus(query)}&{params}"


def build_jobs(feeds: dict, watchlist: dict) -> list[dict]:
    """The feed jobs of a run: a Google News query per company and category, and the outlet feeds."""
    jobs = []
    google = feeds.get("google_news")
    if google:
        template = google.get("query_template", DEFAULT_QUERY_TEMPLATE)
        for _ticker, query in company_queries(watchlist, template):
            # the query only finds candidates: many results never name the company
            jobs.append({"url": google_news_url(query, google), "feed": f"{FEED_PREFIX_GNEWS}{query}",
                         "category": "company"})
        for category, queries in feeds.get("categories", {}).items():
            for query in queries:
                jobs.append({"url": google_news_url(query, google), "feed": f"{FEED_PREFIX_GNEWS}{query}",
                             "category": category})
    for outlet in feeds.get("outlets", []):
        jobs.append({"url": outlet["url"], "feed": outlet["name"], "category": outlet.get("category", DEFAULT_CATEGORY),
                     "watchlist_only": bool(outlet.get("watchlist_only"))})
    return jobs


def now_utc() -> datetime:
    """The wall-clock time (not MB_NOW): feed items are aged against the moment they are read."""
    return datetime.now(timezone.utc)


def parse_time(entry) -> datetime | None:
    """The published (or updated) time of a feed entry as an aware UTC datetime, or None."""
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*stamp[:6], tzinfo=timezone.utc) if stamp else None


def is_failed(parsed, status: int) -> bool:
    """True when a feed answered with an error status, or with nothing but a parse error."""
    return status >= 400 or bool(parsed.bozo and not parsed.entries)


def fetch_with_retry(url: str):
    """(parsed feed, status) with one retry: Google News occasionally fails a single query."""
    for _attempt in range(FETCH_ATTEMPTS):
        parsed = fetch_feed(url)
        status = parsed.get("status", 200)
        if not is_failed(parsed, status) or status in PERMANENT_STATUSES:
            break
        time.sleep(RETRY_PAUSE_SECONDS)
    return parsed, status


class NewsCollector:
    """One run over the feed jobs of a market."""

    def __init__(self, watchlist: dict):
        """The news collector's watchlist and market."""
        self.watchlist, self.market = watchlist, watchlist[CFG_MARKET]
        self.feeds = watchlist.get(CFG_NEWS, {})
        self.tagger = Tagger(watchlist)
        self.seen = recent_ids(self.market, KIND_NEWS, days=SEEN_LOOKBACK_DAYS)
        self.now, self.now_dt = utc_now(), now_utc()
        self.items: dict[str, dict] = {}
        self.failed: list[dict] = []
        self.stale: list[dict] = []
        self.skipped_off_watchlist = 0

    def check_stale(self, job: dict, times: list) -> None:
        """Note an outlet feed that answers but has nothing recent (it has stopped updating)."""
        if job["feed"].startswith(FEED_PREFIX_GNEWS):
            return
        if any(t is None or self.now_dt - t <= MAX_AGE for t in times):
            return
        newest = max((t for t in times if t), default=None)
        self.stale.append({"feed": job["feed"], "entries": len(times),
                           "newest": newest.isoformat() if newest else None})

    def add_entry(self, job: dict, entry) -> None:
        """Turn one feed entry into a news row unless it is empty, old, seen, or off the watchlist."""
        title = (entry.get(COL_TITLE) or "").strip()
        if not title:
            return
        source_info = entry.get("source") or {}
        source = source_info.get(COL_TITLE) or job["feed"]
        if source and title.endswith(f"{TITLE_SEPARATOR}{source}"):
            title = title[: -len(f"{TITLE_SEPARATOR}{source}")]
        published = parse_time(entry)
        if published and self.now_dt - published > MAX_AGE:
            return
        domain = source_domain(source_info.get("href"))
        news_id = item_id(title, source, domain)
        if news_id in self.seen or article_id(title, source) in self.seen:   # also ids stored before domains
            return
        # headline first; the plain-text summary only when the title names no company
        tags = self.tagger.classify_item(title, entry.get("summary"), source, wire=job.get("watchlist_only", False))
        if job.get("watchlist_only") and not tags["tickers"]:
            self.skipped_off_watchlist += 1   # wire feeds: keep only releases naming a watchlist company
            return
        if news_id in self.items:  # same article from several feeds: tags come from its text, keep the first
            return
        self.items[news_id] = {
            COL_ID: news_id, COL_TITLE: title, "url": entry.get("link"), "source": source,
            "published_at": published.isoformat() if published else None,
            "first_seen_at": self.now, "feed": job["feed"], "category": job["category"],
            **tags, "source_domain": domain, "tag_version": TAG_VERSION,
        }

    def run_job(self, job: dict) -> None:
        """Fetch one feed and add its entries."""
        parsed, status = fetch_with_retry(job["url"])
        if is_failed(parsed, status):
            self.failed.append({"feed": job["feed"], "status": status,
                                "error": str(parsed.get("bozo_exception", ""))[:200]})
            return
        self.check_stale(job, [parse_time(entry) for entry in parsed.entries])
        for entry in parsed.entries:
            self.add_entry(job, entry)

    def collect(self) -> int:
        """Run every job, store the rows, print the summary; returns the exit code."""
        jobs = build_jobs(self.feeds, self.watchlist)
        for job in jobs:
            self.run_job(job)
        written = append_jsonl(day_file(self.market, KIND_NEWS, utc_today()), self.items.values())
        print(json.dumps({SUMMARY_COLLECTOR: COLLECTOR_NEWS, SUMMARY_MARKET: self.market, "feeds": len(jobs),
                          SUMMARY_FAILED: self.failed, "stale": self.stale, "new_items": written,
                          "skipped_off_watchlist": self.skipped_off_watchlist}, indent=2))
        return 1 if jobs and len(self.failed) == len(jobs) else 0


def main() -> int:
    """Entry point of scripts/collect_news.py."""
    watchlist = require_market(market_arg(__doc__).parse_args())
    return NewsCollector(watchlist).collect()
