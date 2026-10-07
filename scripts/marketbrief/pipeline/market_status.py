"""Print whether the market trades today (exchange timezone) and the session being predicted.
The routine uses this to post a one-line "market closed" message on holidays.
`previous_session` is the newest session whose bar is final (its close plus BAR_SETTLE_MINUTES
has passed, calendar.last_complete_session; collect_prices.py stores the market's own bars up to
it) and `session_date` the session after it, so a run after the close and the settling time
predicts the next session (issue #20). `late_run` is true when the time is already past the
regular close of `session_date` (a run in the settling window after the close, when that
session's bar is not final yet): the forecaster then abstains, because any call would be scored
on an outcome that is already public.
`in_session` is true between the open (`session_open_utc`) and the close of `session_date` (a
manual mid-session run): that session's outcome is partly public, so no call is made, ranges.py
publishes no 1-day range, and every range or call made then is late (never scored)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from marketbrief.constants.pipeline_messages import MSG_NOW_NEEDS_A_UTC_OFFSET
from marketbrief.core import calendar
from marketbrief.core.cli import market_arg, require_market


def status(cfg: dict, now: datetime) -> dict:
    """Whether the market trades today, the session being predicted and the run's timing flags."""
    now = now.astimezone(ZoneInfo(cfg["timezone"]))
    today = now.date()
    previous = calendar.last_complete_session(cfg, now)
    session = calendar.next_session(cfg, previous, include=False)
    open_, close = calendar.session_open_utc(cfg, session), calendar.session_close_utc(cfg, session)
    return {
        "market": cfg["market"],
        "local_time": now.isoformat(timespec="minutes"),
        "trading_day": calendar.is_session(cfg, today),
        "session_date": str(session),
        "previous_session": str(previous),
        "calendar_covered": calendar.calendar_covers(cfg, today),
        "session_open_utc": open_.isoformat(),
        "session_close_utc": close.isoformat(),
        "in_session": open_ <= now < close,
        "late_run": now >= close,
    }


def main() -> int:
    """Print the market status as JSON."""
    parser = market_arg(__doc__)
    parser.add_argument("--now", help="evaluate at this ISO 8601 time with offset instead of now (testing)")
    args = parser.parse_args()
    cfg = require_market(args)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(ZoneInfo(cfg["timezone"]))
    if now.tzinfo is None:
        raise SystemExit(MSG_NOW_NEEDS_A_UTC_OFFSET)
    print(json.dumps(status(cfg, now), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
