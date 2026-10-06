"""Option-implied volatility for the range engine: the first expiry on or after the target date either blends into
the daily volatility, or (with earnings inside the expiry) sets the earnings multiple."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from marketbrief.analytics import range_math
from marketbrief.analytics.earnings_reaction import earnings_in_horizon
from marketbrief.analytics.event_history import as_date
from marketbrief.analytics.scoring import percent
from marketbrief.constants.range_inputs import (INPUT_EARNINGS_HISTORY, INPUT_IMPLIED_VOL, MSG_IV_BLENDED,
                                                MSG_IV_PRICES_EARNINGS, MSG_IV_TEXT)
from marketbrief.core.calendar import next_session


def sessions_between(cfg: dict, start: date, end: date) -> list[date]:
    """Trading sessions in (start, end]."""
    found, day = [], start
    while True:
        day = next_session(cfg, day, include=False)
        if day > end:
            return found
        found.append(day)


def implied_sigma(cfg: dict, options: pd.DataFrame, span: tuple[date, date], sigma_daily: float,
                  earnings: list[tuple[date, str | None]], range_config: dict) -> tuple[float, float | None, list[str]]:
    """Use the first expiry on or after the target date. Without earnings before that expiry the
    implied daily variance is blended into sigma; with earnings inside the expiry the IV mostly
    prices the report, so it sets the earnings multiple instead (if `use_for_earnings`).
    Returns (sigma_daily, implied earnings multiple or None, notes). span = (as_of, target date)."""
    as_of, target = span
    settings = range_config[INPUT_IMPLIED_VOL]
    if options is None or options.empty:
        return sigma_daily, None, []
    window = options[(options["expiry"] >= target)
                     & (options["expiry"] <= target + timedelta(days=int(settings["max_expiry_days"])))]
    window = window[window["atm_iv"].notna() & (window["atm_iv"] > 0)].sort_values("expiry")
    if window.empty:
        return sigma_daily, None, []
    row = window.iloc[0]
    expiry = as_date(row["expiry"])
    sessions = len(sessions_between(cfg, as_of, expiry))
    if sessions < 1:
        return sigma_daily, None, []
    total = range_math.implied_variance(float(row["atm_iv"]), (expiry - as_of).days)
    text = MSG_IV_TEXT.format(iv=percent(float(row["atm_iv"])), expiry=expiry)
    if earnings_in_horizon(cfg, earnings, as_of, expiry):
        if not settings.get("use_for_earnings", True):
            return sigma_daily, None, []
        multiple = range_math.implied_earnings_multiple(total, sessions, sigma_daily,
                                                        float(range_config[INPUT_EARNINGS_HISTORY]["max_multiple"]))
        return sigma_daily, multiple, [MSG_IV_PRICES_EARNINGS.format(text=text)]
    weight = float(settings["weight"])
    return (range_math.blend_sigma(sigma_daily, total / sessions, weight), None,
            [MSG_IV_BLENDED.format(text=text, weight=weight)])
