"""The MotherDuck token and the warehouse's error type, which never carries it.

The warehouse token is read from the environment only (MOTHERDUCK_TOKEN). Every warehouse error message goes
through `redact`, which hides that token, and any other token a caller passed in (e.g. the inbox's), as is and
URL-encoded."""

from __future__ import annotations

import os
import urllib.parse

from marketbrief.constants.environment import ENV_MOTHERDUCK_TOKEN
from marketbrief.constants.warehouse import REDACTED


def token() -> str | None:
    """The MotherDuck token from the environment, None when unset or blank."""
    value = os.environ.get(ENV_MOTHERDUCK_TOKEN, "").strip()
    return value or None


def redact(text, other_secrets: tuple[str, ...] = ()) -> str:
    """The text with the warehouse token and `other_secrets` (as is and URL-encoded) replaced by ***."""
    redacted = str(text)
    for secret in (token(), *other_secrets):
        if secret:
            for form in {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}:
                redacted = redacted.replace(form, REDACTED)
    return redacted


class WarehouseError(RuntimeError):
    """A warehouse failure whose message never carries the token."""

    def __init__(self, message: str, other_secrets: tuple[str, ...] = ()):
        """Keep only the message with every token redacted."""
        super().__init__(redact(message, other_secrets))
