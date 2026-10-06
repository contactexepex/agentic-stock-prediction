"""The one HTTP client of the scripts: a urllib request loop with pacing, retries and failure hooks.

Every source (free-source collectors, NSE, SEC EDGAR, Neo4j, Slack) is a small subclass that sets an
`HttpPolicy` (timeout, attempts, pause after each attempt, minimum spacing, wait before a retry, which
HTTP statuses and network errors are retried) and turns a final failure into its own error by overriding
`on_http_error` / `on_network_error`. Proxy settings and the CA bundle come from the environment, as for
any urllib call (HTTPS_PROXY, SSL_CERT_FILE)."""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from marketbrief.constants.messages import MSG_UNREACHABLE


def constant_wait(seconds: float) -> Callable[[int], float]:
    """A retry wait that is the same after every failed attempt."""
    return lambda _failed_attempt: seconds


def linear_wait(step_seconds: float) -> Callable[[int], float]:
    """A retry wait that grows by `step_seconds` with each failed attempt (1 step, 2 steps ...)."""
    return lambda failed_attempt: step_seconds * failed_attempt


@dataclass(frozen=True)
class HttpPolicy:
    """How one client talks to its server.

    timeout: seconds per request. attempts: tries per call. pause: seconds slept after every attempt
    (None: no sleep). min_interval: least seconds between the starts of two attempts. retry_wait: seconds to
    sleep after the n-th failed attempt before the next. retry_statuses: HTTP statuses that are retried.
    network_errors: exception types treated as a network failure (retried while attempts remain).
    count_attempts: whether every attempt (not only every call) adds to the client's request count."""

    timeout: float
    attempts: int = 1
    pause: float | None = None
    min_interval: float = 0.0
    retry_wait: Callable[[int], float] = field(default=constant_wait(0.0))
    retry_statuses: tuple[int, ...] = ()
    network_errors: tuple[type[BaseException], ...] = ()
    count_attempts: bool = True


class HttpClient:
    """Sends requests under an HttpPolicy; subclasses override the two failure hooks and read_response."""

    def __init__(self, policy: HttpPolicy, opener: urllib.request.OpenerDirector | None = None):
        """An HTTP client with a policy and an optional opener."""
        self.policy, self.opener = policy, opener
        self.requests = 0
        self._last_attempt_started = 0.0

    def send(self, url: str, *, headers: dict | None = None, data: bytes | None = None,
             method: str | None = None, stream: bool = False):
        """The response body (read_response of the answer), or the open response when `stream`.
        Retries per the policy; a final failure goes to the hooks, which raise (or return a result)."""
        request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        for attempt in range(1, self.policy.attempts + 1):
            is_last = attempt == self.policy.attempts
            self._begin_attempt()
            try:
                return self._exchange(request, stream)
            except urllib.error.HTTPError as exc:
                if exc.code in self.policy.retry_statuses and not is_last:
                    time.sleep(self.policy.retry_wait(attempt))
                    continue
                return self.on_http_error(url, exc)
            except self.policy.network_errors as exc:
                self.on_network_error(url, exc, attempt, is_last)
                time.sleep(self.policy.retry_wait(attempt))
            finally:
                if self.policy.pause is not None:
                    time.sleep(self.policy.pause)
        raise AssertionError(MSG_UNREACHABLE)

    def read_response(self, response):
        """What a successful call returns: the body bytes."""
        return response.read()

    def on_http_error(self, _url: str, exc: urllib.error.HTTPError):
        """A final HTTP error status: raise the client's error (default: the HTTPError itself)."""
        raise exc

    def on_network_error(self, _url: str, exc: BaseException, _attempt: int, _is_last: bool) -> None:
        """A network failure: raise the client's error to stop (always on the last attempt), or return to retry."""
        raise exc

    def _begin_attempt(self) -> None:
        """Wait out the minimum interval since the last attempt started, then count the attempt."""
        if self.policy.min_interval:
            wait = self._last_attempt_started + self.policy.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_attempt_started = time.monotonic()
        if self.policy.count_attempts:
            self.requests += 1

    def _exchange(self, request: urllib.request.Request, stream: bool):
        """One request: open it, then return the response (stream) or read it and close it."""
        opener_open = self.opener.open if self.opener else urllib.request.urlopen
        response = opener_open(request, timeout=self.policy.timeout)
        if stream:
            return response
        with response:
            return self.read_response(response)


def egress_proxy_denied(reason: str, markers: tuple[str, ...]) -> bool:
    """True when a connection failure's text says the egress proxy refused the host."""
    return any(marker in reason for marker in markers)
