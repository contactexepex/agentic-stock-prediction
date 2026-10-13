"""Link schemes of collected news (issue #478): only https:// links are stored. A press-release wire whose RSS
feed gives http:// links (Business Wire) gets the same link with https:// when its config/news_sources.yaml
domain says `https_links: true`; nothing is requested to do so. Every other link that is not https:// (another
scheme, an http:// link of any other host, an explicit port, credentials in the link, no link) is not stored, so
one such entry never fails the news gate (`validate --stage news_collect`, NEWS_SOURCE) and with it the run."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from marketbrief.constants.articles import HTTPS
from marketbrief.constants.news import HTTPS_LINKS_KEY, NOT_HTTPS_EXAMPLES, NOT_HTTPS_LINK_CHARS

HTTP = "http"


def secure_link(url: str | None, src) -> str | None:
    """The https:// link to store for a feed entry's `url`, or None when it may not be stored. `src` is the
    news-source allowlist (analytics.news_sources.Sources) or None (no upgrades)."""
    parts = urlsplit((url or "").strip())
    if not parts.hostname or parts.username is not None or parts.password is not None:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if parts.scheme == HTTPS:
        return url
    if parts.scheme != HTTP or port not in (None, 80) or src is None:
        return None
    _, meta = src.lookup(parts.hostname)
    if not (meta or {}).get(HTTPS_LINKS_KEY):
        return None
    return urlunsplit((HTTPS, parts.hostname, parts.path, parts.query, parts.fragment))


class LinkGuard:
    """One collection run's link checks: the link to store per entry and the summary counts."""

    def __init__(self, src):
        """`src`: the news-source allowlist, or None when config/news_sources.yaml is missing."""
        self.src = src
        self.skipped: list[dict] = []
        self.upgraded = 0

    def link(self, url: str | None) -> str | None:
        """The https:// link to store for an entry's link, or None (see secure_link)."""
        return secure_link(url, self.src)

    def skip(self, feed: str, url: str | None) -> None:
        """Note an entry not stored because its link is not https:// and cannot be made so."""
        self.skipped.append({"feed": feed, "link": str(url or "")[:NOT_HTTPS_LINK_CHARS]})

    def stored(self, link: str, url: str | None) -> None:
        """Note a stored entry; counts it when its link was rewritten to https://."""
        self.upgraded += link != url

    def summary(self) -> dict:
        """The run summary's link keys."""
        return {
            "skipped_not_https": len(self.skipped),
            "not_https_examples": self.skipped[:NOT_HTTPS_EXAMPLES],
            "upgraded_to_https": self.upgraded,
        }
