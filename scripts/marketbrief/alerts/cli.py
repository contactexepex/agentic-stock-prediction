"""Post the market's Slack notifications (B6; docs/SPEC.md F9, docs/ws/b6.md).

  alerts.py --market india morning   [--date D]                 morning paper picks (starts the day's thread)
  alerts.py --market india intraday  [--date D] [--check-id ID] [--feed FILE]   alerts of one check run
  alerts.py --market india close     [--date D]                 close results (into the day's thread)
  alerts.py --market india corrections [--days 30]              a reply per trade re-settled after its close post
  alerts.py --market us weekly       [--week 2026-W41]          the weekly research report (its own post)
  alerts.py --market us onboarding   --command-id ID --channel C --thread-ts TS   reply to a command

Live: SLACK_BOT_TOKEN (scope chat:write) and slack_channel_id in config/settings.yaml (without the token,
unthreaded messages through SLACK_WEBHOOK_URL); each posted part is
recorded in data/<market>/slack_posts/, so a rerun posts nothing twice. --dry-run posts nothing: it writes the
messages to work/alerts_dryrun/<market>/messages.jsonl (with its own ledger there). Every read is as of the
run's clock (MB_NOW-aware). Exit codes: 0 posted, dry run or nothing to post; 2 neither token nor webhook, or a
token without a channel; 1 error."""
from __future__ import annotations

import json
import sys
from http.client import HTTPException
from pathlib import Path

import yaml

from marketbrief.alerts import reads
from marketbrief.alerts.close import build_close
from marketbrief.alerts.constants import (
    CORRECTION_DAYS,
    MSG_NOTHING,
    POST_ALERTS,
    POST_CLOSE,
    POST_CORRECTION,
    POST_MORNING,
    POST_WEEKLY,
)
from marketbrief.alerts.corrections import close_posts, correction_key, correction_text, session_of
from marketbrief.alerts.intraday import build_alerts
from marketbrief.alerts.morning import build_morning
from marketbrief.alerts.onboarding import post_onboarding_confirmation
from marketbrief.alerts.publish import Message, NotConfiguredError, publisher
from marketbrief.alerts.client import SlackError
from marketbrief.alerts.weekly import build_weekly
from marketbrief.contracts.strategies import STRATEGIES_FILE
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock
from marketbrief.core.database import connect
from marketbrief.core.settings import load_settings
from marketbrief.pipeline.market_status import status


def parser():
    """The command line."""
    ap = market_arg(__doc__)
    ap.add_argument("--dry-run", action="store_true", help="post nothing; write the messages to work/")
    sub = ap.add_subparsers(dest="post", required=True)
    for name in ("morning", "intraday", "close"):
        p = sub.add_parser(name)
        p.add_argument("--date", help="the session (default: from the market status as of the clock)")
        if name == "intraday":
            p.add_argument("--check-id", help="the check run (default: the newest by the clock)")
            p.add_argument("--feed", help="a JSONL file of B9's alert records instead of the stored feed")
    sub.add_parser("corrections").add_argument("--days", type=int, default=CORRECTION_DAYS,
                                               help="check the close posts of this many past days")
    sub.add_parser("weekly").add_argument("--week", help="ISO week, e.g. 2026-W41 (default: the newest)")
    p = sub.add_parser("onboarding")
    p.add_argument("--command-id", required=True)
    p.add_argument("--channel", required=True, help="the channel of the command's message")
    p.add_argument("--thread-ts", required=True, help="the ts of the command's message")
    return ap


def display_names(cfg: dict) -> dict:
    """Ticker -> company name and strategy id -> strategy name."""
    names = {t: (v or {}).get("name", t) for t, v in (cfg.get("tickers") or {}).items()}
    registry = paths.CONFIG / STRATEGIES_FILE
    if registry.exists():
        doc = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
        names.update({s["id"]: s.get("name", s["id"]) for s in doc.get("strategies") or []})
    return names


def horizons() -> list[int]:
    """The horizon list of config/strategies.yaml (1-5 when it is missing)."""
    registry = paths.CONFIG / STRATEGIES_FILE
    doc = yaml.safe_load(registry.read_text(encoding="utf-8")) if registry.exists() else {}
    return [int(h) for h in (doc or {}).get("horizons") or [1, 2, 3, 4, 5]]


