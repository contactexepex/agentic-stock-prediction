"""As-of reads for the paper portfolio: every query keeps only rows stored by the run's clock (MB_NOW-aware), so
a run never sees data written after it. Bars are the stored ones (latest collection by the clock wins) on the
market's sessions; split and bonus factors are the adjustments detected by the clock (views.sql semantics)."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from marketbrief.constants.kinds import KIND_PORTFOLIO_TRADES, KIND_WATCHLIST_REQUESTS
from marketbrief.core.calendar import is_session
from marketbrief.portfolio.constants import TRADE_SIDES

BAR_COLUMNS = ["ticker", "date", "open", "high", "low", "close"]


def stored_bars(con, cfg: dict, clock: datetime, tickers: list[str], start: date | None = None) -> pd.DataFrame:
    """Raw daily bars (as stored, unadjusted) of `tickers` collected by `clock`, on sessions only, sorted."""
    if not tickers:
        return pd.DataFrame(columns=BAR_COLUMNS)
    frame = con.execute(
        "SELECT DISTINCT ON (ticker, date) ticker, date, open, high, low, close FROM prices "
        "WHERE ticker IN (SELECT unnest(?)) AND collected_at <= ? AND date >= coalesce(?, DATE '1900-01-01') "
        "AND close IS NOT NULL ORDER BY ticker, date, collected_at DESC",
        [list(tickers), clock, start],
    ).df()
    if frame.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame[[is_session(cfg, day) for day in frame["date"]]]
    return frame.sort_values(["ticker", "date"]).reset_index(drop=True)


def bar_on(con, cfg: dict, clock: datetime, ticker: str, day: date) -> dict | None:
    """The stored raw bar of `ticker` on `day` as of `clock`, or None."""
    bars = stored_bars(con, cfg, clock, [ticker], day)
    bars = bars[bars["date"] == day]
    return None if bars.empty else bars.iloc[0].to_dict()


def adjustments(con, clock: datetime) -> pd.DataFrame:
    """Split/bonus records detected by `clock`, minus those a later row (also by `clock`) supersedes."""
    return con.execute(
        "SELECT DISTINCT ON (id) id, ticker, ex_date, factor FROM adjustments WHERE detected_at <= ? AND id NOT IN "
        "(SELECT supersedes FROM adjustments WHERE supersedes IS NOT NULL AND detected_at <= ?) "
        "ORDER BY id, detected_at", [clock, clock],
    ).df()


def factor_after(adjust: pd.DataFrame, ticker: str, day: date) -> float:
    """The price multiplier that puts a `day` price of `ticker` on today's basis (1 when no adjustment)."""
    if adjust.empty:
        return 1.0
    rows = adjust[(adjust["ticker"] == ticker) & (pd.to_datetime(adjust["ex_date"]).dt.date > day)]
    out = 1.0
    for value in sorted(rows["factor"].tolist()):
        out *= float(value)
    return out


def trade_rows(con, clock: datetime) -> pd.DataFrame:
    """Every stored paper-trade row entered by `clock` (active, cancelled and corrected), oldest first. A row id
    stored twice (the same idempotency key appended by two concurrent imports, docs/ws/ws4.md) counts once, at its
    first entry."""
    frame = con.execute(
        f"SELECT * FROM (SELECT DISTINCT ON (id) * FROM {KIND_PORTFOLIO_TRADES} WHERE entered_at <= ? "
        "ORDER BY id, entered_at) ORDER BY entered_at, id", [clock]).df()
    if not frame.empty:
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def request_rows(con, clock: datetime) -> pd.DataFrame:
    """Every stored watchlist request made by `clock`, oldest first (a row id stored twice counts once)."""
    return con.execute(
        f"SELECT * FROM (SELECT DISTINCT ON (id) * FROM {KIND_WATCHLIST_REQUESTS} WHERE requested_at <= ? "
        "ORDER BY id, requested_at) ORDER BY requested_at, id", [clock]).df()


def superseded_by(trades: pd.DataFrame) -> dict[str, str]:
    """{cancelled or corrected trade id: the id of the row that supersedes it}."""
    if trades.empty:
        return {}
    rows = trades[trades["supersedes"].notna()]
    return dict(zip(rows["supersedes"], rows["id"]))


def active_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Buy and sell rows that no later row cancels or corrects (cancel rows themselves are never active)."""
    if trades.empty:
        return trades
    gone = set(superseded_by(trades))
    return trades[~trades["id"].isin(gone) & trades["side"].isin(TRADE_SIDES)].reset_index(drop=True)
