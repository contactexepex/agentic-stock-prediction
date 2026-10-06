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
import runpy
import sys
import time
import types
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml

CODE = Path(__file__).resolve().parents[2]
FIXTURES = CODE / "tests" / "fixtures"
sys.path.insert(0, str(CODE / "scripts"))

HISTORY_ROWS = {"5d": 5, "1mo": 22, "3mo": 66, "1y": 252, "2y": 504}
SPLIT_EX_DATE = date(2026, 9, 30)
STALE_AFTER = date(2026, 9, 30)
SESSION_TIMES = {"india": ("Asia/Kolkata", "09:15"), "us": ("America/New_York", "09:30")}
TOPICS = ("Q3 results beat estimates", "announces share buyback", "CEO steps down", "wins large order",
          "faces regulatory probe", "raises guidance for the year", "plans acquisition of rival", "dividend declared",
          "profit falls on weak demand", "launches new product line")
NEWS_OUTLET_COUNT = 12


def crc(text: str) -> int:
    """A stable number for a name or URL."""
    return zlib.crc32(text.encode())


def market_config(market: str) -> dict:
    """The market's config as the collectors load it (MB_CONFIG)."""
    from marketbrief.core.market_config import load_market
    return load_market(market)


def listed_outlets() -> list[str]:
    """Allowlisted outlet domains whose pages may be fetched, in a fixed order."""
    sources = yaml.safe_load((Path(os.environ["MB_CONFIG"]) / "news_sources.yaml").read_text())
    domains = [d for d, meta in sources["domains"].items() if (meta or {}).get("tier") != "primary"
               and (meta or {}).get("fetch") is not False]
    return sorted(domains)[:NEWS_OUTLET_COUNT * 3]


# ---------- Yahoo ----------

class YahooBars:
    """The daily bars the fake Yahoo serves: the pinned price files, with the scripted cases."""

    def __init__(self, market: str):
        self.market, self.cfg = market, market_config(market)
        self.source = Path(os.environ["GOLDEN_PRICE_SOURCE"])
        self.zone = SESSION_TIMES[market][0]
        frames = [pd.read_csv(p) for p in sorted(self.source.rglob("*.csv"))]
        self.bars = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        tickers = list(self.cfg["tickers"])
        self.key_of = {meta["yahoo"]: key for key, meta in self.cfg["symbols"].items()}
        self.key_of.update({meta["yahoo"]: key for key, meta in self.cfg["tickers"].items()})
        self.case = {key: ("stale", "normal", "error", "normal")[i % 4] for i, key in enumerate(tickers)}
        if len(tickers) > 1:
            self.case[tickers[1]] = "split"
        cues = [k for k, m in self.cfg["symbols"].items() if m.get("role") == "cue"]
        if cues:
            self.case[cues[0]] = "empty"

    def case_of(self, symbol: str) -> str:
        """normal | stale | split | error | empty for a Yahoo symbol."""
        return self.case.get(self.key_of.get(symbol, ""), "normal")

    def daily(self, symbol: str, rows: int, start: date | None = None) -> pd.DataFrame:
        """A yfinance-shaped daily frame (index at local midnight)."""
        case = self.case_of(symbol)
        if case == "error":
            raise RuntimeError(f"golden: Yahoo refused {symbol}")
        if case == "empty":
            return pd.DataFrame()
        key = self.key_of.get(symbol)
        found = self.bars[self.bars["ticker"] == key] if key and len(self.bars) else self.bars.iloc[0:0]
        frame = self.synthetic(symbol) if found.empty else self.from_files(found)
        if case == "stale":
            frame = frame[frame.index.date <= STALE_AFTER].copy()
        if case == "split":
            before = frame.index.date < SPLIT_EX_DATE
            for column in ("Open", "High", "Low", "Close", "Adj Close"):
                frame.loc[before, column] = (frame.loc[before, column] / 2).round(4)
            frame.loc[before, "Volume"] = frame.loc[before, "Volume"] * 2
            frame.loc[frame.index.date == SPLIT_EX_DATE, "Stock Splits"] = 2.0
        return frame[frame.index.date >= start].copy() if start else frame.tail(rows).copy()

    def from_files(self, found: pd.DataFrame) -> pd.DataFrame:
        """The pinned bars of one symbol as a frame."""
        found = found.sort_values("date")
        index = pd.DatetimeIndex(pd.to_datetime(found["date"])).tz_localize(self.zone)
        return pd.DataFrame({"Open": found["open"].to_numpy(), "High": found["high"].to_numpy(),
                             "Low": found["low"].to_numpy(), "Close": found["close"].to_numpy(),
                             "Adj Close": found["adj_close"].to_numpy(), "Volume": found["volume"].to_numpy(),
                             "Dividends": 0.0, "Stock Splits": 0.0}, index=index)

    def synthetic(self, symbol: str) -> pd.DataFrame:
        """Bars for a symbol the pinned files do not hold (an ADR): a fixed walk by the symbol's crc."""
        days = pd.bdate_range(end="2026-10-02", periods=30)
        base = 20 + crc(symbol) % 180
        closes = [round(base * (1 + 0.003 * ((crc(f"{symbol}{d.date()}") % 21) - 10)), 4) for d in days]
        return pd.DataFrame({"Open": closes, "High": [c * 1.01 for c in closes], "Low": [c * 0.99 for c in closes],
                             "Close": closes, "Adj Close": closes, "Volume": 1_000_000,
                             "Dividends": 0.0, "Stock Splits": 0.0}, index=days.tz_localize(self.zone))

    def intraday(self, symbol: str) -> pd.DataFrame:
        """Five-minute bars of the last two sessions around each daily close."""
        daily = self.daily(symbol, 3)
        if daily.empty:
            return daily
        rows = {}
        for stamp, row in daily.tail(2).iterrows():
            for step in range(6):
                rows[stamp + pd.Timedelta(hours=9, minutes=15 + 5 * step)] = float(row["Close"]) * (1 + 0.001 * step)
        return pd.DataFrame({"Close": list(rows.values())}, index=pd.DatetimeIndex(list(rows)))


