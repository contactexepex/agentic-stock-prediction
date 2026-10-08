"""One open paper trade's row of a check (B9; docs/ws/b9.md): the trade_checks row (price vs entry, vs target and vs
the trade's own range, band, target_z, flags) with its detail columns (issue #78: quality, today's
basis, whether the target has been reached so far, the z-scores). Monitoring only: nothing is ever traded.

All measures are on today's price basis: the prediction's target and range are multiplied by the split/bonus
factors with an ex-date after its as-of date, a stored entry open by those after D (adjustments detected by the
check). The trade_checks row keeps the raw entry, target and range as predicted."""

from __future__ import annotations

import math
from datetime import date

from marketbrief.constants.config_keys import CFG_MARKET
from marketbrief.constants.kinds import KIND_TRADE_CHECKS
from marketbrief.contracts.protocol import QUANTITY_DECIMALS
from marketbrief.core.schemas import SCHEMAS
from marketbrief.intraday.constants import (
    BAND_ABOVE80,
    BAND_BELOW80,
    ENTRY_INTRADAY_OPEN,
    ENTRY_STORED_OPEN,
    QUALITY_NO_ENTRY,
    QUALITY_NO_QUOTE,
    QUALITY_OK,
    TRADE_FLAG_AGAINST,
    TRADE_FLAG_FAR_FROM_TARGET,
    TRADE_FLAG_OUTSIDE_RANGE,
    NOTE_UNSETTLED_PAST_EXIT,
    TRADE_METHOD_VERSION,
)
from marketbrief.intraday.inputs import sessions_between
from marketbrief.intraday.measures import band_position, rounded, scaled
from marketbrief.intraday.quotes import SessionQuote
from marketbrief.intraday.settings import trade_check_id
from marketbrief.intraday.trades import factor_after

BAND_KEYS = ("lo80", "lo50", "hi50", "hi80")


def skipped_for_price(market: str, amount: float | None, entry_raw: float | None) -> bool:
    """India buys whole shares only (decision 4): a share above the amount means no trade (F1.4)."""
    if QUANTITY_DECIMALS.get(market) != 0 or not amount or not entry_raw:
        return False
    return math.floor(amount / entry_raw) == 0


def trade_row(ctx, trade: dict, quote: SessionQuote | None, sigma: float | None,
              elapsed: float | None) -> dict | None:
    """The trade_checks row of one open trade (with every detail column since issue #78), or None when the trade was
    skipped because
    one share costs more than its amount (India)."""
    ticker = trade["ticker"]
    ok = quote is not None and not ctx.stale.get(ticker)
    quality = QUALITY_OK if ok else (ctx.stale.get(ticker) or QUALITY_NO_QUOTE)
    entry_raw, source = _entry(ctx, trade, quote, ok)
    if skipped_for_price(ctx.cfg[CFG_MARKET], trade.get("amount"), entry_raw):
        return None
    if quality == QUALITY_OK and entry_raw is None:
        quality = QUALITY_NO_ENTRY
    adjustments = ctx.adjustments.get(ticker, [])
    basis = factor_after(adjustments, trade["as_of_date"])
    entry_factor = 1.0 if source == ENTRY_INTRADAY_OPEN else factor_after(adjustments, trade["entry_date"])
    check = _base_row(ctx, trade, quality, source)
    check["entry_price"] = rounded(entry_raw, 4)
    adj = {key: _times(trade.get(key), basis) for key in ("target_price", *BAND_KEYS)}
    check.update(basis_factor=rounded(basis, 6), entry_adj=rounded(_times(entry_raw, entry_factor), 4),
                   target_adj=rounded(adj["target_price"], 4),
                   **{f"{key}_adj": rounded(adj[key], 4) for key in BAND_KEYS})
    if trade.get("exit_delayed"):
        # issue #93: past its exit date with no paper_trades_settled row yet (a missing exit close, a settle step
        # that has not run, or a trade the settlement refused); the note names only what is known (#128)
        check["notes"].append(NOTE_UNSETTLED_PAST_EXIT)
    reached, high, low = _so_far(ctx, trade, quote if ok else None, adj["target_price"], check["notes"])
    check.update(target_reached=reached[0], target_reached_session=reached[1])
    if quality != QUALITY_OK:
        return check
    entry_adj = entry_raw * entry_factor
    last = quote.last_price
    sessions_held = trade["session_number"] - 1 + elapsed
    min_left = ctx.settings["measures"]["min_elapsed_fraction"]
    # a delayed exit (#93) settles at the next stored close: the rest of today
    exit_number = trade["session_number"] if trade.get("exit_delayed") else trade["exit_session_number"]
    sessions_left = max(exit_number - trade["session_number"] + 1 - elapsed, min_left)
    ret = last / entry_adj - 1
    to_target = adj["target_price"] / last - 1 if adj["target_price"] else None
    band = band_position(last, {key: adj[key] for key in BAND_KEYS})
    z_since, target_z = scaled(ret, sigma, sessions_held), scaled(to_target, sigma, sessions_left)
    check.update(last_price=rounded(last, 4), ret_since_entry_pct=rounded(100 * ret, 4),
                 to_target_pct=rounded(100 * to_target, 4) if to_target is not None else None, band=band,
                 target_z=rounded(target_z, 3))
    check.update(last_time=quote.last_time.isoformat(), sigma_1d=rounded(sigma), elapsed_fraction=rounded(elapsed, 4),
                   sessions_held=rounded(sessions_held, 4), sessions_left=rounded(sessions_left, 4),
                   z_since_entry=rounded(z_since, 3),
                   high_since_entry_pct=rounded(100 * (high / entry_adj - 1), 4) if high else None,
                   low_since_entry_pct=rounded(100 * (low / entry_adj - 1), 4) if low else None)
    if sigma is None:
        check["notes"].append("no_sigma")
    check["flags"] = trade_flags(trade, band, z_since, check["target_z"], reached[0], ctx.settings)
    check["flagged"] = any(flag in ctx.settings["trade_flag_on"] for flag in check["flags"])
    return check


