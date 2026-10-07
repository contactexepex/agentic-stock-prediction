"""A stand-in for the yfinance module that serves fixed daily bars (offline onboarding tests and fixture runs)."""
from __future__ import annotations

import pandas as pd

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class FixtureTicker:
    """yfinance.Ticker for one symbol's fixture bars [[date, open, high, low, close, volume], ...]."""

    def __init__(self, bars: list[list]):
        """Keep the symbol's bars."""
        self.bars = bars

    def history(self, start=None, **_options):  # period, interval: always the whole daily series
        """The bars (from `start` when given) as a yfinance-shaped frame: Open .. Volume, Adj Close, splits."""
        frame = pd.DataFrame([row[1:] for row in self.bars], columns=COLUMNS,
                             index=pd.DatetimeIndex([pd.Timestamp(row[0], tz="UTC") for row in self.bars]))
        if start is not None:
            frame = frame[frame.index >= pd.Timestamp(start, tz="UTC")]
        frame["Adj Close"] = frame["Close"]
        frame["Dividends"], frame["Stock Splits"] = 0.0, 0.0
        return frame


class FixtureYfinance:
    """The yfinance module's `Ticker` over fixture bars; a symbol without bars returns an empty frame."""

    def __init__(self, bars_by_symbol: dict[str, list[list]]):
        """Keep every symbol's bars."""
        self.bars_by_symbol = bars_by_symbol

    def Ticker(self, symbol: str) -> FixtureTicker:  # noqa: N802 (the yfinance name)
        """One symbol."""
        return FixtureTicker(self.bars_by_symbol.get(symbol, []))
