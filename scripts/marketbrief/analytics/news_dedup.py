"""News de-duplication (owner decisions Q45-Q47, 2026-10-07; docs/DESIGN.md section 3, "News de-duplication").

One article is stored once per market (India and the US each keep their own copy). Two items are the same article
when, within DEDUP_WINDOW_DAYS of the matched item's newest stored row:
- link: they share the canonical article link (a Google News article URL without its query; a publisher URL without
  tracking parameters, the host prefixes 'www.', 'm.', 'amp.', 'mobile.' and a trailing slash), unless both rows
  name a known outlet (a host) and the outlets differ. A different headline at that link is the same article with
  an edited headline: a headline update, never a new item;
- title: they share the normalised title (news_tags.norm) from the same outlet.
The outlet key of a row is its host without those prefixes, mapped to its allowlisted domain in
config/news_sources.yaml (parent domains too: m.economictimes.com -> economictimes.com) and that domain's
`same_as` (economictimes.com -> economictimes.indiatimes.com); without a host, the domain of a configured outlet
name ('Business Today' -> businesstoday.in) or of a host-like label ('businesstoday.in'); else
'label:<normalised label>', which never matches a different label. The same story from different outlets is never
merged: independent outlets feed the news verification.

Rows are assigned in (first_seen_at, id) order and a row only joins an item stored before it, so no later row
changes an earlier assignment: hiding a duplicate on read never depends on data stored after it. The collector
(collectors/news.py) applies the same index to the stored history before it stores anything; core.database.connect
applies it to every stored row (`news_id_map`, read by the `news` view and the alias views in sql/views.sql).
Standard library only (plus the news-source allowlist), so connect can import it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple
from urllib.parse import urlsplit

from marketbrief.analytics.news_tags import norm
from marketbrief.constants.articles import SOURCE_LABEL_PATTERN
from marketbrief.constants.news import (
    DEDUP_WINDOW_DAYS,
    GOOGLE_NEWS_HOST,
    MATCH_LINK,
    MATCH_TITLE,
    OUTLET_HOST_PREFIXES,
    OUTLET_LABEL_PREFIX,
    TRACKING_PARAMETER,
)

_TRACKING = re.compile(TRACKING_PARAMETER, re.I)
SAME_AS_KEY = "same_as"


def strip_host(host: str | None) -> str:
    """A host in lower case without a port, trailing dot or the outlet prefixes ('amp.scmp.com' -> 'scmp.com');
    a prefix is kept when nothing with a dot would remain."""
    host = (host or "").strip().lower().split(":")[0].strip(".")
    stripped = True
    while stripped:
        stripped = False
        for prefix in OUTLET_HOST_PREFIXES:
            if host.startswith(prefix) and "." in host[len(prefix) :]:
                host, stripped = host[len(prefix) :], True
    return host


class OutletKeys:
    """The outlet key of a row's source label and host (see the module docstring)."""

    def __init__(self, src=None):
        """`src`: the news-source allowlist (news_sources.Sources), or None for host prefixes and labels only."""
        self.src = src
        domains = getattr(src, "domains", {}) or {}
        self.same_as = {
            domain: str(settings[SAME_AS_KEY]).lower()
            for domain, settings in domains.items()
            if settings.get(SAME_AS_KEY)
        }
        self._cache: dict[tuple, str] = {}

    def host_key(self, host: str | None) -> str | None:
        """The outlet key of a host: the allowlisted domain it belongs to (and its `same_as`), else the bare host."""
        host = strip_host(host)
        if not host:
            return None
        listed = self.src.lookup(host)[0] if self.src else None
        domain = listed or host
        return self.same_as.get(domain, domain)

    def key(self, source: str | None, domain: str | None) -> str:
        """The outlet key of a row: its host, else its label (configured name or host-like), else 'label:<label>'."""
        cache_key = (source, domain)
        if cache_key not in self._cache:
            result = self.host_key(domain) if domain else None
            label = (source or "").strip()
            if result is None and label and self.src:
                listed = self.src.domain_of_label(label)
                result = self.same_as.get(listed, listed) if listed else None
            if result is None and label and re.fullmatch(SOURCE_LABEL_PATTERN, label):
                result = self.host_key(label)
            self._cache[cache_key] = result or f"{OUTLET_LABEL_PREFIX}{norm(label)}"
        return self._cache[cache_key]


def known_outlet(key: str) -> bool:
    """True when an outlet key is a host (not a bare label)."""
    return not key.startswith(OUTLET_LABEL_PREFIX)


def same_outlet_possible(first: str, second: str) -> bool:
    """Two rows at one link are one article unless both outlets are known and differ."""
    return first == second or not known_outlet(first) or not known_outlet(second)