class FakeTicker:
    """yfinance.Ticker: history, calendar, dividends, earnings dates and option chains."""
    bars: YahooBars

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.key = self.bars.key_of.get(symbol, symbol)
        self.position = list(self.bars.cfg["tickers"]).index(self.key) if self.key in self.bars.cfg["tickers"] else -1

    def history(self, period=None, interval="1d", prepost=False, start=None, auto_adjust=True):  # noqa: ARG002
        """Daily or five-minute bars."""
        if interval == "5m":
            return self.bars.intraday(self.symbol)
        return self.bars.daily(self.symbol, HISTORY_ROWS.get(period or "1mo", 22),
                               date.fromisoformat(start) if start else None)

    @property
    def calendar(self) -> dict:
        """Upcoming earnings and ex-dividend dates ({} for one ticker in five, an error for one in seven)."""
        if self.position % 7 == 5:
            raise RuntimeError("golden: calendar refused")
        if self.position % 5 == 3:
            return {}
        return {"Earnings Date": [date(2026, 10, 22) + timedelta(days=self.position % 9)],
                "Ex-Dividend Date": date(2026, 10, 9) + timedelta(days=self.position % 6)}

    @property
    def dividends(self) -> pd.Series:
        """Past dividends (none for one ticker in six)."""
        if self.position % 6 == 2:
            return pd.Series(dtype=float)
        stamps = [pd.Timestamp(d, tz=self.bars.zone) for d in ("2025-12-12", "2026-03-13", "2026-06-12")]
        return pd.Series([0.5 + 0.01 * self.position, 0.52 + 0.01 * self.position, 0.55 + 0.01 * self.position],
                         index=pd.DatetimeIndex(stamps))

    def get_earnings_dates(self, limit=40):  # noqa: ARG002
        """Past earnings and call dates (an error for one ticker in four, so the screener answers)."""
        if self.position % 4 == 1:
            raise RuntimeError("golden: earnings page refused")
        return self._earnings()

    def _get_earnings_dates_using_screener(self, limit=40):  # noqa: ARG002
        """The screener fallback."""
        return self._earnings()

    def _earnings(self) -> pd.DataFrame:
        """Four past report dates and one call, local after-close and before-open times."""
        zone = self.bars.zone
        stamps = [pd.Timestamp(f"{d} {t}", tz=zone) for d, t in (
            ("2026-07-30", "16:30"), ("2026-04-29", "07:00"), ("2026-01-28", "16:30"), ("2025-10-29", "13:00"))]
        kinds = ["Earnings", "Earnings", "Call", "Earnings"]
        return pd.DataFrame({"Event Type": kinds, "EPS Estimate": 1.0}, index=pd.DatetimeIndex(stamps))

    @property
    def options(self) -> tuple:
        """Expiry dates (none for one ticker in five)."""
        return () if self.position % 5 == 3 else ("2026-10-09", "2026-10-16", "2026-10-30")

    @property
    def fast_info(self) -> dict:
        """The last price."""
        return {"lastPrice": self.spot()}

    def spot(self) -> float:
        """The newest pinned close of the symbol."""
        daily = self.bars.daily(self.symbol, 1)
        return float(daily["Close"].iloc[-1])

    def option_chain(self, expiry: str):
        """Calls and puts around the spot (an error for one ticker in seven; one empty expiry)."""
        if self.position % 7 == 6:
            raise RuntimeError("golden: option chain refused")
        spot = self.spot()
        base = 0.2 + (crc(self.symbol) % 25) / 100
        strikes = [round(spot * (0.9 + 0.025 * k), 2) for k in range(9)]
        empty = expiry == "2026-10-30" and self.position % 2 == 0

        def side(sign: int) -> pd.DataFrame:
            if empty:
                return pd.DataFrame(columns=["strike", "impliedVolatility", "bid", "ask", "lastPrice"])
            iv = [base + 0.2 * (k / spot - 1) ** 2 + sign * 0.005 for k in strikes]
            mid = [max(0.1, abs(spot - k) + spot * 0.02) for k in strikes]
            return pd.DataFrame({"strike": strikes, "impliedVolatility": iv, "bid": [m * 0.98 for m in mid],
                                 "ask": [m * 1.02 for m in mid], "lastPrice": mid})
        return types.SimpleNamespace(calls=side(1), puts=side(-1), underlying={"regularMarketPrice": spot})


