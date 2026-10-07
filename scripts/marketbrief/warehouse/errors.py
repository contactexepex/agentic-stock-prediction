"""The MotherDuck token and the warehouse's error type, which never carries it.

The token is read from the environment only (MOTHERDUCK_TOKEN). Every warehouse error message goes through
`redact`, which hides the token as is and URL-encoded."""

from __future__ import annotations

import os
import urllib.parse

from marketbrief.constants.environment import ENV_MOTHERDUCK_TOKEN
from marketbrief.constants.warehouse import REDACTED


def token() -> str | None:
    """The MotherDuck token from the environment, None when unset or blank."""
    value = os.environ.get(ENV_MOTHERDUCK_TOKEN, "").strip()
    return value or None


def redact(text) -> str:
    """The text with the token (as is and URL-encoded) replaced by ***."""
    redacted, secret = str(text), token()
    if secret:
        for form in {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}:
            redacted = redacted.replace(form, REDACTED)
    return redacted


class WarehouseError(RuntimeError):
    """A warehouse failure whose message never carries the token."""

    def __init__(self, message: str):
        """Keep only the redacted message."""
        super().__init__(redact(message))
