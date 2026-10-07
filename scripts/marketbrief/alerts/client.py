"""Posting one Slack message: the live Web API client (bot token from SLACK_BOT_TOKEN, as notify_slack.py) and
the dry-run client that writes the messages to a file under work/ instead. The token is only ever put in the
Authorization header; no error, log line or file contains it."""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from marketbrief.alerts.constants import DRY_RUN_TS_PREFIX, SLACK_API
from marketbrief.constants.files import ENCODING_UTF8
from marketbrief.core.storage import append_jsonl
from marketbrief.sources.slack_client import SlackHttp


class SlackError(RuntimeError):
    """A refused or failed Web API call (method and Slack's error code only)."""


def default_http(url: str, data: bytes, headers: dict) -> tuple[int, bytes]:
    """POST through the shared Slack HTTP client; replaced by a fake in tests."""
    return SlackHttp().post(url, data, headers)


class SlackClient:
    """chat.postMessage with a bot token (scope chat:write; the bot must be a channel member)."""

    mode = "live"

    def __init__(self, token: str, http=None):
        """`http(url, data, headers) -> (status, body)`."""
        self._token = token
        self.http = http or default_http

    def __repr__(self) -> str:
        """Never shows the token."""
        return "SlackClient(token=***)"

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> str:
        """Post `text` (a reply when thread_ts is set); returns the new message's ts."""
        form = {"channel": channel, "text": text, "thread_ts": thread_ts, "unfurl_links": "false",
                "unfurl_media": "false"}
        body = urllib.parse.urlencode({k: v for k, v in form.items() if v is not None}).encode()
        status, raw = self.http(SLACK_API + "chat.postMessage", body,
                                {"Authorization": f"Bearer {self._token}",
                                 "Content-Type": "application/x-www-form-urlencoded"})
        try:
            out = json.loads(raw.decode() or "{}")
        except ValueError:
            raise SlackError(f"chat.postMessage: HTTP {status}, answer not JSON") from None
        if status != 200 or not out.get("ok") or not out.get("ts"):
            raise SlackError(f"chat.postMessage: {out.get('error') or f'HTTP {status}'}")
        return str(out["ts"])


class DryRunClient:
    """Writes each message to <folder>/messages.jsonl and returns a made-up ts (dry.000001, ...)."""

    mode = "dry_run"

    def __init__(self, folder: Path):
        """`folder` = work/alerts_dryrun/<market>."""
        self.file = folder / "messages.jsonl"

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> str:
        """Record the message instead of posting it."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        count = len(self.file.read_text(encoding=ENCODING_UTF8).splitlines()) if self.file.exists() else 0
        ts = f"{DRY_RUN_TS_PREFIX}.{count + 1:06d}"
        append_jsonl(self.file, [{"ts": ts, "channel": channel, "thread_ts": thread_ts, "text": text}])
        return ts
