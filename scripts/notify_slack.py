#!/usr/bin/env python3
"""Post the filled Slack draft (work/slack_<market>.md) to Slack through an incoming webhook.

Set SLACK_WEBHOOK_URL in the cloud environment (Slack app -> Incoming Webhooks -> channel
#market-brief) and allow hooks.slack.com in its network settings. Refuses to post a draft that
still contains AGENT markers. Exit codes: 0 posted, 2 no webhook configured, 1 error."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

from common import ROOT, market_arg, require_market


def clean(text: str) -> str:
    # an unfilled optional failures line is dropped; any other marker is an error
    lines = [l for l in text.splitlines() if not l.strip().startswith("<!-- AGENT:failures")]
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the payload instead of posting")
    ap.add_argument("--text", help="post this one line instead of the draft (e.g. the market-closed message)")
    args = ap.parse_args()
    cfg = require_market(args)
    path = ROOT / "work" / f"slack_{cfg['market']}.md"
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
    if len(text.splitlines()) > 12:
        print(json.dumps({"step": "notify", "warning": "draft longer than 12 lines"}))
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if args.dry_run or not url:
        print(json.dumps({"step": "notify", "posted": False,
                          "reason": "dry run" if args.dry_run else "SLACK_WEBHOOK_URL not set", "text": text}))
        return 0 if args.dry_run else 2
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode()[:200]
    except Exception as exc:
        print(json.dumps({"step": "notify", "posted": False, "error": str(exc)[:200]}))
        return 1
    print(json.dumps({"step": "notify", "posted": body == "ok", "response": body}))
    return 0 if body == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