def trade_flags(trade: dict, band: str | None, z_since: float | None, target_z: float | None,
                reached: bool | None, settings: dict) -> list[str]:
    """outside_range: the price is outside the trade's own 80% range; far_from_target: the target is not reached
    yet and lies at least thresholds.target_z sigma (scaled to the sessions left) above the price;
    against_prediction: the move since entry runs against the direction by at least thresholds.against_call_z
    sigma (scaled to the sessions held), as WS5's against_call."""
    thresholds, flags = settings["thresholds"], []
    if band in (BAND_BELOW80, BAND_ABOVE80):
        flags.append(TRADE_FLAG_OUTSIDE_RANGE)
    if reached is False and target_z is not None and target_z >= thresholds["target_z"]:
        flags.append(TRADE_FLAG_FAR_FROM_TARGET)
    if z_since is not None:
        signed = z_since if trade.get("direction", "up") == "up" else -z_since
        if signed <= -thresholds["against_call_z"]:
            flags.append(TRADE_FLAG_AGAINST)
    return flags


def _entry(ctx, trade: dict, quote: SessionQuote | None, ok: bool) -> tuple[float | None, str]:
    """(raw entry open, source): today's first 5-minute open when D is today, else D's stored raw open."""
    if trade["entry_date"] == ctx.session_date:
        return (quote.open_price if ok else None), ENTRY_INTRADAY_OPEN
    bar = ctx.trade_bars.get((trade["ticker"], trade["entry_date"]))
    return (bar.get("open") if bar else None), ENTRY_STORED_OPEN


def _so_far(ctx, trade: dict, quote: SessionQuote | None, target: float | None,
            notes: list[str]) -> tuple[tuple[bool | None, int | None], float | None, float | None]:
    """((target_reached, first session), highest high, lowest low) from D up to the check on today's basis: the
    stored bars of the sessions before today, then today's complete bars when the quote is fresh. Not reached
    before today and no fresh quote: (None, None) = unknown."""
    adjustments, highs, lows = ctx.adjustments.get(trade["ticker"], []), [], []
    reached = None
    days = sessions_between(ctx.cfg, trade["entry_date"], ctx.session_date)
    for number, day in enumerate(days[:-1], 1):
        bar = ctx.trade_bars.get((trade["ticker"], day))
        if bar is None or bar.get("high") is None:
            notes.append(f"no_bar_{day.isoformat()}")
            continue
        factor = factor_after(adjustments, day)
        highs.append(bar["high"] * factor)
        lows.append((bar.get("low") or bar["high"]) * factor)
        if reached is None and target is not None and highs[-1] >= target:
            reached = number
    if quote is not None:
        highs += [quote.high] if quote.high is not None else []
        lows += [quote.low] if quote.low is not None else []
        if reached is None and target is not None and quote.high is not None and quote.high >= target:
            reached = len(days)
    high, low = (max(highs), min(lows)) if highs and lows else (None, None)
    if reached is not None:
        return (True, reached), high, low
    if quote is None or target is None:
        return (None, None), high, low
    return (False, None), high, low


def _base_row(ctx, trade: dict, quality: str, source: str) -> dict:
    """The row with its identifying columns, every measure empty."""
    ident = trade_check_id(ctx.check_id, trade["trade_id"])
    stamp = {"check_id": ctx.check_id, "check_at": ctx.check_at.isoformat(),
             "session_date": ctx.session_date.isoformat(), "ticker": trade["ticker"], "trade_id": trade["trade_id"],
             "computed_at": ctx.computed_at}
    check = {
        **dict.fromkeys(SCHEMAS[KIND_TRADE_CHECKS][1]), **stamp, "id": ident,
        "check_row_id": ctx.check_row(trade["ticker"]), "market": ctx.cfg[CFG_MARKET],
        "prediction_id": trade["prediction_id"], "strategy_id": trade["strategy_id"], "view": trade["view"],
        "horizon_days": trade["horizon_days"], "entry_date": _iso(trade["entry_date"]),
        "exit_date": _iso(trade["exit_date"]), "session_number": trade["session_number"],
        "target_price": trade["target_price"], **{key: trade[key] for key in BAND_KEYS}, "flags": [],
        "flagged": False, "method_version": TRADE_METHOD_VERSION,
    }
    check.update(family=trade["family"], pick_rule=trade["pick_rule"], quality=quality, entry_source=source,
                 notes=[])   # issue #78: the detail columns live in trade_checks itself
    return check


def _times(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()
