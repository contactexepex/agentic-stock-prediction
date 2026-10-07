"""The published range of one ticker and horizon: width (sigma), centre and the four band edges."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from marketbrief.analytics import range_math
from marketbrief.analytics.earnings_reaction import dividends_in_horizon, earnings_in_horizon, earnings_stats
from marketbrief.analytics.implied_volatility import implied_sigma
from marketbrief.analytics.index_cue import clip_beta
from marketbrief.analytics.range_context import HorizonContext, RangeContext
from marketbrief.analytics.range_switches import enabled
from marketbrief.analytics.scoring import percent
from marketbrief.constants.horizons import LABEL_N_PLUS_K
from marketbrief.constants.indicators import QUALITY_BLOCKED, TRADING_DAYS
from marketbrief.constants.range_inputs import (
    INPUT_BETA_SPLIT,
    INPUT_EARNINGS_HISTORY,
    INPUT_EX_DIVIDEND,
    INPUT_IMPLIED_VOL,
    INPUTS,
)
from marketbrief.constants.range_publication import (
    MSG_AI_WIDENED,
    MSG_CUE,
    MSG_CUE_IGNORED,
    MSG_EX_DIVIDEND,
    MSG_INDEX_CUE,
    MSG_LATE_CLOSED,
    MSG_LATE_OPENED,
    MSG_OWN_CUE_NET,
    NOTE_OPTIONS_IMPLIED,
    NOTE_PAST_MOVES,
    ROUND_CENTER,
    ROUND_PRICE,
)


@dataclass
class WidthBasis:
    """What the width of one ticker's range depends on, before the optional inputs."""

    sigma_daily: float
    earnings_in_horizon: bool
    implied: tuple | None
    use: dict
    moves: list


@dataclass
class RangeParts:
    """The computed pieces of one range row."""

    base: float
    center: float
    sigma_h: float
    formula_sigma: float
    iv_formula: float | None
    notes: list
    inputs: list
    direction: str | None
    confidence: float | None


def horizon_width(
    ctx: RangeContext, horizon_context: HorizonContext, basis: WidthBasis, apply_iv: bool
) -> tuple[float, list, list]:
    """(horizon sigma, notes, input names) with or without the option-implied volatility."""
    sigma, mult, earnings_note, notes, names = basis.sigma_daily, None, "", [], []
    in_h = basis.earnings_in_horizon
    if apply_iv and basis.implied is not None:
        s_iv, m_iv, iv_notes = basis.implied
        if s_iv != sigma or (m_iv is not None and in_h):
            sigma, mult, notes, names = s_iv, (m_iv if in_h else None), list(iv_notes), [INPUT_IMPLIED_VOL]
            earnings_note = NOTE_OPTIONS_IMPLIED if mult is not None else ""
    if in_h and mult is None and basis.use[INPUT_EARNINGS_HISTORY]:
        earnings_multiple, event_count, median = earnings_stats(basis.moves, ctx.ranges_config, ctx.as_of)
        if event_count >= ctx.ranges_config[INPUT_EARNINGS_HISTORY]["min_events"]:
            mult, earnings_note = earnings_multiple, NOTE_PAST_MOVES.format(count=event_count, median=median)
            names.append(INPUT_EARNINGS_HISTORY)
    sigma_h, horizon_notes = range_math.horizon_sigma(
        sigma,
        horizon_context.sessions,
        in_h,
        ctx.ranges_config,
        ctx.reg["regime"],
        horizon_context.major,
        mult,
        earnings_note,
    )
    return sigma_h, notes + horizon_notes, names


def adjust_sigma(ctx: RangeContext, ticker: str, sigma_h: float, notes: list) -> float:
    """Late-run notes, then the relation and smart-money widening of the width."""
    if ctx.made >= ctx.first_close:
        notes.append(MSG_LATE_CLOSED.format(first=ctx.first))
    elif ctx.made >= ctx.first_open:
        notes.append(MSG_LATE_OPENED.format(first=ctx.first))
    if ticker in ctx.rwiden:
        sigma_h *= 1 + ctx.rwiden[ticker][0]
        notes.append(ctx.rwiden[ticker][1])
    factor, smart_notes = ctx.smart.get(ticker, (1.0, []))
    notes += smart_notes
    return sigma_h * factor


