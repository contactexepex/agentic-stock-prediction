"""RSS and Atom feed access (feedparser, with the project's User-Agent)."""

from __future__ import annotations

import feedparser

from marketbrief.constants.sources import RSS_USER_AGENT


def fetch_feed(url: str):
    """The feed at `url` parsed by feedparser (its `status`, `bozo` and `entries`)."""
    return feedparser.parse(url, agent=RSS_USER_AGENT)
