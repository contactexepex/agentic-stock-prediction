"""Golden seed: the fake `feedparser`, `googlenewsdecoder` and article `requests` session."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

from seed_common import FIXTURES, TOPICS, crc, listed_outlets, market_config


class FeedResult(dict):
    """feedparser's result: status, bozo, entries."""

    def __init__(self, entries, status=200, bozo=False):
        super().__init__(status=status)
        self.entries, self.bozo = entries, bozo


def install_feedparser(market: str, now: datetime) -> None:
    """Put the fake `feedparser` module in place."""
    cfg, outlets = market_config(market), listed_outlets()
    tickers = list(cfg["tickers"].items())

    def parse(url: str, agent=None):  # noqa: ARG001
        seed = crc(url)
        if seed % 13 == 0 and url.startswith("https://news.google.com"):
            return FeedResult([], status=503, bozo=True)
        entries = []
        for k in range(4):
            key, meta = tickers[(seed + 7 * k) % len(tickers)]
            title = f"{meta['name']} {TOPICS[(seed // 3 + k) % len(TOPICS)]}"
            label = outlets[(seed + k) % len(outlets)]
            age_hours = (seed >> k) % 50
            if "rss" in url and "markets-106" in url:
                age_hours += 200
            published = (now - timedelta(hours=age_hours)).timetuple()
            entry = {"title": title, "summary": f"<p>{title} says the company.</p>", "published_parsed": published}
            if url.startswith("https://news.google.com"):
                entry.update(title=f"{title} - {label}", source={"title": label, "href": f"https://{label}"},
                             link=f"https://news.google.com/rss/articles/CBMi{crc(title + label):08x}")
            else:
                entry.update(link=f"https://{label}/story/{crc(title):08x}")
            entries.append(entry)
        if "business-standard.com/rss/companies" in url:
            return FeedResult([], status=503, bozo=True)
        return FeedResult(entries)
    module = types.ModuleType("feedparser")
    module.parse = parse
    sys.modules["feedparser"] = module


class FakeResponse:
    """A requests response for an article page."""
    is_redirect = False
    encoding = "utf-8"

    def __init__(self, status: int, body: bytes = b"", location: str | None = None):
        self.status_code, self.body = status, body
        self.headers = {"content-type": "text/html; charset=utf-8", **({"location": location} if location else {})}

    def iter_content(self, size: int):
        """The body in chunks."""
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def close(self) -> None:
        """Nothing to release."""


class FakeSession:
    """A requests session serving the article fixtures by the URL's crc (some 404, some redirects)."""

    def __init__(self):
        self.pages = sorted((FIXTURES / "articles").glob("*.html"))

    def get(self, url: str, **kwargs):  # noqa: ARG002
        """One fake GET."""
        seed = crc(url)
        if url.endswith("/moved"):
            return FakeResponse(200, self.pages[seed % len(self.pages)].read_bytes())
        if seed % 7 == 0:
            return FakeResponse(404)
        if seed % 7 == 1:
            return FakeResponse(301, location=url + "/moved")
        return FakeResponse(200, self.pages[seed % len(self.pages)].read_bytes())

    def close(self) -> None:
        """Nothing to release."""


def install_articles() -> None:
    """The fake session factory and the fake Google News decoder."""
    import marketbrief.sources.article_fetch as article_fetch
    article_fetch.make_session = FakeSession
    outlets = listed_outlets()

    class FakeDecoder:
        """googlenewsdecoder.GoogleDecoder."""

        def __init__(self, **kwargs):  # noqa: ARG002
            self.client = types.SimpleNamespace(event_hooks={})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def decode_google_news_urls(self, links, interval=1):  # noqa: ARG002
            """Most links resolve to an allowlisted page, every fifth fails."""
            out = []
            for link in links:
                seed = crc(link)
                if seed % 5 == 0:
                    out.append({"success": False, "message": "golden: not decoded"})
                else:
                    out.append({"success": True, "decoded_url": f"https://{outlets[seed % len(outlets)]}/n/{seed:08x}"})
            return out
    module = types.ModuleType("googlenewsdecoder")
    module.GoogleDecoder = FakeDecoder
    sys.modules["googlenewsdecoder"] = module
