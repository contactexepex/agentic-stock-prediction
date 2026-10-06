"""The Neo4j HTTPS Query API v2 client (one auto-commit transaction per statement)."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse

from marketbrief.constants.environment import ENV_NEO4J_RETRY_BACKOFF
from marketbrief.constants.messages import MSG_NEO4J_CONNECTION_FAILED, MSG_NEO4J_HTTP_STATUS
from marketbrief.constants.sources import (NEO4J_DEFAULT_BACKOFF_SECONDS, NEO4J_RETRIES, NEO4J_RETRY_STATUSES,
                                           NEO4J_TIMEOUT_SECONDS)
from marketbrief.sources.http import HttpClient, HttpPolicy, linear_wait

ERROR_TEXT_LIMIT = 300
REDACTED = "***"


class Neo4jError(RuntimeError):
    """A failed Neo4j statement or request; its text never contains the password."""


def error_text(body: str) -> str:
    """The Neo4j error codes and messages of an error body, or the body's first characters."""
    try:
        errors = json.loads(body).get("errors") or []
        return "; ".join(f"{e.get('code', '')}: {e.get('message', '')}"[:ERROR_TEXT_LIMIT]
                         for e in errors) or body[:ERROR_TEXT_LIMIT]
    except (ValueError, AttributeError):
        return body[:ERROR_TEXT_LIMIT]


class Neo4jClient(HttpClient):
    """Minimal client for the Neo4j Query API v2: retries throttled and failed requests with a growing wait."""

    def __init__(self, base_url: str, database: str, credentials: tuple[str, str],
                 timeout: float = NEO4J_TIMEOUT_SECONDS, retries: int = NEO4J_RETRIES, backoff: float | None = None):
        user, password = credentials
        self.base_url, self.database = base_url.rstrip("/"), database
        self.url = f"{self.base_url}/db/{urllib.parse.quote(database, safe='')}/query/v2"
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json",
                         "Accept": "application/json"}
        self._secrets = [s for s in (password, token) if s]
        self.timeout, self.retries = timeout, retries
        self.backoff = (float(os.environ.get(ENV_NEO4J_RETRY_BACKOFF, NEO4J_DEFAULT_BACKOFF_SECONDS))
                        if backoff is None else backoff)
        policy = HttpPolicy(timeout=timeout, attempts=retries + 1, retry_wait=linear_wait(self.backoff),
                            retry_statuses=NEO4J_RETRY_STATUSES,
                            network_errors=(urllib.error.URLError, TimeoutError, ConnectionError, OSError),
                            count_attempts=False)
        super().__init__(policy)

    @property
    def host(self) -> str:
        """The server's host name, for messages."""
        return urllib.parse.urlparse(self.base_url).hostname or "?"

    def redact(self, text: str) -> str:
        """`text` with the password and the Basic-auth token replaced."""
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text

    def run(self, statement: str, parameters: dict | None = None) -> dict:
        """Run one Cypher statement; the response payload, or Neo4jError (also for an `errors` payload)."""
        body = json.dumps({"statement": statement, "parameters": parameters or {}, "includeCounters": True}).encode()
        raw = self.send(self.url, headers=self._headers, data=body, method="POST")
        payload = json.loads(raw.decode() or "{}")
        if payload.get("errors"):
            raise Neo4jError(self.redact(error_text(json.dumps(payload))))
        return payload

    def on_http_error(self, _url: str, exc: urllib.error.HTTPError):
        """The final HTTP error: its Neo4j error text, redacted."""
        detail = error_text(exc.read().decode(errors="replace"))
        raise Neo4jError(self.redact(MSG_NEO4J_HTTP_STATUS.format(code=exc.code, detail=detail))) from None

    def on_network_error(self, _url: str, exc: BaseException, _attempt: int, is_last: bool) -> None:
        """A connection failure: raise on the last attempt, else retry."""
        if is_last:
            reason = getattr(exc, "reason", exc)
            raise Neo4jError(self.redact(MSG_NEO4J_CONNECTION_FAILED.format(reason=reason))) from None
