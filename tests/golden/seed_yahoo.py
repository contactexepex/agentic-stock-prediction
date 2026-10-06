"""Golden seed: the fake `yfinance` module (daily bars, intraday quotes, earnings, dividends, options)."""
from __future__ import annotations

import os
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from seed_common import HISTORY_ROWS, SESSION_TIMES, SPLIT_EX_DATE, STALE_AFTER, crc, market_config


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
