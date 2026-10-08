"""Invalidate the app's cached pages after a sync commits (docs/ARCHITECTURE.md section 7): POST the changed and
deleted keys of the build to the app's /api/v1/internal/revalidate (web/lib/data/revalidate.ts) with
REVALIDATE_SECRET and, to pass Vercel Authentication, VERCEL_AUTOMATION_BYPASS_SECRET. Neither value is ever
printed or put into a URL. Non-blocking: the outcome is a line of the sync summary (`revalidate`), never an error.
Skipped for the local warehouse file, a dry run, no changed key, or without REVALIDATE_SECRET."""

from __future__ import annotations

import http.client
import json
import os
import urllib.error

from marketbrief.constants.warehouse import (
    ENV_REVALIDATE_SECRET,
    ENV_VERCEL_BYPASS,
    MSG_REVALIDATE_FAILED,
    MSG_REVALIDATE_NO_SECRET,
    REVALIDATE_BATCH,
    REVALIDATE_PATH,
    REVALIDATE_TIMEOUT_SECONDS,
)
from marketbrief.sources.http import HttpClient, HttpPolicy


class RevalidateHttp(HttpClient):
    """One POST per batch; a final failure becomes a status code (or 0 for a network failure)."""

    def __init__(self, opener=None):
        super().__init__(HttpPolicy(timeout=REVALIDATE_TIMEOUT_SECONDS, attempts=1), opener)

    def read_response(self, response) -> int:
        return response.status

    def on_http_error(self, _url: str, exc: urllib.error.HTTPError) -> int:
        return exc.code

    def on_network_error(self, _url: str, exc: BaseException, _attempt: int, _is_last: bool) -> None:
        raise ConnectionError(type(exc).__name__) from None


def secret(name: str) -> str | None:
    """An environment secret, None when unset or blank."""
    value = os.environ.get(name, "").strip()
    return value or None


def revalidate(app_url: str, build_id: str, keys: list[dict], opener=None) -> str:
    """POST the keys in batches; the summary line (`ok: N keys` or why it was skipped or failed)."""
    if not keys:
        return "skipped: no page changed"
    key = secret(ENV_REVALIDATE_SECRET)
    if key is None:
        return MSG_REVALIDATE_NO_SECRET.format(env=ENV_REVALIDATE_SECRET)
    headers = {"Content-Type": "application/json", "X-Revalidate-Secret": key}
    bypass = secret(ENV_VERCEL_BYPASS)
    if bypass:
        headers["x-vercel-protection-bypass"] = bypass
    client = RevalidateHttp(opener)
    for start in range(0, len(keys), REVALIDATE_BATCH):
        body = json.dumps({"build_id": build_id, "keys": keys[start : start + REVALIDATE_BATCH]}).encode()
        try:
            status = client.send(app_url.rstrip("/") + REVALIDATE_PATH, headers=headers, data=body, method="POST")
        except (ConnectionError, OSError, http.client.HTTPException) as exc:
            return MSG_REVALIDATE_FAILED.format(reason=type(exc).__name__)
        if status != 200:
            return MSG_REVALIDATE_FAILED.format(reason=f"HTTP {status}")
    return f"ok: {len(keys)} keys"