def link_key(url: str | None) -> str | None:
    """The canonical article link of a URL (see the module docstring), or None."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = strip_host(parts.hostname)
    if not host:
        return None
    path = (parts.path or "").rstrip("/")
    if host == GOOGLE_NEWS_HOST:
        return f"{host}{path}"
    params = sorted(
        param for param in (parts.query or "").split("&") if param and not _TRACKING.match(param.split("=")[0])
    )
    return f"{host}{path}" + (f"?{'&'.join(params)}" if params else "")


class Sighting(NamedTuple):
    """One stored or collected news row: its id, headline, source label and host, link and when it was seen."""

    news_id: str
    title: str
    source: str | None
    domain: str | None
    url: str | None
    seen_at: datetime | None


@dataclass
class Match:
    """The stored item a row duplicates and the rule that matched."""

    news_id: str
    rule: str


@dataclass
class DuplicateIndex:
    """Links and (title, outlet) keys of the stored items, each with its item's canonical id and the newest
    stored row's time, and the latest headline per item."""

    outlets: OutletKeys
    window: timedelta = timedelta(days=DEDUP_WINDOW_DAYS)
    links: dict[str, list[list]] = field(default_factory=dict)  # link -> [[outlet, canonical id, last seen]]
    titles: dict[tuple, list] = field(default_factory=dict)  # (norm title, outlet) -> [canonical id, last seen]
    headlines: dict[str, tuple] = field(default_factory=dict)  # canonical id -> (seen at, norm title)
    canonical: dict[str, str] = field(default_factory=dict)  # stored id -> canonical id

    def recent(self, last_seen: datetime | None, seen_at: datetime | None) -> bool:
        """True when a key's newest row is within the window before `seen_at` (always when a time is missing)."""
        return last_seen is None or seen_at is None or seen_at - last_seen <= self.window

    def match(self, row: Sighting) -> Match | None:
        """The stored item a row duplicates: the link first (an edited headline is still that article), then the
        title from the same outlet; None for a new article."""
        outlet = self.outlets.key(row.source, row.domain)
        link = link_key(row.url)
        for entry_outlet, news_id, last_seen in self.links.get(link, []) if link else []:
            if same_outlet_possible(entry_outlet, outlet) and self.recent(last_seen, row.seen_at):
                return Match(news_id, MATCH_LINK)
        entry = self.titles.get((norm(row.title), outlet))
        if entry and self.recent(entry[1], row.seen_at):
            return Match(entry[0], MATCH_TITLE)
        return None

    def add(self, row: Sighting, canonical_id: str | None = None) -> str:
        """Register a stored row (canonical_id: the item it duplicates, None for a new item); returns its item."""
        item = self.canonical.setdefault(row.news_id, canonical_id or row.news_id)
        outlet = self.outlets.key(row.source, row.domain)
        link = link_key(row.url)
        seen_at = row.seen_at
        if link:
            entries = self.links.setdefault(link, [])
            for entry in entries:
                if entry[0] == outlet and entry[1] == item:
                    entry[2] = later(entry[2], seen_at)
                    break
            else:
                entries.append([outlet, item, seen_at])
        title_key = (norm(row.title), outlet)
        entry = self.titles.get(title_key)
        if entry and entry[0] == item:
            entry[1] = later(entry[1], seen_at)
        elif entry is None or not self.recent(entry[1], seen_at):
            self.titles[title_key] = [item, seen_at]
        self.note_headline(item, row.title, seen_at)
        return item

    def add_row(self, row: Sighting) -> Match | None:
        """Register a stored row with the item it duplicates (if any) and return that match."""
        found = self.match(row)
        self.add(row, found.news_id if found else None)
        return found

    def note_headline(self, item: str, title: str, seen_at) -> None:
        """Keep an item's headline when it is the newest seen (a tie keeps the later call)."""
        current = self.headlines.get(item)
        if current is None or current[0] is None or seen_at is None or seen_at >= current[0]:
            self.headlines[item] = (seen_at, norm(title))

    def is_new_headline(self, item: str, title: str) -> bool:
        """True when a title differs (normalised) from the item's latest headline."""
        current = self.headlines.get(item)
        return current is None or current[1] != norm(title)


def later(first, second):
    """The later of two times (None counts as unknown)."""
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def assign(rows, outlets: OutletKeys) -> list[tuple[str, str, str | None]]:
    """(id, canonical id, matching rule or None) of stored rows given as (id, title, source, source_domain, url,
    first_seen_at) in (first_seen_at, id) order; an id stored twice keeps its first assignment."""
    index = DuplicateIndex(outlets)
    out = []
    for news_id, title, source, domain, url, seen_at in rows:
        if news_id in index.canonical:
            continue
        found = index.add_row(Sighting(news_id, title or "", source, domain, url, seen_at))
        out.append((news_id, index.canonical[news_id], found.rule if found else None))
    return out


def load_outlet_keys() -> OutletKeys:
    """Outlet keys with the allowlist of config/news_sources.yaml (prefixes and labels only when it is missing)."""
    from marketbrief.analytics.news_sources import load_sources

    try:
        return OutletKeys(load_sources())
    except FileNotFoundError:
        return OutletKeys(None)