def install_yahoo(market: str) -> None:
    """Put the fake `yfinance` module in place."""
    FakeTicker.bars = YahooBars(market)
    module = types.ModuleType("yfinance")
    module.Ticker = FakeTicker
    sys.modules["yfinance"] = module


# ---------- RSS, article pages, decoder ----------

class FeedResult(dict):
    """feedparser's result: status, bozo, entries."""

    def __init__(self, entries, status=200, bozo=False):
        super().__init__(status=status)
        self.entries, self.bozo = entries, bozo


def install_feedparser(market: str, now: datetime) -> None:
    """Put the fake `feedparser` module in place."""
    cfg, outlets = market_config(market), listed_outlets()
    tickers = list(cfg["tickers"].items())

    def parse(url: str, agent=None):  # noqa: ARG001
        seed = crc(url)
        if seed % 13 == 0 and url.startswith("https://news.google.com"):
            return FeedResult([], status=503, bozo=True)
        entries = []
        for k in range(4):
            key, meta = tickers[(seed + 7 * k) % len(tickers)]
            title = f"{meta['name']} {TOPICS[(seed // 3 + k) % len(TOPICS)]}"
            label = outlets[(seed + k) % len(outlets)]
            age_hours = (seed >> k) % 50
            if "rss" in url and "markets-106" in url:
                age_hours += 200
            published = (now - timedelta(hours=age_hours)).timetuple()
            entry = {"title": title, "summary": f"<p>{title} says the company.</p>", "published_parsed": published}
            if url.startswith("https://news.google.com"):
                entry.update(title=f"{title} - {label}", source={"title": label, "href": f"https://{label}"},
                             link=f"https://news.google.com/rss/articles/CBMi{crc(title + label):08x}")
            else:
                entry.update(link=f"https://{label}/story/{crc(title):08x}")
            entries.append(entry)
        if "business-standard.com/rss/companies" in url:
            return FeedResult([], status=503, bozo=True)
        return FeedResult(entries)
    module = types.ModuleType("feedparser")
    module.parse = parse
    sys.modules["feedparser"] = module


class FakeResponse:
    """A requests response for an article page."""
    is_redirect = False
    encoding = "utf-8"

    def __init__(self, status: int, body: bytes = b"", location: str | None = None):
        self.status_code, self.body = status, body
        self.headers = {"content-type": "text/html; charset=utf-8", **({"location": location} if location else {})}

    def iter_content(self, size: int):
        """The body in chunks."""
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def close(self) -> None:
        """Nothing to release."""


class FakeSession:
    """A requests session serving the article fixtures by the URL's crc (some 404, some redirects)."""

    def __init__(self):
        self.pages = sorted((FIXTURES / "articles").glob("*.html"))

    def get(self, url: str, **kwargs):  # noqa: ARG002
        """One fake GET."""
        seed = crc(url)
        if url.endswith("/moved"):
            return FakeResponse(200, self.pages[seed % len(self.pages)].read_bytes())
        if seed % 7 == 0:
            return FakeResponse(404)
        if seed % 7 == 1:
            return FakeResponse(301, location=url + "/moved")
        return FakeResponse(200, self.pages[seed % len(self.pages)].read_bytes())

    def close(self) -> None:
        """Nothing to release."""


def install_articles() -> None:
    """The fake session factory and the fake Google News decoder."""
    import marketbrief.sources.article_fetch as article_fetch
    article_fetch.make_session = FakeSession
    outlets = listed_outlets()

    class FakeDecoder:
        """googlenewsdecoder.GoogleDecoder."""

        def __init__(self, **kwargs):  # noqa: ARG002
            self.client = types.SimpleNamespace(event_hooks={})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def decode_google_news_urls(self, links, interval=1):  # noqa: ARG002
            """Most links resolve to an allowlisted page, every fifth fails."""
            out = []
            for link in links:
                seed = crc(link)
                if seed % 5 == 0:
                    out.append({"success": False, "message": "golden: not decoded"})
                else:
                    out.append({"success": True, "decoded_url": f"https://{outlets[seed % len(outlets)]}/n/{seed:08x}"})
            return out
    module = types.ModuleType("googlenewsdecoder")
    module.GoogleDecoder = FakeDecoder
    sys.modules["googlenewsdecoder"] = module


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
