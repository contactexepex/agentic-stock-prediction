"""Yahoo daily frames and the stored prices CSV files: freshness checks, stored bars, split rows, writing a bar."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path

from marketbrief.constants.collection import STALE_DAYS
from marketbrief.constants.columns import COL_CLOSE, COL_TICKER
from marketbrief.constants.config_keys import CFG_SYMBOLS, CFG_TICKERS, META_ROLE
from marketbrief.constants.kinds import EXT_CSV, KIND_PRICES
from marketbrief.constants.prices import (
    ERROR_NO_COMPLETED_BAR,
    ERROR_NO_DATA,
    MSG_STALE,
    OWN_EXCHANGE_ROLES,
    PRICE_DECIMALS,
    PRICE_FILE_COLUMNS,
    STORED_LOOKBACK_DAYS,
    YAHOO_CLOSE,
    YAHOO_OHLC,
    YAHOO_SPLITS,
)
from marketbrief.core.calendar import prev_session
from marketbrief.core.paths import data_dir
from marketbrief.core.storage import day_file


def expected_bar(cfg: dict, key: str, today: date) -> date:
    """Oldest acceptable newest bar for a symbol on a run on UTC date `today`."""
    if key in cfg[CFG_TICKERS] or cfg[CFG_SYMBOLS].get(key, {}).get(META_ROLE) in OWN_EXCHANGE_ROLES:
        return prev_session(cfg, today, include=False)
    return today - timedelta(days=STALE_DAYS)


def is_complete_bar(row) -> bool:
    """True when a frame row has open, high, low and close."""
    return not row.isna()[YAHOO_OHLC].any()


def frame_error(cfg: dict, key: str, frame, today: date) -> str | None:
    """Why a yfinance daily frame is no usable update (no data, no completed bar, stale), or None."""
    if frame is None or frame.empty:
        return ERROR_NO_DATA
    done = [stamp.date() for stamp, row in frame.iterrows() if stamp.date() < today and is_complete_bar(row)]
    if not done:
        return ERROR_NO_COMPLETED_BAR
    newest, expected = max(done), expected_bar(cfg, key, today)
    return MSG_STALE.format(newest=newest, expected=expected) if newest < expected else None


def stored_bars(path: Path) -> dict[str, dict]:
    """{ticker: row} of the bars in one prices day file (a later row for a ticker wins)."""
    if not path.exists():
        return {}
    return {row[COL_TICKER]: row for row in csv.DictReader(io.StringIO(path.read_text())) if row.get(COL_TICKER)}


def write_bar(path: Path, row: list) -> None:
    """Append one bar to a prices day file, writing the header first for a new file."""
    is_new = not path.exists() or not path.read_text()
    with path.open("a", newline="") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(PRICE_FILE_COLUMNS)
        writer.writerow(row)


def prices_file(cfg: dict, day: date) -> Path:
    """The prices CSV of one trading day."""
    return day_file(cfg["market"], KIND_PRICES, day, EXT_CSV)


def yahoo_split_ratios(frame) -> dict[date, float]:
    """{ex-date: ratio} of the splits and bonus issues in a yfinance frame (column `Stock Splits`;
    2.0 for a 2:1 split or a 1:1 bonus, 0 on other rows)."""
    if frame is None or getattr(frame, "empty", True) or YAHOO_SPLITS not in frame:
        return {}
    return {
        stamp.date(): float(value)
        for stamp, value in frame[YAHOO_SPLITS].items()
        if value == value and value not in (0, 1) and value > 0
    }


def yahoo_splits(frame) -> list[date]:
    """Dates of the splits and bonus issues in a yfinance frame (column `Stock Splits`)."""
    return list(yahoo_split_ratios(frame))


def frame_closes(frame, today: date) -> dict[date, float]:
    """{date: close} of the completed bars of a yfinance frame."""
    closes = {}
    for stamp, row in frame.iterrows():
        close = row.get(YAHOO_CLOSE)
        if stamp.date() < today and close is not None and close == close and float(close) > 0:
            closes[stamp.date()] = float(close)
    return closes


def newest_stored_before(cfg: dict, key: str, day: date) -> tuple[date, float] | None:
    """(date, close) of `key`'s newest stored bar dated before `day` (within STORED_LOOKBACK_DAYS), or None."""
    base = data_dir(cfg["market"]) / KIND_PRICES
    oldest = (day - timedelta(days=STORED_LOOKBACK_DAYS)).isoformat()
    for path in sorted(
        (prices_path for prices_path in base.glob("**/*.csv") if oldest <= prices_path.stem < day.isoformat()),
        reverse=True,
    ):
        row = stored_bars(path).get(key)
        if row and row.get(COL_CLOSE) not in (None, "") and float(row[COL_CLOSE]) > 0:
            return date.fromisoformat(path.stem), float(row[COL_CLOSE])
    return None


def stored_overlap(cfg: dict, key: str, frame, today: date) -> int:
    """How many of the frame's completed bars are stored for `key`."""
    return sum(1 for day in frame_closes(frame, today) if key in stored_bars(prices_file(cfg, day)))


def has_stored_before(cfg: dict, key: str, day: date) -> bool:
    """True when any stored prices file dated before `day` holds a bar of `key`."""
    base = data_dir(cfg["market"]) / KIND_PRICES
    files = sorted(
        (prices_path for prices_path in base.glob("**/*.csv") if prices_path.stem < day.isoformat()), reverse=True
    )
    return any(key in stored_bars(path) for path in files)


def to_stored_basis(row: list, factor: float) -> list:
    """A Yahoo bar [date, key, open, high, low, close, adj_close, volume, collected_at] on today's
    basis, put on the basis the stored bars of its date have (prices / factor, volume x factor) when
    recorded splits or bonus issues after that date (factor product `factor`) are applied on read;
    unchanged at factor = 1."""
    if factor == 1:
        return row
    return [
        row[0],
        row[1],
        *(round(value / factor, PRICE_DECIMALS) for value in row[2:7]),
        int(round(row[7] * factor)),
        row[8],
    ]