def read_feed(path: str) -> list[dict]:
    """Alert records of a JSONL feed file."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def build(args, cfg: dict) -> Message | None:
    """The message the subcommand posts, or None when there is nothing to post."""
    market, now, names = cfg["market"], clock(), display_names(cfg)
    currency, con = cfg.get("currency"), connect(cfg["market"])
    if args.post == "weekly":
        review = reads.research_review(con, now, args.week)
        if review is None:
            return None
        return Message(POST_WEEKLY, f"{POST_WEEKLY}:{market}:{review['iso_week']}",
                       build_weekly(market, review, names, currency, (load_settings() or {}).get("pages_url")))
    market_status = status(cfg, now)
    day = args.date or (market_status["previous_session"] if args.post == "close" else market_status["session_date"])
    thread = f"{market}:{day}"
    if args.post == "morning":
        text = build_morning(market, day, reads.session_predictions(con, day, now), reads.session_picks(con, day, now),
                             horizons(), names)
        return Message(POST_MORNING, f"{POST_MORNING}:{market}:{day}", text, thread)
    if args.post == "close":
        text = build_close(market, day, reads.settled_today(con, day, cfg["timezone"], now),
                           reads.eod_analysis(con, day, now), names, currency)
        return Message(POST_CLOSE, f"{POST_CLOSE}:{market}:{day}", text, thread)
    rows = ([reads.without_late_note(r, now) for r in reads.feed_asof(read_feed(args.feed), now)] if args.feed
            else reads.latest_alerts(con, day, now, args.check_id))
    text = build_alerts(market, rows, names)
    if text is None:
        return None
    run = args.check_id or max(str(r.get("check_id") or r.get("check_at") or r.get("id")) for r in rows)
    return Message(POST_ALERTS, f"{POST_ALERTS}:{market}:{run}", text, thread)


def post_corrections(cfg: dict, args, http=None) -> dict:
    """One reply per trade re-settled after its day's close post, into that day's thread."""
    market, now = cfg["market"], clock()
    pub = publisher(market, dry_run=args.dry_run, http=http)
    con, names, results = connect(market), display_names(cfg), []
    for post in close_posts(pub.ledger, now, args.days):
        day = session_of(post)
        for row in reads.corrections(con, day, cfg["timezone"], post["posted_at"], now):
            text = correction_text(row, names, cfg.get("currency"))
            results.append(pub.publish(Message(POST_CORRECTION, correction_key(market, row), text, f"{market}:{day}")))
    out = {"mode": pub.client.mode, "posts": results, "posted": [p for r in results for p in r["posted"]]}
    return out if results else {**out, "reason": MSG_NOTHING}


def main(argv: list[str] | None = None, http=None) -> int:
    """Build and post one notification; prints a JSON summary (never the token)."""
    args = parser().parse_args(argv)
    cfg = require_market(args)
    out: dict = {"step": "alerts", "post": args.post, "market": cfg["market"]}
    try:
        if args.post == "onboarding":
            cmd = reads.command(connect(cfg["market"]), args.command_id, clock())
            if cmd is None:
                print(json.dumps({**out, "error": f"command {args.command_id} not found"}))
                return 1
            res = post_onboarding_confirmation(cmd, args.channel, args.thread_ts, dry_run=args.dry_run, http=http)
        elif args.post == "corrections":
            res = post_corrections(cfg, args, http)
        else:
            msg = build(args, cfg)
            if msg is None:
                print(json.dumps({**out, "posted": [], "reason": MSG_NOTHING}))
                return 0
            res = publisher(cfg["market"], dry_run=args.dry_run, http=http).publish(msg)
    except NotConfiguredError as exc:
        print(json.dumps({**out, "posted": [], "error": str(exc)}))
        return 2
    except (SlackError, OSError, HTTPException) as exc:
        print(json.dumps({**out, "posted": [], "error": str(exc)[:300]}))
        return 1
    print(json.dumps({**out, **res}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
