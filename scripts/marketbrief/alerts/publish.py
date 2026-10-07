"""Thread handling and idempotent posting. A message is split into parts of at most MAX_MESSAGE_CHARS; each part
is posted once (ledger id <post_key>#<part>). Posts of the day's thread (morning, alerts, close) reply to the
thread's first message, found in the ledger by <market>:<session_date>; the first post of the day starts the
thread. A post outside a thread (weekly) starts its own, and its later parts reply to its first part. A reply
(onboarding) goes to the ts it is given."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from marketbrief.alerts.client import DryRunClient, SlackClient, WebhookClient
from marketbrief.alerts.constants import (
    DRY_RUN_DIR,
    ENV_SLACK_BOT_TOKEN,
    ENV_SLACK_WEBHOOK_URL,
    KIND_SLACK_POSTS,
    METHOD_VERSION,
    POST_BRIEF,
    MSG_NO_CHANNEL,
    MSG_NO_TOKEN,
    SETTING_CHANNEL_ID,
    WORK_DIR,
)
from marketbrief.alerts.ledger import Ledger
from marketbrief.alerts.text import split_message
from marketbrief.core import paths
from marketbrief.core.clock import utc_now
from marketbrief.core.settings import load_settings


class NotConfiguredError(RuntimeError):
    """No token or no channel: nothing can be posted."""


@dataclass
class Message:
    """One post: kind, its idempotency key, the text, and where it goes (the day's thread, or a reply to a ts)."""

    kind: str
    post_key: str
    text: str
    thread_key: str | None = None
    reply_to: str | None = None


class Publisher:
    """Posts messages through a client and records each part in the ledger."""

    def __init__(self, market: str, client, ledger: Ledger, channel: str):
        """client: SlackClient or DryRunClient."""
        self.market, self.client, self.ledger, self.channel = market, client, ledger, channel

    def publish(self, msg: Message) -> dict:
        """Post the parts of `msg` not posted before; returns what was posted and skipped."""
        parts = split_message(msg.text)
        done = self.ledger.parts_of(msg.post_key)
        summary = {"post_key": msg.post_key, "kind": msg.kind, "mode": self.client.mode, "parts": len(parts),
                   "posted": [], "skipped": sorted(f"{msg.post_key}#{n}" for n in done)}
        expected = max((int(r["parts"]) for r in done.values()), default=0)
        if done and (len(done) >= expected or len(parts) != expected):
            summary["thread_ts"] = done[min(done)].get("thread_ts") or done[min(done)]["ts"]
            missing = [n for n in range(1, expected + 1) if n not in done]
            if missing:   # partly posted, and the text now splits differently: left as is, but said so
                summary.update({"incomplete": True, "missing_parts": missing})
            return summary   # posted before (a changed text is not posted again)
        anchor = msg.reply_to or (self.ledger.thread_ts(msg.thread_key) if msg.thread_key else None)
        for number, part in enumerate(parts, 1):
            if number in done:
                anchor = anchor or done[number]["ts"]
                continue
            ts = self.client.post_message(self.channel, part, anchor)
            self.ledger.append(self.row(msg, number, len(parts), part, ts, anchor))
            summary["posted"].append(f"{msg.post_key}#{number}")
            anchor = anchor or ts
        summary["thread_ts"] = anchor
        return summary

    def row(self, msg: Message, number: int, parts: int, text: str, ts: str, thread_ts: str | None) -> dict:
        """The ledger row of one posted part."""
        return {"id": f"{msg.post_key}#{number}", "market": self.market, "kind": msg.kind,
                "post_key": msg.post_key, "part": number, "parts": parts, "thread_key": msg.thread_key,
                "channel": self.channel, "ts": ts, "thread_ts": thread_ts,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text),
                "posted_at": utc_now(), "method_version": METHOD_VERSION}


def dry_run_folder(market: str):
    """work/alerts_dryrun/<market>: the dry run's messages.jsonl and its own ledger."""
    return paths.ROOT / WORK_DIR / DRY_RUN_DIR / market


def publisher(market: str, *, dry_run: bool, http=None, channel: str | None = None, environ=None) -> Publisher:
    """A live publisher (SLACK_BOT_TOKEN, the channel of config/settings.yaml, the data/ ledger); without the token
    the webhook fallback (SLACK_WEBHOOK_URL: unthreaded messages, same ledger); or a dry-run one (messages and
    ledger under work/). Raises NotConfiguredError when a live run has neither, or the token but no channel."""
    environ = os.environ if environ is None else environ
    channel = channel or (load_settings() or {}).get(SETTING_CHANNEL_ID)
    if dry_run:
        folder = dry_run_folder(market)
        return Publisher(market, DryRunClient(folder), Ledger(folder / KIND_SLACK_POSTS), channel or "dry-run")
    token, hook = environ.get(ENV_SLACK_BOT_TOKEN), environ.get(ENV_SLACK_WEBHOOK_URL)
    ledger = Ledger(paths.data_dir(market) / KIND_SLACK_POSTS)
    if not token and hook:
        return Publisher(market, WebhookClient(hook, http), ledger, channel or "webhook")
    if not token:
        raise NotConfiguredError(MSG_NO_TOKEN)
    if not channel:
        raise NotConfiguredError(MSG_NO_CHANNEL)
    return Publisher(market, SlackClient(token, http), ledger, channel)


def post_brief(market: str, session_date: str, text: str, *, dry_run: bool = False, http=None) -> dict:
    """notify_slack.py's daily brief in the day's thread (one thread per market per day, owner 2026-10-07): a reply
    to the thread the morning picks started, or the thread's first message when it is the day's first post (later
    posts then reply to it). Posted once per market and day; the summary's thread_ts is where notify_slack.py
    uploads its charts, report and dashboard."""
    msg = Message(POST_BRIEF, f"{POST_BRIEF}:{market}:{session_date}", text, f"{market}:{session_date}")
    return publisher(market, dry_run=dry_run, http=http).publish(msg)
