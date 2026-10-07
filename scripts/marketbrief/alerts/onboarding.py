"""Onboarding confirmations (SPEC F9, F8.7): a reply to the Slack command that asked, built from its stored
`command_log` record. B5 (and B1's import) call `post_onboarding_confirmation`."""
from __future__ import annotations

from marketbrief.alerts.constants import LABEL_PAPER_ONLY, MSG_FOOTER, ONBOARDING_RESULT_TEXT, POST_ONBOARDING
from marketbrief.alerts.publish import Message, publisher


def onboarding_text(command: dict) -> str:
    """'Done: Microsoft (NASDAQ, Tech, CIK 0000789019), $1,000 per trade - confirmed. Records: we-us-...'."""
    head = ONBOARDING_RESULT_TEXT.get(command.get("result"), str(command.get("result")))
    body = command.get("message") or command.get("tool") or ""
    lines = [f"{head}: {body}" if body else head]
    if command.get("refusal_code"):
        lines[0] += f" ({command['refusal_code']})"
    if command.get("record_ids"):
        lines.append("Records: " + ", ".join(command["record_ids"]))
    lines.append(f"Request {command['id']} ({command.get('tool')}).")
    lines += [LABEL_PAPER_ONLY, MSG_FOOTER]
    return "\n".join(lines) + "\n"


def onboarding_key(command: dict) -> str:
    """One reply per command and result (a pending reply, then the final one)."""
    return f"{POST_ONBOARDING}:{command.get('market')}:{command['id']}:{command.get('result')}"


def post_onboarding_confirmation(command: dict, channel: str, thread_ts: str, *, dry_run: bool = False,
                                 http=None) -> dict:
    """Reply to the command's Slack message (`channel`, `thread_ts` = the command message's ts) with the
    outcome of its `command_log` record. Idempotent: a second call for the same command and result posts
    nothing. dry_run writes the reply under work/ instead of posting. Returns the publish summary."""
    pub = publisher(command["market"], dry_run=dry_run, http=http, channel=channel)
    msg = Message(kind=POST_ONBOARDING, post_key=onboarding_key(command), text=onboarding_text(command),
                  reply_to=thread_ts)
    return pub.publish(msg)
