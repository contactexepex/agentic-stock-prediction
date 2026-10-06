"""The HTTP POST behind the Slack Web API and incoming webhooks: one attempt, no retry."""
from __future__ import annotations

import urllib.error

from marketbrief.constants.sources import SLACK_TIMEOUT_SECONDS
from marketbrief.sources.http import HttpClient, HttpPolicy


class SlackHttp(HttpClient):
    """POSTs data and returns (status, body); an HTTP error status is an answer, not an exception."""

    def __init__(self):
        """A Slack client with its timeout policy."""
        super().__init__(HttpPolicy(timeout=SLACK_TIMEOUT_SECONDS))

    def post(self, url: str, data: bytes, headers: dict) -> tuple[int, bytes]:
        """POST `data` to `url`; returns (status, body). Network errors propagate."""
        return self.send(url, headers=headers, data=data, method="POST")

    def read_response(self, response) -> tuple[int, bytes]:
        """The status and body of a successful answer."""
        return response.status, response.read()

    def on_http_error(self, _url: str, exc: urllib.error.HTTPError) -> tuple[int, bytes]:
        """An error status and its body are returned like any answer."""
        return exc.code, exc.read()
