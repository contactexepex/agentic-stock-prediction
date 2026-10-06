#!/usr/bin/env python3
"""Print whether the market trades today (exchange timezone) and the session being predicted.
The routine uses this to post a one-line "market closed" message on holidays.
`late_run` is true when the exchange-local time is already past the regular close of
`session_date` (e.g. the pre-open routine started after the close): the forecaster then
abstains, because any call would be scored on an outcome that is already public.
`in_session` is true between the open (`session_open_utc`) and the close of `session_date` (a
manual mid-session run): that session's outcome is partly public, so no call is made, ranges.py
publishes no 1-day range, and every range or call made then is late (never scored)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from marketbrief.core import calendar as ev
from marketbrief.core.cli import market_arg, require_market


def status(cfg: dict, now: datetime) -> dict:
    now = now.astimezone(ZoneInfo(cfg["timezone"]))
    today = now.date()
    session = ev.next_session(cfg, today)
    open_, close = ev.session_open_utc(cfg, session), ev.session_close_utc(cfg, session)
    return {
        "market": cfg["market"], "local_time": now.isoformat(timespec="minutes"),
        "trading_day": ev.is_session(cfg, today),
        "session_date": str(session),
        "previous_session": str(ev.prev_session(cfg, today, include=False)),
        "calendar_covered": ev.calendar_covers(cfg, today),
        "session_open_utc": open_.isoformat(),
        "session_close_utc": close.isoformat(),
        "in_session": open_ <= now < close,
        "late_run": now >= close,
    }


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--now", help="evaluate at this ISO 8601 time with offset instead of now (testing)")
    args = ap.parse_args()
    cfg = require_market(args)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(ZoneInfo(cfg["timezone"]))
    if now.tzinfo is None:
        raise SystemExit("--now needs a UTC offset, e.g. 2026-10-05T14:40:00+00:00")
    print(json.dumps(status(cfg, now), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
