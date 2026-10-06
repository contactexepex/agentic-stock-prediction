"""The polite client of the free-source collectors (macro, short selling, India flows).

An identifying User-Agent, a pause between requests, up to two retries on a transient network error and
none on an HTTP error. Errors are classified so a summary can say what happened: an HTTP status from the
site, the egress proxy refusing the host (the host to allowlist), or the site closing the connection
without an answer (a site-side refusal). After a host refuses or drops a connection, later calls to the
same host in that run fail at once instead of waiting for the same answer again."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse

from marketbrief.constants.messages import (
    MSG_FREE_SOURCE_CLOSED,
    MSG_FREE_SOURCE_DEAD_CLOSED,
    MSG_FREE_SOURCE_DEAD_PROXY,
    MSG_FREE_SOURCE_HOST_SKIPPED,
    MSG_FREE_SOURCE_HTTP_STATUS,
    MSG_FREE_SOURCE_NOT_JSON,
    MSG_FREE_SOURCE_PROXY_DENIED,
    MSG_FREE_SOURCE_UNREACHABLE,
)
from marketbrief.constants.sources import (
    ACCEPT_ANY,
    ACCEPT_LANGUAGE_US,
    CONNECTION_CLOSED_MARKERS,
    FREE_SOURCE_ATTEMPTS,
    FREE_SOURCE_BACKOFF_SECONDS,
    FREE_SOURCE_PAUSE_SECONDS,
    FREE_SOURCE_TIMEOUT_SECONDS,
    FREE_SOURCE_USER_AGENT,
    PROXY_TUNNEL_FAILURE,
)
from marketbrief.sources.errors import FetchError
from marketbrief.sources.http import HttpClient, HttpPolicy, constant_wait, egress_proxy_denied

JSON_PREVIEW_CHARS = 80


class FreeSourceClient(HttpClient):
    """One client per run: paced requests with retries on transient network errors and dead-host memory."""

    def __init__(
        self,
        pause: float = FREE_SOURCE_PAUSE_SECONDS,
        user_agent: str = FREE_SOURCE_USER_AGENT,
        timeout: float = FREE_SOURCE_TIMEOUT_SECONDS,
        attempts: int = FREE_SOURCE_ATTEMPTS,
        backoff: float = FREE_SOURCE_BACKOFF_SECONDS,
    ):
        # 3 attempts: fred.stlouisfed.org sometimes closes a connection without answering and
        # serves the same URL on the next try (seen 2026-10-05)
        """A client for the free sources with its pause and user agent."""
        policy = HttpPolicy(
            timeout=timeout,
            attempts=attempts,
            pause=pause,
            retry_wait=constant_wait(backoff),
            network_errors=(urllib.error.URLError, OSError, http.client.HTTPException),
        )
        super().__init__(policy)
        self.user_agent = user_agent
        self.dead_hosts: dict[str, str] = {}  # host -> why later calls to it are skipped this run

    def get(self, url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
        """The body of a URL (POST when `data` is given); a FetchError describes any failure."""
        host = urllib.parse.urlsplit(url).hostname or ""
        if host in self.dead_hosts:
            raise FetchError(url, MSG_FREE_SOURCE_HOST_SKIPPED.format(host=host, why=self.dead_hosts[host]))
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": ACCEPT_ANY,
            "Accept-Language": ACCEPT_LANGUAGE_US,
            **(headers or {}),
        }
        return self.send(url, headers=request_headers, data=data)

    def json(self, url: str, **kw):
        """A URL's body parsed as JSON."""
        body = self.get(url, **kw)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise FetchError(url, MSG_FREE_SOURCE_NOT_JSON.format(preview=body[:JSON_PREVIEW_CHARS])) from exc

    def on_http_error(self, url: str, exc: urllib.error.HTTPError):
        """An HTTP error status is final: no retry."""
        host = urllib.parse.urlsplit(url).hostname or ""
        raise FetchError(url, MSG_FREE_SOURCE_HTTP_STATUS.format(code=exc.code, host=host), status=exc.code) from exc

    def on_network_error(self, url: str, exc: BaseException, attempt: int, is_last: bool) -> None:
        """Raise for a proxy refusal at once, and for any failure on the last attempt; else retry."""
        host = urllib.parse.urlsplit(url).hostname or ""
        reason = str(getattr(exc, "reason", exc))
        if egress_proxy_denied(reason, (PROXY_TUNNEL_FAILURE,)):
            self.dead_hosts[host] = MSG_FREE_SOURCE_DEAD_PROXY
            raise FetchError(url, MSG_FREE_SOURCE_PROXY_DENIED.format(host=host, reason=reason), host=host) from exc
        if not is_last:
            return
        if any(marker in repr(exc) for marker in CONNECTION_CLOSED_MARKERS):
            self.dead_hosts[host] = MSG_FREE_SOURCE_DEAD_CLOSED
            raise FetchError(url, MSG_FREE_SOURCE_CLOSED.format(host=host, attempts=attempt, reason=reason)) from exc
        raise FetchError(url, MSG_FREE_SOURCE_UNREACHABLE.format(host=host, attempts=attempt, reason=reason)) from exc
