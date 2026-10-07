"""Intraday prices for a check: the quotes collector's source (Yahoo through yfinance, 5-minute bars, its
`priced` filter and `snapshot` for the index cue), cut at the check time so a check never sees a later bar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from marketbrief.collectors.quotes import priced, snapshot
from marketbrief.constants.quotes import INTRADAY_INTERVAL, INTRADAY_PERIOD, YAHOO_CLOSE_COLUMN

YAHOO_OPEN_COLUMN = "Open"


@dataclass
class SessionQuote:
    """A symbol's session so far: the first bar's open, the newest complete bar's close and its time."""

    open_price: float
    last_price: float
    last_time: datetime


class YahooIntraday:
    """The live fetcher: one yfinance history call per symbol (regular session only), and the collector's
    snapshot for cues. Tests pass a stand-in with the same two methods."""

    def __init__(self):
        """Import yfinance only when a live check runs."""
        import yfinance

        self._yf = yfinance

    def bars(self, symbol: str) -> pd.DataFrame:
        """The symbol's recent 5-minute bars (index = bar start, aware)."""
        frame = self._yf.Ticker(symbol).history(period=INTRADAY_PERIOD, interval=INTRADAY_INTERVAL, prepost=False)
        return priced(frame)

    def cue(self, symbol: str, now: str) -> dict:
        """The collector's snapshot: latest price vs the previous regular-session close."""
        return snapshot(self._yf, symbol, now)


def complete_bars(frame: pd.DataFrame, check_at: datetime, bar_minutes: int) -> pd.DataFrame:
    """Bars complete by check_at (start + bar length <= check_at), in UTC."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    index = pd.DatetimeIndex(frame.index)
    frame.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    cutoff = pd.Timestamp(check_at) - timedelta(minutes=bar_minutes)
    return frame[frame.index <= cutoff].sort_index()


def session_quote(frame: pd.DataFrame, session_open: datetime, session_close: datetime) -> SessionQuote | None:
    """Open (first bar at or after the session open) and last close of the session's bars, or None."""
    if frame is None or frame.empty:
        return None
    today = frame[(frame.index >= pd.Timestamp(session_open)) & (frame.index < pd.Timestamp(session_close))]
    if today.empty:
        return None
    first, last = today.iloc[0], today.iloc[-1]
    open_price = first.get(YAHOO_OPEN_COLUMN)
    if open_price is None or pd.isna(open_price):
        open_price = first[YAHOO_CLOSE_COLUMN]
    return SessionQuote(float(open_price), float(last[YAHOO_CLOSE_COLUMN]), today.index[-1].to_pydatetime())


def last_bar_time(frame: pd.DataFrame) -> datetime | None:
    """The newest complete bar's start (any day), for the staleness note."""
    return None if frame is None or frame.empty else frame.index[-1].to_pydatetime()
