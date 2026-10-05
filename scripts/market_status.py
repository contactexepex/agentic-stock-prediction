#!/usr/bin/env python3
"""Print whether the market trades today (exchange timezone) and the session being predicted.
The routine uses this to post a one-line "market closed" message on holidays."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import events as ev
from common import market_arg, require_market


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    now = datetime.now(ZoneInfo(cfg["timezone"]))
    today = now.date()
    print(json.dumps({
        "market": cfg["market"], "local_time": now.isoformat(timespec="minutes"),
        "trading_day": ev.is_session(cfg, today),
        "session_date": str(ev.next_session(cfg, today)),
        "previous_session": str(ev.prev_session(cfg, today, include=False)),
        "calendar_covered": ev.calendar_covers(cfg, today),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
