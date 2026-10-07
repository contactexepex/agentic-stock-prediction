"""Column types of the Slack post ledger (B6; docs/ws/b6.md)."""
from __future__ import annotations

from marketbrief.alerts.constants import KIND_SLACK_POSTS

ALERTS_SCHEMAS = {
    # One row per posted message part (alerts.py), in the day file of posted_at. id = <post_key>#<part>;
    # post_key = <kind>:<market>:<day or check id or iso week or command id[:result]>; kind morning | alerts |
    # close | weekly | onboarding. thread_key = <market>:<session_date> for the day's thread (morning, alerts,
    # close), else null. ts = the Slack message ts; thread_ts = the thread it replies to (null for a thread's
    # first message). text_sha256 and chars describe the text posted; the text itself is rebuilt from data.
    KIND_SLACK_POSTS: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "kind": "VARCHAR", "post_key": "VARCHAR", "part": "INTEGER",
        "parts": "INTEGER", "thread_key": "VARCHAR", "channel": "VARCHAR", "ts": "VARCHAR",
        "thread_ts": "VARCHAR", "text_sha256": "VARCHAR", "chars": "INTEGER", "posted_at": "TIMESTAMPTZ",
        "method_version": "VARCHAR",
    }),
}
