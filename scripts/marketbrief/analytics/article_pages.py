"""Fetching an allowlisted article page: URL checks (HTTPS only, allowlisted domain, `fetch: false` outlets never
requested) and a GET that follows redirects by hand so that every hop is checked before it is requested."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from marketbrief.analytics.news_sources import Sources
from marketbrief.constants.articles import (
    CONTENT_TYPE_TEXT_LIMIT,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_REDIRECTS,
    FETCH_ERROR_NETWORK,
    FETCH_ERROR_TEXT_LIMIT,
    FETCH_ERROR_TLS,
    HTTPS,
    HTTPS_PORT,
    MSG_FETCH_ERROR,
    MSG_HTTP_STATUS,
    MSG_NOT_HTML,
    MSG_REDIRECT_NO_LOCATION,
    MSG_TOO_MANY_REDIRECTS,
    MSG_URL_FETCH_FALSE,
    MSG_URL_MISSING,
    MSG_URL_NO_SCHEME,
    MSG_URL_NOT_FETCHED,
    MSG_URL_NOT_HTTPS,
    MSG_URL_NOT_LISTED,
    MSG_URL_OK,
    MSG_URL_PORT,
    READ_CHUNK_BYTES,
    REDIRECT_STATUSES,
)
from marketbrief.sources.article_fetch import get_article_page

AMP_PATH = re.compile(r"/amp(?=/|$)|/amp_articleshow/")
HOST_PREFIXES = ("www.", "m.", "amp.")


def host_of(url: str | None) -> str:
    """The lower-case host of a URL ('' when none)."""
    return (urlsplit(url or "").hostname or "").lower()


def url_check(url: str | None, src: Sources) -> tuple[bool, str, str | None]:
    """(may fetch, reason, allowlisted domain). Only https:// URLs on an allowlisted domain whose
    entry does not say `fetch: false` may be requested."""
    if not url:
        return False, MSG_URL_MISSING, None
    parts = urlsplit(url)
    if parts.scheme != HTTPS:
        return False, MSG_URL_NOT_HTTPS.format(scheme=parts.scheme or MSG_URL_NO_SCHEME), None
    if parts.port not in (None, HTTPS_PORT):
        return False, MSG_URL_PORT.format(port=parts.port), None
    domain, meta = src.lookup(parts.hostname)
    if not domain:
        return False, MSG_URL_NOT_LISTED.format(host=parts.hostname), None
    if meta.get("fetch") is False:
        return False, MSG_URL_NOT_FETCHED.format(domain=domain, why=meta.get("note") or MSG_URL_FETCH_FALSE), domain
    return True, MSG_URL_OK, domain


def canonical_url(url: str | None) -> str | None:
    """https://host/path without query, fragment, 'www.', 'm.' or a trailing slash (dedupe key)."""
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    for prefix in HOST_PREFIXES:
        host = host.removeprefix(prefix)
    path = AMP_PATH.sub(lambda m: "/articleshow/" if "articleshow" in m.group(0) else "", parts.path or "/").rstrip("/")
    return urlunsplit((HTTPS, host, path, "", ""))


class FetchResult:
    """The outcome of fetching one page: status, final URL, HTML (None when not read), error text, the number of
    requests made and why the URL was skipped (never requested)."""

    def __init__(self, status=None, final_url=None, html=None, error=None, requests=0, skipped=None):
        """A fetched article page: status, final URL, HTML, error and request count."""
        self.status, self.final_url, self.html, self.error = status, final_url, html, error
        self.requests, self.skipped = requests, skipped


def request_error(url: str, exc: Exception, requests: int) -> FetchResult:
    """The result of a request that raised (TLS, proxy refusal, timeout): never retried without verification."""
    kind = FETCH_ERROR_TLS if "SSL" in type(exc).__name__ or "certificate" in str(exc).lower() else FETCH_ERROR_NETWORK
    detail = MSG_FETCH_ERROR.format(kind=kind, error_type=type(exc).__name__, detail=str(exc)[:FETCH_ERROR_TEXT_LIMIT])
    return FetchResult(final_url=url, error=detail, requests=requests)


def read_page(response, url: str, selection: dict, requests: int) -> FetchResult:
    """The page of a 200 response (an HTML body of at most `max_bytes`, decoded), or why it is not read."""
    content_type = (response.headers.get("content-type") or "").lower()
    if content_type and "html" not in content_type:
        response.close()
        return FetchResult(
            status=200,
            final_url=url,
            requests=requests,
            error=MSG_NOT_HTML.format(content_type=content_type[:CONTENT_TYPE_TEXT_LIMIT]),
        )
    body, limit = b"", int(selection.get("max_bytes", DEFAULT_MAX_BYTES))
    for chunk in response.iter_content(READ_CHUNK_BYTES):
        body += chunk
        if len(body) >= limit:
            break
    response.close()
    # requests assumes ISO-8859-1 for text/* without a charset; pages are UTF-8 unless they say so
    encoding = response.encoding if "charset=" in content_type and response.encoding else "utf-8"
    return FetchResult(status=200, final_url=url, html=body.decode(encoding, errors="replace"), requests=requests)


def fetch_page(session, url: str, src: Sources) -> FetchResult:
    """GET an allowlisted HTTPS page, following at most `max_redirects` redirects by hand so that
    every hop is checked (HTTPS, allowlisted) before it is requested. TLS verification stays on."""
    selection, requests = src.sel, 0
    for _ in range(int(selection.get("max_redirects", DEFAULT_MAX_REDIRECTS)) + 1):
        allowed, why, _domain = url_check(url, src)
        if not allowed:
            return FetchResult(final_url=url, error=why, requests=requests, skipped=why)
        try:
            requests += 1
            response = get_article_page(session, url, selection)
        except Exception as exc:  # TLS, proxy refusal, timeout
            return request_error(url, exc, requests)
        if response.is_redirect or response.status_code in REDIRECT_STATUSES:
            location = response.headers.get("location")
            response.close()
            if not location:
                return FetchResult(
                    status=response.status_code, final_url=url, error=MSG_REDIRECT_NO_LOCATION, requests=requests
                )
            url = urljoin(url, location)
            continue
        if response.status_code != 200:
            response.close()
            return FetchResult(
                status=response.status_code,
                final_url=url,
                error=MSG_HTTP_STATUS.format(status=response.status_code),
                requests=requests,
            )
        return read_page(response, url, selection, requests)
    return FetchResult(final_url=url, error=MSG_TOO_MANY_REDIRECTS, requests=requests)
