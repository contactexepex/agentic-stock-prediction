"""The NSE (National Stock Exchange of India) client.

NSE serves its JSON only to browser-like clients: one session per run loads the home page for its
cookies, then calls /api/... with a Referer, pausing between requests. Files on nsearchives.nseindia.com
(XBRL filings, CSV reports) are fetched through the same session. With `replay`, responses come from
local files instead of the network (an API call reads <endpoint>[_<symbol>][_<optionType>].json, an
archive file reads its base name)."""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from marketbrief.constants.messages import (MSG_NSE_HTTP_STATUS, MSG_NSE_NO_REPLAY_FILE, MSG_NSE_NOT_JSON,
                                            MSG_NSE_PROXY_DENIED, MSG_NSE_UNREACHABLE)
from marketbrief.constants.sources import (ACCEPT_HTML_PAGES, ACCEPT_LANGUAGE_NSE, NSE_ARCHIVES_HOST,
                                           NSE_ARCHIVES_URL, NSE_ATTEMPTS, NSE_BASE_URL,
                                           NSE_DEFAULT_PAUSE_SECONDS, NSE_REFERER_PAGES, NSE_RETRY_WAIT_SECONDS,
                                           NSE_TIMEOUT_SECONDS, NSE_USER_AGENT, PROXY_TUNNEL_FAILURE)
from marketbrief.sources.errors import FetchError
from marketbrief.sources.http import HttpClient, HttpPolicy, constant_wait, egress_proxy_denied

ACCEPT_JSON = "application/json, text/plain, */*"
ACCEPT_ARCHIVE = "text/csv,application/xml,*/*"
PROXY_DENIAL_MARKERS = (PROXY_TUNNEL_FAILURE, "403")   # the proxy's refusal shows as a tunnel failure or a 403


class Nse(HttpClient):
    """Minimal NSE client: one cookie session, browser headers, polite pacing."""

    def __init__(self, base: str = NSE_BASE_URL, archives: str = NSE_ARCHIVES_URL, replay: Path | None = None,
                 pause: float = NSE_DEFAULT_PAUSE_SECONDS):
        """An NSE client with its base URLs and an optional replay folder."""
        policy = HttpPolicy(timeout=NSE_TIMEOUT_SECONDS, attempts=NSE_ATTEMPTS, pause=pause,
                            retry_wait=constant_wait(NSE_RETRY_WAIT_SECONDS),
                            network_errors=(urllib.error.URLError, OSError))
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        super().__init__(policy, opener=opener)
        self.base, self.archives, self.replay = base.rstrip("/"), archives.rstrip("/"), replay
        self.warm_error: FetchError | None = None
        self.warmed = False

    def _open(self, url: str, accept: str, referer: str | None = None) -> bytes:
        """One browser-like GET (one retry for transient network errors: TLS EOF, reset, timeout)."""
        headers = {"User-Agent": NSE_USER_AGENT, "Accept": accept, "Accept-Language": ACCEPT_LANGUAGE_NSE}
        if referer:
            headers["Referer"] = referer
        return self.send(url, headers=headers)

    def on_http_error(self, url: str, exc: urllib.error.HTTPError):
        """An HTTP error status is final: no retry."""
        host = urllib.parse.urlsplit(url).hostname
        raise FetchError(url, MSG_NSE_HTTP_STATUS.format(code=exc.code, host=host)) from exc

    def on_network_error(self, url: str, exc: BaseException, _attempt: int, is_last: bool) -> None:
        """Raise at once when the egress proxy refuses the host (every later call fails the same way),
        and on the last attempt; otherwise retry."""
        host = urllib.parse.urlsplit(url).hostname
        reason = str(getattr(exc, "reason", exc))
        if egress_proxy_denied(reason, PROXY_DENIAL_MARKERS):
            raise FetchError(url, MSG_NSE_PROXY_DENIED.format(host=host, reason=reason), host=host) from exc
        if is_last:
            raise FetchError(url, MSG_NSE_UNREACHABLE.format(host=host, reason=reason)) from exc

    def _warm(self) -> None:
        """Load the home page once for its cookies; fail fast when the host is not reachable at all."""
        if not self.warmed:
            self.warmed = True
            try:
                self._open(self.base + "/", ACCEPT_HTML_PAGES)
            except FetchError as exc:
                self.warm_error = exc
        if self.warm_error and self.warm_error.host:   # host not reachable at all: fail fast
            raise self.warm_error

    def json(self, endpoint: str, params: dict | None = None):
        """An /api/<endpoint> call parsed as JSON (or the replay file's content)."""
        params = params or {}
        if self.replay:
            keys = [params[k] for k in ("symbol", "optionType") if params.get(k)]
            return self._replay("_".join([endpoint.rsplit("/", 1)[-1], *keys]) + ".json", json.loads)
        url = f"{self.base}/api/{endpoint}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        self._warm()
        referer = self.base + NSE_REFERER_PAGES.get(endpoint.rsplit("/", 1)[-1], "/")
        try:
            return json.loads(self._open(url, ACCEPT_JSON, referer))
        except json.JSONDecodeError as exc:
            raise FetchError(url, MSG_NSE_NOT_JSON.format(error=exc)) from exc

    def text(self, path_or_url: str) -> str:
        """An archive file by path (/content/...) or by its full nsearchives URL."""
        path = path_or_url.split(NSE_ARCHIVES_HOST, 1)[-1] if NSE_ARCHIVES_HOST in path_or_url else path_or_url
        if self.replay:
            return self._replay(path.rsplit("/", 1)[-1], lambda content: content)
        return self._open(self.archives + path, ACCEPT_ARCHIVE, self.base + "/").decode("utf-8", "replace")

    def _replay(self, name: str, parse):
        """A replay file's text through `parse`; FetchError when the file is missing."""
        file = self.replay / name
        if not file.exists():
            raise FetchError(f"replay:{name}", MSG_NSE_NO_REPLAY_FILE)
        return parse(file.read_text(encoding="utf-8"))