def cue_center(
    ctx: RangeContext, ticker: str, feature_row: pd.Series, use_split: bool, notes: list, inputs: list
) -> float:
    """The centre shift of the overnight cue (beta split of the index cue and the own cue, or the own cue)."""
    ranges_config, center = ctx.ranges_config, 0.0
    cue = feature_row.get("cue_change_pct")
    own = math.log1p(float(cue)) if cue is not None and not pd.isna(cue) else None
    if own is not None and ctx.cue_ts.get(ticker) is not None and ctx.cue_ts[ticker] > ctx.first_open:
        notes.append(MSG_CUE_IGNORED.format(first=ctx.first))
        own = None
    beta = clip_beta(feature_row.get("beta_1y"), ranges_config)
    if use_split and ctx.index_cue_note:
        notes.append(ctx.index_cue_note)
    if use_split and ctx.index_cue is not None and beta is not None:
        beta_split = ranges_config[INPUT_BETA_SPLIT]
        center += range_math.beta_split_center(
            beta, ctx.index_cue, own, beta_split["index_weight"], beta_split["own_weight"], ranges_config["cue_weight"]
        )
        note = MSG_INDEX_CUE.format(
            index=ctx.index_cue, symbol=ctx.cfg["index_cue"]["symbol"], beta=beta, weight=beta_split["index_weight"]
        )
        notes.append(
            note + (MSG_OWN_CUE_NET.format(cue=float(cue), weight=beta_split["own_weight"]) if own is not None else "")
        )
        inputs.append(INPUT_BETA_SPLIT)
    elif own is not None:
        center += ranges_config["cue_weight"] * own
        notes.append(MSG_CUE.format(cue=float(cue), weight=ranges_config["cue_weight"]))
    return center


def ai_drift(
    ctx: RangeContext, prediction, sigma_h: float, notes: list
) -> tuple[float, float, str | None, float | None]:
    """(centre shift, sigma, direction, confidence) from the AI call: a drift toward its direction and a widening."""
    if prediction is None or prediction.direction not in ("up", "down") or pd.isna(prediction.confidence):
        return 0.0, sigma_h, None, None
    direction, confidence = prediction.direction, float(prediction.confidence)
    sign = 1 if direction == "up" else -1
    shift = sign * (confidence - 0.5) * ctx.ranges_config["ai_drift_scale"] * sigma_h
    widen = 0.0 if prediction.range_widen is None or pd.isna(prediction.range_widen) else float(prediction.range_widen)
    widen = min(max(widen, 0.0), ctx.ranges_config["max_ai_widen"])
    if widen:
        sigma_h *= 1 + widen
        notes.append(MSG_AI_WIDENED.format(percent=percent(widen)))
    return shift, sigma_h, direction, confidence


def ex_dividend_center(
    ctx: RangeContext, horizon_context: HorizonContext, ticker: str, base: float, notes: list, inputs: list
) -> float:
    """The known price drop of dividends going ex inside the horizon (outside the drift cap)."""
    amounts = dividends_in_horizon(ctx.cfg, ctx.divs.get(ticker, []), ctx.as_of, horizon_context.target)
    if not amounts:
        return 0.0
    notes.append(MSG_EX_DIVIDEND.format(amount=sum(amounts), share=sum(amounts) / base))
    inputs.append(INPUT_EX_DIVIDEND)
    return range_math.ex_dividend_shift(base, amounts)


