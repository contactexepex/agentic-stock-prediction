"""The one error type of every source client."""

from __future__ import annotations

from marketbrief.constants.statuses import SUMMARY_ALLOWLIST
from marketbrief.constants.columns import COL_SOURCE, COL_URL

ERROR_TEXT_LIMIT = 200
ENTRY_KEY_ERROR = "error"
ENTRY_KEY_STATUS = "status"


class FetchError(Exception):
    """A failed request. status: the HTTP status, or None when there was no HTTP answer;
    host: set when the egress proxy refused the host (it must be allowlisted)."""

    def __init__(self, url: str, error: str, status: int | None = None, host: str | None = None):
        """A fetch error with the URL, status and host."""
        super().__init__(error)
        self.url, self.error, self.status, self.host = url, error, status, host

    def entry(self, source: str, **extra) -> dict:
        """The failure as a summary entry: source, url, error text, and the status and host when known."""
        entry = {COL_SOURCE: source, COL_URL: self.url, ENTRY_KEY_ERROR: self.error[:ERROR_TEXT_LIMIT], **extra}
        if self.status is not None:
            entry[ENTRY_KEY_STATUS] = self.status
        if self.host:
            entry[SUMMARY_ALLOWLIST] = self.host
        return entry
