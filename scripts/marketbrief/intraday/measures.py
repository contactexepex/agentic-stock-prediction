"""Deviation measures of one ticker at a check (pure functions): band position, the volatility-scaled move
since the open, the beta-adjusted residual and the direction of open calls, and the flags they raise."""

from __future__ import annotations

import math
import re

from marketbrief.intraday.constants import (
    BAND_ABOVE50,
    BAND_ABOVE80,
    BAND_BELOW50,
    BAND_BELOW80,
    BAND_INSIDE50,
    CALL_MODEL,
    CALL_PREDICTION,
    FLAG_AGAINST_CALL,
    FLAG_AGAINST_MODEL,
    FLAG_LARGE_MOVE,
    FLAG_LARGE_RESIDUAL,
    OUTSIDE_50_TEMPLATE,
    OUTSIDE_80_RE,
    OUTSIDE_80_TEMPLATE,
)

LEGACY_BAND_RE = r"band_(\d+)d"


def band_position(price: float | None, band: dict | None) -> str | None:
    """Where the price sits against a published range. A price exactly on an edge is inside that band."""
    if price is None or not band or band.get("lo80") is None or band.get("hi80") is None:
        return None
    if price < band["lo80"]:
        return BAND_BELOW80
    if price > band["hi80"]:
        return BAND_ABOVE80
    lo50, hi50 = band.get("lo50"), band.get("hi50")
    if lo50 is not None and price < lo50:
        return BAND_BELOW50
    if hi50 is not None and price > hi50:
        return BAND_ABOVE50
    return BAND_INSIDE50


def elapsed_fraction(last_time, session_open, session_close, minimum: float) -> float:
    """Share of the regular session elapsed at the last bar's end, within [minimum, 1]."""
    total = (session_close - session_open).total_seconds()
    done = (last_time - session_open).total_seconds()
    return min(1.0, max(minimum, done / total if total > 0 else 1.0))


def scaled(value: float | None, sigma: float | None, sessions: float) -> float | None:
    """value / (sigma * sqrt(sessions)), or None when it cannot be computed."""
    if value is None or not sigma or sigma <= 0 or sessions <= 0:
        return None
    return value / (sigma * math.sqrt(sessions))


def residual(ret: float | None, beta: float | None, bench_ret: float | None) -> float | None:
    """Return minus beta x benchmark return over the same window."""
    if ret is None or beta is None or bench_ret is None:
        return None
    return ret - beta * bench_ret


def call_side(call: dict, min_edge: float) -> str | None:
    """up / down of a call: its direction, or the side of 0.5 of a model score (None within min_edge)."""
    if call["source"] == CALL_PREDICTION:
        return call.get("direction")
    prob = call.get("prob_up")
    if prob is None or abs(prob - 0.5) < min_edge:
        return None
    return "up" if prob > 0.5 else "down"


def judge_call(call: dict, last_price: float, sigma: float | None, sessions: float, settings: dict) -> dict:
    """The call with its return since entry, that return's z and whether it runs against the call."""
    entry = call.get("entry_price")
    ret = last_price / entry - 1 if entry else None
    z = scaled(ret, sigma, sessions)
    side = call_side(call, settings["thresholds"]["model_min_edge"])
    against = False
    if side and z is not None:
        signed = z if side == "up" else -z
        against = signed <= -settings["thresholds"]["against_call_z"]
    return {**call, "direction": side if call["source"] == CALL_MODEL else call.get("direction"),
            "ret": rounded(ret), "z": rounded(z, 3), "against": against}


def band_by_horizon(row: dict) -> dict[int, str | None]:
    """{horizon k: band position} of a row: its `bands` JSON (every published horizon), else the legacy band_<k>d
    columns."""
    if row.get("bands"):
        return {int(k): value.get("band") for k, value in row["bands"].items()}
    return {int(m.group(1)): value for key, value in row.items() if (m := re.fullmatch(LEGACY_BAND_RE, key))}


def flags_for(row: dict, calls: list[dict], settings: dict) -> list[str]:
    """Every flag the row's measures raise (trigger flags and information flags). Band flags for every horizon k:
    outside_<k>d_80, and outside_<k>d_50 for the shortest horizon (WS5's 1-day 50% flag)."""
    thresholds, flags = settings["thresholds"], []
    bands = band_by_horizon(row)
    for k in sorted(bands):
        if bands[k] in (BAND_BELOW80, BAND_ABOVE80):
            flags.append(OUTSIDE_80_TEMPLATE.format(k=k))
        if k == min(bands) and bands[k] in (BAND_BELOW80, BAND_BELOW50, BAND_ABOVE50, BAND_ABOVE80):
            flags.append(OUTSIDE_50_TEMPLATE.format(k=k))
    if row.get("move_z") is not None and abs(row["move_z"]) >= thresholds["move_z"]:
        flags.append(FLAG_LARGE_MOVE)
    if row.get("residual_z") is not None and abs(row["residual_z"]) >= thresholds["residual_z"]:
        flags.append(FLAG_LARGE_RESIDUAL)
    if any(call["against"] for call in calls if call["source"] == CALL_PREDICTION):
        flags.append(FLAG_AGAINST_CALL)
    if any(call["against"] for call in calls if call["source"] == CALL_MODEL):
        flags.append(FLAG_AGAINST_MODEL)
    return flags


def is_trigger(flag: str, flag_on: list[str]) -> bool:
    """A flag marks the row flagged: listed in flag_on, or an outside_<k>d_80 flag when flag_on lists the
    template outside_{k}d_80 (every horizon)."""
    return flag in flag_on or (OUTSIDE_80_TEMPLATE in flag_on and re.fullmatch(OUTSIDE_80_RE, flag) is not None)


def rounded(value: float | None, digits: int = 6) -> float | None:
    """A float rounded for storage (None and NaN stay None)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), digits)