def range_parts(ctx: RangeContext, horizon_context: HorizonContext, ticker: str, feature_row: pd.Series) -> RangeParts:
    """Width, centre, notes and AI fields of one ticker's range."""
    cfg, market = ctx.cfg, ctx.cfg["market"]
    base, daily_sigma = float(feature_row["close"]), float(feature_row["ewma_vol"]) / math.sqrt(TRADING_DAYS)
    use = {input_name: enabled(ctx.ranges_config, input_name, market, horizon_context.horizon) for input_name in INPUTS}
    tev = ctx.earn_ev.get(ticker, [])
    if use[INPUT_EARNINGS_HISTORY]:  # timed reaction sessions from the event history
        in_h = earnings_in_horizon(cfg, tev, ctx.as_of, horizon_context.target)
    else:
        earnings_date = ctx.earnings.get(ticker)
        in_h = bool(earnings_date and earnings_date <= horizon_context.target)
    topts = ctx.opts[ctx.opts["ticker"] == ticker] if not ctx.opts.empty else ctx.opts
    implied = (
        implied_sigma(cfg, topts, (ctx.as_of, horizon_context.target), daily_sigma, tev, ctx.ranges_config)
        if not topts.empty
        else None
    )
    basis = WidthBasis(daily_sigma, in_h, implied, use, ctx.moves.get(ticker, []))
    sigma_h, notes, inputs = horizon_width(ctx, horizon_context, basis, use[INPUT_IMPLIED_VOL])
    formula_sigma = sigma_h
    iv_formula = horizon_width(ctx, horizon_context, basis, True)[0] if implied is not None else None
    sigma_h = adjust_sigma(ctx, ticker, sigma_h, notes)
    # centre: overnight cue (beta split or direct) + AI drift, capped
    center = cue_center(ctx, ticker, feature_row, use[INPUT_BETA_SPLIT], notes, inputs)
    shift, sigma_h, direction, confidence = ai_drift(
        ctx, ctx.pred.get((ticker, horizon_context.horizon)), sigma_h, notes
    )
    center += shift
    cap = ctx.ranges_config["max_center_shift_sigma"] * sigma_h
    center = max(-cap, min(cap, center))
    if use[INPUT_EX_DIVIDEND]:
        center += ex_dividend_center(ctx, horizon_context, ticker, base, notes, inputs)
    return RangeParts(base, center, sigma_h, formula_sigma, iv_formula, notes, inputs, direction, confidence)


def range_row(ctx: RangeContext, horizon_context: HorizonContext, ticker: str) -> dict | None:
    """The range row of one ticker and horizon (None when it exists already or the ticker has no usable features)."""
    rid = f"{ctx.as_of}-{ticker}-{horizon_context.horizon}d"
    if rid in ctx.existing or ticker not in ctx.feats.index:
        return None
    feature_row = ctx.feats.loc[ticker]
    if feature_row["quality"] == QUALITY_BLOCKED or pd.isna(feature_row["ewma_vol"]) or pd.isna(feature_row["close"]):
        return None
    parts = range_parts(ctx, horizon_context, ticker, feature_row)
    base, quantiles = parts.base, horizon_context.quantiles

    def band(standardized_quantile: float) -> float:
        """A band edge: the base close moved by the centre and a standardised quantile, rounded."""
        return round(base * math.exp(parts.center + standardized_quantile * parts.sigma_h), ROUND_PRICE)

    close = ctx.bars[ticker]["close"] if ticker in ctx.bars else None
    s20 = range_math.realized_sigma(close[close.index <= pd.Timestamp(ctx.as_of)]) if close is not None else None
    n50 = (
        tuple(round(price, ROUND_PRICE) for price in range_math.naive_range(base, s20, horizon_context.sessions, 0.5))
        if s20
        else (None, None)
    )
    n80 = (
        tuple(round(price, ROUND_PRICE) for price in range_math.naive_range(base, s20, horizon_context.sessions, 0.8))
        if s20
        else (None, None)
    )
    return {
        "id": rid,
        "made_at": ctx.now,
        "as_of_date": str(ctx.as_of),
        "session_date": str(ctx.reg["session_date"])[:10],
        "target_date": str(horizon_context.target),
        "ticker": ticker,
        "horizon_days": horizon_context.horizon,
        "base_close": base,
        "center": round(parts.center, ROUND_CENTER),
        "sigma_h": round(parts.sigma_h, ROUND_CENTER),
        "lo50": band(quantiles["q25"]),
        "hi50": band(quantiles["q75"]),
        "lo80": band(quantiles["q10"]),
        "hi80": band(quantiles["q90"]),
        "naive_lo50": n50[0],
        "naive_hi50": n50[1],
        "naive_lo80": n80[0],
        "naive_hi80": n80[1],
        "direction": parts.direction,
        "confidence": parts.confidence,
        "regime": ctx.reg["regime"],
        "calibration_id": horizon_context.cal_id,
        "notes": parts.notes,
        "inputs": parts.inputs,
        "iv_sigma_h": round(parts.iv_formula * parts.sigma_h / parts.formula_sigma, ROUND_CENTER)
        if parts.iv_formula
        else None,
        "horizon_label": LABEL_N_PLUS_K,
        "entry_date": str(ctx.first),
        "exit_date": str(horizon_context.target),
    }
