"""Article-page access: the `requests` session, its one GET and the pacing between article fetches.

The session trusts the environment's proxy and REQUESTS_CA_BUNDLE; TLS verification is always on."""

from __future__ import annotations

import time

from marketbrief.constants.sources import ACCEPT_HTML_PAGES, ACCEPT_LANGUAGE_US, ARTICLE_DEFAULT_USER_AGENT


def make_session():
    """A `requests` session (trust_env: the proxy and REQUESTS_CA_BUNDLE from the environment)."""
    import requests

    return requests.Session()


def get_article_page(session, url: str, selection: dict):
    """One streamed GET of an article page without following redirects (the caller checks every hop)."""
    return session.get(
        url,
        allow_redirects=False,
        stream=True,
        timeout=float(selection.get("timeout_seconds", 20)),
        headers={
            "User-Agent": selection.get("user_agent", ARTICLE_DEFAULT_USER_AGENT),
            "Accept": ACCEPT_HTML_PAGES,
            "Accept-Language": ACCEPT_LANGUAGE_US,
        },
        verify=True,
    )


class Pacer:
    """Keeps at least `pause` seconds between two article fetches."""

    def __init__(self, pause: float):
        """The fetcher's pause between requests."""
        self.pause, self.last = pause, 0.0

    def wait(self):
        """Sleep until `pause` seconds have passed since the last call returned."""
        elapsed = time.monotonic() - self.last
        if self.last and elapsed < self.pause:
            time.sleep(self.pause - elapsed)
        self.last = time.monotonic()
