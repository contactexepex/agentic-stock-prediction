"""Labels of the signal model (library, pure functions; the owner's trade convention).

For an as-of date d (a benchmark session with the ticker's bar), D is the first session after d.
- Primary, open_to_close: buy at the open of D, sell at the close of D+1 for the 1-day horizon
  (two sessions held) and at the close of D+4 for the 5-day horizon (five sessions held).
- Secondary, close_to_close: the as-of close to the close of D (1-day) or D+4 (5-day), as
  score_predictions.py scores calls (base close = the as-of close, target = h sessions later).
Each return comes with its end date (the session whose close resolves it): a training fit at cutoff c
uses only labels whose end date is on or before c. A label is missing when the ticker lacks a bar on
any benchmark session it spans (no gaps are bridged). `up` = return > 0; the cost-aware label is
return > the round-trip cost."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.constants.model import LABEL_CLOSE_TO_CLOSE, LABEL_OPEN_TO_CLOSE


def end_offset(convention: str, horizon: int) -> int:
    """Sessions after d whose close resolves the label: open_to_close 1d -> 2 (D+1), 5d -> 5 (D+4);
    close_to_close h -> h."""
    if convention == LABEL_OPEN_TO_CLOSE:
        return 2 if horizon == 1 else horizon
    return horizon


def forward_labels(frame: pd.DataFrame, session_pos: pd.Series, horizon: int) -> pd.DataFrame:
    """Per row of a ticker's bars (indexed by date, with open and close): for both conventions the
    return and its end date, plus the entry price (the open of D) and D's date.

    session_pos: benchmark session date -> its position (0, 1, ...)."""
    frame = frame.sort_index()
    pos = session_pos.reindex(frame.index).to_numpy(dtype=float)
    opens, closes = frame["open"].to_numpy(dtype=float), frame["close"].to_numpy(dtype=float)
    dates = frame.index.to_numpy()
    n = len(frame)
    out = pd.DataFrame(index=frame.index)
    entry_ok = shifted(pos, 1, n) - pos == 1
    out[f"entry_open_{horizon}d"] = np.where(entry_ok, shifted(opens, 1, n), np.nan)
    for convention in (LABEL_OPEN_TO_CLOSE, LABEL_CLOSE_TO_CLOSE):
        k = end_offset(convention, horizon)
        contiguous = shifted(pos, k, n) - pos == k
        base = shifted(opens, 1, n) if convention == LABEL_OPEN_TO_CLOSE else closes
        with np.errstate(divide="ignore", invalid="ignore"):
            ret = shifted(closes, k, n) / base - 1
        ok = contiguous & np.isfinite(ret) & (base > 0)
        out[f"ret_{convention}_{horizon}d"] = np.where(ok, ret, np.nan)
        end = pd.Series(shifted_dates(dates, k), index=frame.index)
        out[f"end_{convention}_{horizon}d"] = end.where(ok)
    return out


def shifted(values: np.ndarray, k: int, n: int) -> np.ndarray:
    """values[i + k] at row i (NaN past the end)."""
    out = np.full(n, np.nan)
    if k < n:
        out[:n - k] = values[k:]
    return out


def shifted_dates(dates: np.ndarray, k: int) -> np.ndarray:
    """dates[i + k] at row i (NaT past the end)."""
    out = np.full(len(dates), np.datetime64("NaT"), dtype="datetime64[ns]")
    if k < len(dates):
        out[:len(dates) - k] = dates[k:]
    return out


def label_columns(convention: str, horizon: int) -> tuple[str, str]:
    """(return column, end-date column) of a convention and horizon."""
    return f"ret_{convention}_{horizon}d", f"end_{convention}_{horizon}d"
