"""Golden seed (tests/golden/seed.py): run a collector that needs Yahoo, RSS feeds, article pages or SEC
header pages with offline stand-ins for those services.

  python tests/golden/seed_collectors.py <market> <collector script> [collector arguments]

The collector's own entry point runs unchanged (scripts/<name>.py through runpy); only the outside world
is replaced, at the third-party boundary, so the stand-ins do not depend on how the code is organised:
- `yfinance` (daily bars from the pinned price files in GOLDEN_PRICE_SOURCE with a few scripted cases:
  stale, a split, an error, no data; intraday quotes; earnings calendar, dividends and earnings dates;
  option chains);
- `feedparser` (headlines naming watchlist companies, plus a failing and a stale outlet feed);
- `googlenewsdecoder` and the article `requests` session (pages from tests/fixtures/articles, with a
  404 and a redirect);
- the NSE client (marketbrief.sources.nse_client.Nse) replays the files of GOLDEN_NSE_REPLAY;
- time.sleep does nothing and time.monotonic is constant; for collect_news (which asks the wall clock
  for the age of an item) datetime.now() is MB_NOW.
Every value follows a fixed rule of the name or the URL (crc32), so two runs print the same bytes."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import runpy
from seed_common import CODE
from seed_feeds import install_articles, install_feedparser
from seed_yahoo import install_yahoo


def install_nse_replay() -> None:
    """The NSE client reads the replay folder instead of the network."""
    import marketbrief.sources.nse_client as nse_client
    real = nse_client.Nse

    class ReplayNse(real):
        """Nse with replay set."""

        def __init__(self, base=nse_client.NSE_BASE_URL, archives=nse_client.NSE_ARCHIVES_URL, pause=0.0, **_ignored):
            super().__init__(base, archives, replay=Path(os.environ["GOLDEN_NSE_REPLAY"]), pause=pause)
    nse_client.Nse = ReplayNse


def freeze_clock(script: str) -> None:
    """No sleeping, a constant monotonic clock, and for collect_news datetime.now() = MB_NOW."""
    time.sleep = lambda _seconds: None
    time.monotonic = lambda: 0.0
    if script != "collect_news.py":
        return
    import datetime as datetime_module
    frozen = datetime.fromisoformat(os.environ["MB_NOW"])
    real = datetime_module.datetime

    class Meta(type):
        """isinstance against the real datetime still holds."""

        def __instancecheck__(cls, instance):
            return isinstance(instance, real)

    class Frozen(real, metaclass=Meta):
        """datetime whose now() is MB_NOW."""

        @classmethod
        def now(cls, tz=None):
            """MB_NOW in the zone asked for."""
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)
    datetime_module.datetime = Frozen


def main() -> int:
    market, script, *arguments = sys.argv[1:]
    now = datetime.fromisoformat(os.environ["MB_NOW"]).astimezone(timezone.utc)
    install_yahoo(market)
    install_feedparser(market, now)
    install_articles()
    install_nse_replay()
    freeze_clock(script)
    sys.argv = [script, *arguments]
    runpy.run_path(str(CODE / "scripts" / script), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
