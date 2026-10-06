"""Text helpers."""
from __future__ import annotations

import re

_NON_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lower-case `text` with every run of other characters replaced by one '-', trimmed of '-'."""
    return _NON_SLUG_RUN.sub("-", text.lower()).strip("-")


def slugify_with_unknown_fallback(text: str | None) -> str:
    """Like slugify, but None, empty and all-symbol text become 'unknown'."""
    return _NON_SLUG_RUN.sub("-", str(text or "unknown").lower()).strip("-") or "unknown"
