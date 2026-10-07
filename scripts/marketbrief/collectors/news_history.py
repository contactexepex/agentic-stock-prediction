"""The stored news history the collector de-duplicates against (analytics/news_dedup.py; docs/DESIGN.md section 3,
"News de-duplication"): the rows of the newest DEDUP_LOOKBACK_FILES daily files of `news` and `news_updates`.

The rows are indexed in (first_seen_at, id) order with the same rules the read side applies to every stored row
(core.database.connect -> news_id_map), so an item the collector stores is one the `news` view shows. Rows first
seen after the run's clock (MB_NOW in a test or replay) are left out of the index; their ids still count as stored."""

from __future__ import annotations

import hashlib
from datetime import datetime

from marketbrief.analytics.news_dedup import DuplicateIndex, OutletKeys, Sighting
from marketbrief.analytics.news_tags import norm
from marketbrief.collectors.news_window import parse_utc, recent_rows
from marketbrief.constants.columns import COL_ID, COL_TITLE
from marketbrief.constants.kinds import KIND_NEWS, KIND_NEWS_UPDATES
from marketbrief.constants.news import DEDUP_LOOKBACK_FILES

UPDATE_ID_LENGTH = 16


def stored_index(market: str, now: datetime, outlets: OutletKeys) -> tuple[DuplicateIndex, set[str]]:
    """(the duplicate index of the stored history known by `now`, every stored id of those files)."""
    rows = list(recent_rows(market, KIND_NEWS, files=DEDUP_LOOKBACK_FILES))
    ids = {row[COL_ID] for row in rows}
    timed = [(parse_utc(row.get("first_seen_at")), row) for row in rows]
    timed = sorted(
        ((seen, row) for seen, row in timed if seen is not None and seen <= now),
        key=lambda pair: (pair[0], pair[1][COL_ID]),
    )
    index = DuplicateIndex(outlets)
    for seen, row in timed:
        if row[COL_ID] in index.canonical:
            continue
        title, url = row.get(COL_TITLE) or "", row.get("url")
        index.add_row(Sighting(row[COL_ID], title, row.get("source"), row.get("source_domain"), url, seen))
    stored_updates = recent_rows(market, KIND_NEWS_UPDATES, files=DEDUP_LOOKBACK_FILES)
    updates = [(parse_utc(row.get("seen_at")), row) for row in stored_updates]
    for seen, row in sorted(
        ((seen, row) for seen, row in updates if seen is not None and seen <= now),
        key=lambda pair: (pair[0], pair[1][COL_ID]),
    ):
        item = index.canonical.get(row["news_id"], row["news_id"])
        index.note_headline(item, row.get(COL_TITLE) or "", seen)
    return index, ids


def update_id(news_id: str, title: str, seen_at: str) -> str:
    """The id of a headline update: a hash of the item, the normalised title and when it was seen."""
    return hashlib.sha256(f"{news_id}|{norm(title)}|{seen_at}".encode()).hexdigest()[:UPDATE_ID_LENGTH]


def update_record(news_id: str, row: Sighting, seen_at: str, published, feed: str) -> dict:
    """A news_updates row: the stored item `news_id` seen again at its link with the headline of `row`."""
    return {
        COL_ID: update_id(news_id, row.title, seen_at),
        "news_id": news_id,
        COL_TITLE: row.title,
        "seen_at": seen_at,
        "url": row.url,
        "source": row.source,
        "source_domain": row.domain,
        "published_at": published.isoformat() if published else None,
        "feed": feed,
    }
