#!/usr/bin/env python3
"""Post the day's brief to Slack #market-brief as a thread.

With SLACK_BOT_TOKEN set (bot scopes chat:write and files:write; the bot must be a member of
the channel `slack_channel_id` in config/settings.yaml), it posts:
  1. the filled summary draft work/slack_<market>.md into the day's #market-brief thread through B6's
     marketbrief.alerts.publish.post_brief: a reply when alerts.py morning started the thread, else the thread's
     first message; once per market and session (data/<market>/slack_posts/); a --text message (market closed) is
     posted on its own;
  2. the chart images as one reply, then 3. the HTML report as a file reply, then 4. the
     dashboard (reports/<market>/dashboard.html) as a file reply when dashboard.py listed it, each
     through files.getUploadURLExternal -> upload to the returned URL -> files.completeUploadExternal
     with channel_id and thread_ts. The files come from work/slack_<market>_files.json
     (written by html_report.py, the dashboard key added by dashboard.py); without it only the
     summary is posted, with a warning.
Without the token it falls back to one text message through the incoming webhook in
SLACK_WEBHOOK_URL (hooks.slack.com). --dry-run posts nothing: it writes the planned thread to
work/slack_<market>_plan.json and copies the files it would upload to work/slack_<market>_plan/.
Refuses a draft that still contains AGENT markers. Exit codes: 0 posted (or dry run), 2 no
token and no webhook configured, 1 error."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.parse
from pathlib import Path

from marketbrief.core.cli import market_arg, require_market
from marketbrief.core import paths
from marketbrief.core.settings import load_settings
from marketbrief.alerts.client import SlackError as AlertsSlackError
from marketbrief.alerts.publish import NotConfiguredError, post_brief
from marketbrief.pipeline.market_status import status as market_status
from marketbrief.core.clock import clock
from marketbrief.sources.slack_client import SlackHttp

API = "https://slack.com/api/"
MIME = {".png": "image/png", ".html": "text/html"}


def clean(text: str) -> str:
    # an unfilled optional failures line is dropped; any other marker is an error
    lines = [l for l in text.splitlines() if not l.strip().startswith("<!-- AGENT:failures")]
    return "\n".join(lines).strip() + "\n"


def urllib_http(url: str, data: bytes, headers: dict) -> tuple[int, bytes]:
    """POST data to url; returns (status, body). Replaced by a fake in tests."""
    return SlackHttp().post(url, data, headers)


class SlackError(RuntimeError):
    pass


class Slack:
    """The three Web API methods the thread needs (bot token, chat:write + files:write)."""

    def __init__(self, token: str, http=urllib_http):
        self.token, self.http = token, http
        self.calls: list[str] = []

    def api(self, method: str, form: dict) -> dict:
        self.calls.append(method)
        body = urllib.parse.urlencode({k: v for k, v in form.items() if v is not None}).encode()
        status, raw = self.http(API + method, body, {"Authorization": f"Bearer {self.token}",
                                                     "Content-Type": "application/x-www-form-urlencoded"})
        try:
            out = json.loads(raw.decode() or "{}")
        except ValueError:
            raise SlackError(f"{method}: HTTP {status}, not JSON: {raw[:120]!r}") from None
        if status != 200 or not out.get("ok"):
            raise SlackError(f"{method}: {out.get('error') or f'HTTP {status}'}")
        return out

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> str:
        out = self.api("chat.postMessage", {"channel": channel, "text": text, "thread_ts": thread_ts,
                                            "unfurl_links": "false", "unfurl_media": "false"})
        return out["ts"]

    def upload(self, path: Path, title: str) -> str:
        data = path.read_bytes()
        got = self.api("files.getUploadURLExternal", {"filename": path.name, "length": str(len(data))})
        self.calls.append("upload")
        status, raw = self.http(got["upload_url"], data,
                                {"Content-Type": MIME.get(path.suffix, "application/octet-stream")})
        if status != 200:
            raise SlackError(f"upload of {path.name}: HTTP {status} {raw[:120]!r}")
        return got["file_id"]

    def share(self, files: list[tuple[str, str]], channel: str, thread_ts: str, comment: str) -> None:
        self.api("files.completeUploadExternal", {
            "files": json.dumps([{"id": i, "title": t} for i, t in files]),
            "channel_id": channel, "thread_ts": thread_ts, "initial_comment": comment})


def thread_plan(text: str, files: dict | None, root: Path = paths.ROOT) -> list[dict]:
    """The thread in posting order: summary, chart images (one reply), HTML report (one reply)."""
    steps = [{"step": "summary", "method": "chat.postMessage", "text": text}]
    if not files:
        return steps
    images = [root / p for p in files.get("images", []) if (root / p).exists()]
    if images:
        steps.append({"step": "charts", "method": "files.completeUploadExternal",
                      "comment": "Charts for today (tap to enlarge).",
                      "files": [{"path": str(p.relative_to(root)), "title": title_of(p)} for p in images]})
    html = root / files["html"] if files.get("html") else None
    if html is not None and html.exists():
        steps.append({"step": "report", "method": "files.completeUploadExternal",
                      "comment": "Full report: download and open in any browser. Filter by sector or company.",
                      "files": [{"path": str(html.relative_to(root)), "title": f"Report {html.stem}"}]})
    board = root / files["dashboard"] if files.get("dashboard") else None   # added by dashboard.py
    if board is not None and board.exists():
        steps.append({"step": "dashboard", "method": "files.completeUploadExternal",
                      "comment": "Dashboard: every stock's chart, ranges, model probability with its reasons, "
                                 "and the track record. Opens offline in any browser. Research only.",
                      "files": [{"path": str(board.relative_to(root)), "title": "Dashboard"}]})
    return steps


def title_of(p: Path) -> str:
    return {"ranges": "Price ranges", "sectors": "Sector moves", "track_record": "Track record"}.get(p.stem, p.stem)


def post_thread(slack: Slack, channel: str, steps: list[dict], root: Path = paths.ROOT,
                market: str | None = None, session_date: str | None = None) -> dict:
    """Post the summary, then the files as replies. With a market and session the summary goes into the day's
    #market-brief thread through B6's post_brief (a reply when alerts.py morning posted first, else the thread's
    first message; once per market and day, recorded in data/<market>/slack_posts/)."""
    if market and session_date:
        brief = post_brief(market, session_date, steps[0]["text"], http=slack.http)
        slack.calls += ["chat.postMessage"] * len(brief["posted"])
        ts = brief["thread_ts"]
    else:
        ts = slack.post_message(channel, steps[0]["text"])
    done = ["summary"]
    for s in steps[1:]:
        ids = [(slack.upload(root / f["path"], f["title"]), f["title"]) for f in s["files"]]
        slack.share(ids, channel, ts, s["comment"])
        done.append(s["step"])
    return {"thread_ts": ts, "posted": done}


def write_plan(market: str, channel: str | None, steps: list[dict], root: Path = paths.ROOT) -> str:
    plan = root / "work" / f"slack_{market}_plan.json"
    folder = root / "work" / f"slack_{market}_plan"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for s in steps:
        for f in s.get("files", []):
            shutil.copy(root / f["path"], folder / Path(f["path"]).name)
            f["bytes"] = (root / f["path"]).stat().st_size
    plan.write_text(json.dumps({"channel_id": channel, "thread": steps}, indent=2, ensure_ascii=False))
    return str(plan.relative_to(root))


def webhook_post(url: str, text: str, http=urllib_http) -> tuple[bool, str]:
    status, raw = http(url, json.dumps({"text": text}).encode(), {"Content-Type": "application/json"})
    body = raw.decode(errors="replace")[:200]
    return status == 200 and body == "ok", body


def main(argv: list[str] | None = None, http=urllib_http) -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="post nothing; write the planned thread and its files to work/")
    ap.add_argument("--text", help="post this one line instead of the draft (e.g. the market-closed message)")
    args = ap.parse_args(argv)
    cfg = require_market(args)
    market = cfg["market"]
    path = paths.ROOT / "work" / f"slack_{market}.md"
    if args.text:
        text = args.text.strip() + "\n"
    elif not path.exists():
        print(json.dumps({"step": "notify", "error": f"{path} not found; run report.py first"}))
        return 1
    else:
        text = clean(path.read_text())
    if re.search(r"<!--\s*AGENT:", text):
        print(json.dumps({"step": "notify", "error": "draft still has AGENT markers; fill them first"}))
        return 1
    out: dict = {"step": "notify"}
    if len(text.splitlines()) > 12:
        out["warning"] = "draft longer than 12 lines"
    settings = load_settings()
    channel = settings.get("slack_channel_id")
    files = None
    mpath = paths.ROOT / "work" / f"slack_{market}_files.json"
    if not args.text:
        if mpath.exists():
            files = json.loads(mpath.read_text())
        else:
            out["files_warning"] = f"{mpath.relative_to(paths.ROOT)} not found (run html_report.py): summary only"
    steps = thread_plan(text, files, paths.ROOT)
    token, hook = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_WEBHOOK_URL")

    if args.dry_run:
        out.update({"posted": False, "reason": "dry run", "mode": "thread" if token else ("webhook" if hook else "none"),
                    "plan": write_plan(market, channel, steps, paths.ROOT), "text": text})
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if token:
        if not channel:
            print(json.dumps({**out, "posted": False, "error": "slack_channel_id missing in config/settings.yaml"}))
            return 1
        slack = Slack(token, http)
        # the day's thread: the report's session (the files manifest), else the session being predicted
        session_date = None if args.text else ((files or {}).get("session")
                                                or market_status(cfg, clock())["session_date"])
        try:
            res = post_thread(slack, channel, steps, paths.ROOT, market if session_date else None, session_date)
        except (SlackError, AlertsSlackError, NotConfiguredError, OSError) as exc:
            print(json.dumps({**out, "posted": False, "mode": "thread", "error": str(exc)[:300],
                              "calls": slack.calls}))
            return 1
        print(json.dumps({**out, "posted": True, "mode": "thread", **res}))
        return 0
    if not hook:
        print(json.dumps({**out, "posted": False, "reason": "SLACK_BOT_TOKEN and SLACK_WEBHOOK_URL not set",
                          "text": text}, ensure_ascii=False))
        return 2
    try:
        ok, body = webhook_post(hook, text, http)
    except OSError as exc:
        print(json.dumps({**out, "posted": False, "mode": "webhook", "error": str(exc)[:200]}))
        return 1
    print(json.dumps({**out, "posted": ok, "mode": "webhook", "response": body}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
