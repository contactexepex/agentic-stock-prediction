"""Earnings reaction windows for the range engine: which sessions an earnings report moves, past reaction moves,
the earnings multiple they imply, and the dividends going ex inside a horizon."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from marketbrief.analytics import range_math
from marketbrief.constants.range_inputs import (
    EARNINGS_LOOKBACK_DAYS,
    INPUT_EARNINGS_HISTORY,
    TIMING_AFTER_CLOSE,
    TIMING_BEFORE_OPEN,
    TIMING_DURING,
)
from marketbrief.core.calendar import is_session, next_session


def affected_sessions(cfg: dict, day: date, timing: str | None) -> list[date]:
    """Sessions whose close-to-close move contains the earnings reaction. Unknown timing: the day
    itself and the next session (could be before the open or after the close)."""
    if timing in (TIMING_BEFORE_OPEN, TIMING_DURING):
        return [next_session(cfg, day)]
    if timing == TIMING_AFTER_CLOSE:
        return [next_session(cfg, day, include=False)]
    if is_session(cfg, day):
        return [day, next_session(cfg, day, include=False)]
    return [next_session(cfg, day)]


def earnings_in_horizon(cfg: dict, events: list[tuple[date, str | None]], as_of: date, target: date) -> bool:
    """True when an earnings reaction falls in the sessions after `as_of` up to `target`."""
    for day, timing in events:
        if day > target or day < as_of - timedelta(days=EARNINGS_LOOKBACK_DAYS):
            continue
        if any(as_of < session <= target for session in affected_sessions(cfg, day, timing)):
            return True
    return False


def past_moves(cfg: dict, close: pd.Series, sigma: pd.Series, events, warmup: int) -> list[tuple]:
    """(last session of the window, log move, daily sigma before it, sessions) per past report."""
    position = {stamp.date(): index for index, stamp in enumerate(close.index)}
    moves = []
    for day, timing in events:
        window = affected_sessions(cfg, day, timing)
        if window[0] not in position or window[-1] not in position:
            continue
        start, end = position[window[0]] - 1, position[window[-1]]
        if start < warmup:
            continue
        daily_sigma = float(sigma.iloc[start])
        if not daily_sigma > 0:
            continue
        moves.append((window[-1], math.log(close.iloc[end] / close.iloc[start]), daily_sigma, end - start))
    return moves


def earnings_stats(moves: list[tuple], range_config: dict, as_of: date) -> tuple[float, int, float | None]:
    """(multiple, events used, median absolute move) from reactions completed by as_of."""
    history = range_config[INPUT_EARNINGS_HISTORY]
    done = [move_row for move_row in moves if move_row[0] <= as_of][-int(history["lookback_events"]) :]
    multiple, used = range_math.earnings_multiple(
        [(move, sigma, sessions) for _, move, sigma, sessions in done],
        range_config["earnings_vol_multiple"],
        int(history["min_events"]),
        float(history["prior_events"]),
        float(history["max_multiple"]),
    )
    median = float(np.median([abs(move) for _, move, _, _ in done])) if done else None
    return multiple, used, median


def dividends_in_horizon(
    cfg: dict, dividends: list[tuple[date, float | None]], as_of: date, target: date
) -> list[float]:
    """Amounts of dividends whose ex-date session falls in (as_of, target]."""
    return [
        amount for day, amount in dividends if amount and day <= target and as_of < next_session(cfg, day) <= target
    ]
