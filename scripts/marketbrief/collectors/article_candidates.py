"""Which news items the articles collector reads: news rows first seen in the last `lookback_hours`, published
within `max_age_hours`, whose title names a watchlist company as its primary subject with `tag_confidence` at or
above `min_tag_confidence` (marketbrief/analytics/news_tags.py), and whose title matches `material_terms` with
weight >= `min_priority`; highest weight, then allowlist tier, then newest first. Ids already in
data/<market>/news_articles/ are skipped, so a rerun writes nothing twice (one row per news id)."""

from __future__ import annotations

import pandas as pd

from marketbrief.analytics.article_pages import host_of
from marketbrief.analytics.news_sources import Sources
from marketbrief.constants.article_collection import (
    CONFIDENCE_RANK,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_PRIORITY,
)
from marketbrief.constants.articles import GOOGLE_HOST, TIER_RANK, TIER_UNLISTED
from marketbrief.constants.config_keys import CFG_TICKERS

DONE_SQL = "SELECT DISTINCT id FROM news_articles"
NEWS_IN_WINDOW_SQL = (
    "SELECT id, title, url, source, source_domain, feed, published_at, first_seen_at, primary_tickers, "
    "tag_confidence FROM news WHERE first_seen_at >= ? AND first_seen_at <= ? ORDER BY first_seen_at, id"
)


def lookback_start(src: Sources, now: pd.Timestamp) -> pd.Timestamp:
    """The start of this run's collection window (`lookback_hours` before now)."""
    return now - pd.Timedelta(hours=float(src.sel.get("lookback_hours", DEFAULT_LOOKBACK_HOURS)))


def candidates(con, cfg: dict, src: Sources, now: pd.Timestamp) -> list[dict]:
    """The items to read, best first (see the module docstring)."""
    selection = src.sel
    oldest = now - pd.Timedelta(hours=float(selection.get("max_age_hours", DEFAULT_MAX_AGE_HOURS)))
    needed = CONFIDENCE_RANK.get(str(selection.get("min_tag_confidence", DEFAULT_MIN_CONFIDENCE)), 2)
    done = {row[0] for row in con.execute(DONE_SQL).fetchall()}
    rows = con.execute(NEWS_IN_WINDOW_SQL, [lookback_start(src, now).to_pydatetime(), now.to_pydatetime()]).fetchall()
    found = []
    for news_id, title, url, source, source_domain, _feed, published, seen, primary, confidence in rows:
        if news_id in done:
            continue
        tickers = [ticker for ticker in (primary or []) if ticker in cfg[CFG_TICKERS]]
        if not tickers or CONFIDENCE_RANK.get(confidence or "", 0) < needed:
            continue
        stamp = pd.Timestamp(published or seen)
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
        if stamp < oldest:
            continue
        priority = src.priority(title)
        if priority < int(selection.get("min_priority", DEFAULT_MIN_PRIORITY)):
            continue
        host = source_domain or src.domain_of_label(source) or (host_of(url) if host_of(url) != GOOGLE_HOST else None)
        found.append(
            {
                "id": news_id,
                "title": title,
                "url": url,
                "source": source,
                "outlet": host,
                "ticker": tickers[0],
                "priority": priority,
                "ts": stamp,
                "tier": src.tier(host),
            }
        )
    found.sort(
        key=lambda c: (-c["priority"], TIER_RANK.get(c["tier"], TIER_RANK[TIER_UNLISTED]), -c["ts"].value, c["id"])
    )
    return found
