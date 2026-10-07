"""Backtest observations: rolling beta, index cue series and the per-ticker input columns."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from marketbrief.analytics import earnings_reaction, index_cue, range_math
from marketbrief.constants.indicators import TRADING_DAYS
from marketbrief.core import calendar, market_config


def rolling_beta(close: pd.Series, bench: pd.Series, window: int = TRADING_DAYS, min_obs: int = 60) -> pd.Series:
    """The rolling beta of a stock against the benchmark."""
    joined = pd.concat([index_cue.log_returns(close), index_cue.log_returns(bench)], axis=1, join="inner").dropna()
    stock, benchmark = joined.iloc[:, 0], joined.iloc[:, 1]
    return (
        stock.rolling(window, min_periods=min_obs).cov(benchmark) / benchmark.rolling(window, min_periods=min_obs).var()
    ).reindex(close.index)


def index_cue_series(cfg: dict, bars: dict, ranges_config: dict) -> pd.Series | None:
    """Historical proxy of the index cue (log move expected for the benchmark), by as-of date."""
    cue_config = cfg.get("index_cue") or {}
    bench = bars.get(market_config.benchmark_key(cfg))
    if not cue_config.get("symbol") or bench is None:
        return None
    if cue_config.get("beta", 1.0) != "fit":
        return float(cue_config.get("beta", 1.0)) * np.log(bench["open"].shift(-1) / bench["close"])
    cue = bars.get(cue_config["symbol"])
    if cue is None:
        return None
    # the session after each as-of date; after the last stored bar the exchange calendar's (issue #27: the last
    # as-of day of a cut-off data set keeps its cue when the cue's bar is stored)
    after_last = pd.Timestamp(calendar.next_session(cfg, bench.index[-1].date(), include=False))
    nxt = pd.Series(bench.index[1:].tolist() + [after_last], index=bench.index)
    asof_frame = pd.DataFrame({"asof": bench.index, "date": nxt.to_numpy()}).dropna()
    cue_returns = index_cue.log_returns(cue["close"]).dropna()
    cue_frame = pd.DataFrame({"date": cue_returns.index, "r": cue_returns.to_numpy()})
    cue_by_day = pd.merge_asof(
        asof_frame.sort_values("date"), cue_frame, on="date", allow_exact_matches=False
    ).set_index("asof")["r"]
    betas = pd.Series(
        {
            position: index_cue.fit_cue_beta(
                bench["close"], cue["close"], position, int(ranges_config["beta_split"]["fit_sessions"])
            )
            for position in cue_by_day.index
        },
        dtype=float,
    )
    return (betas * cue_by_day).reindex(bench.index)


def mark_window(length: int, positions: list[int], horizon: int) -> np.ndarray:
    """Rows i whose horizon (i, i+h] contains one of the positions."""
    out = np.zeros(length, dtype=bool)
    for position in positions:
        out[max(0, position - horizon) : max(0, position)] = True
    return out


def observations(  # noqa: PLR0913 (the walk-forward inputs; callers pass them by position and keyword)
    bars,
    tickers,
    horizon: int,
    ranges_config: dict,
    index_by_timestamp: dict,
    cfg: dict | None = None,
    extra: dict | None = None,
) -> pd.DataFrame:
    """The walk-forward observations: standardised outcomes per ticker and day."""
    out = []
    for ticker_symbol in tickers:
        frame = bars.get(ticker_symbol)
        if frame is None or len(frame) < ranges_config["warmup_bars"] + horizon + 21:
            continue
        close_series = frame["close"]
        standardized_returns = range_math.standardized(
            close_series, horizon, ranges_config["ewma_lambda"], ranges_config["warmup_bars"]
        )
        logr = np.log(close_series / close_series.shift(1))
        s20 = logr.rolling(20).std(ddof=1)
        standardized_returns = standardized_returns.assign(
            close=close_series.reindex(standardized_returns.index),
            s20=s20.reindex(standardized_returns.index),
            ticker=ticker_symbol,
        )
        if cfg is not None and extra is not None:
            standardized_returns = standardized_returns.join(
                input_columns(cfg, ranges_config, frame, ticker_symbol, horizon, extra)
            )
        standardized_returns["rank"] = [index_by_timestamp.get(timestamp) for timestamp in standardized_returns.index]
        out.append(standardized_returns.dropna(subset=["rank", "z", "s20"]))
    if not out:
        return pd.DataFrame()
    frame = pd.concat(out)
    frame["rank"] = frame["rank"].astype(int)
    return frame[np.isfinite(frame["z"])]


def input_columns(
    cfg: dict, ranges_config: dict, frame: pd.DataFrame, ticker: str, horizon: int, extra: dict
) -> pd.DataFrame:
    """Per as-of date: earnings in horizon and the walk-forward multiple, ex-dividend log shift,
    beta at d and the cue proxies."""
    close, bar_index = frame["close"], frame.index
    length = len(bar_index)
    position_of_day = {timestamp.date(): position for position, timestamp in enumerate(bar_index)}
    # the calendar's sessions after the last stored bar get the positions they will have (issue #27), so an
    # earnings day or ex-date just after a cut-off data set still flags the last days before it
    after_last = calendar.sessions_ahead(cfg, bar_index[-1].date() + timedelta(days=1), horizon) if length else []
    position_of_day.update({day: length + offset for offset, day in enumerate(after_last)})
    input_frame = pd.DataFrame(index=bar_index)
    # earnings: each as-of date d uses the events as known at d (SEC 2.02 filings classified by
    # the 10-Q/10-K reports accepted by d; event_history.earnings_versions)
    earn, history_multiplier = np.zeros(length, dtype=bool), np.full(length, np.nan)
    sigma = range_math.ewma_sigma(close, ranges_config["ewma_lambda"])
    days = np.array([timestamp.date() for timestamp in bar_index])
    versions = extra["earnings"].get(ticker, [])
    for key, (start, events) in enumerate(versions):
        end = versions[key + 1][0] if key + 1 < len(versions) else None
        live = np.ones(length, dtype=bool)
        if start is not None:
            live &= days >= start
        if end is not None:
            live &= days < end
        if not live.any():
            continue
        event_positions = [
            position_of_day[affected_session]
            for event_day, timing in events
            for affected_session in earnings_reaction.affected_sessions(cfg, event_day, timing)
            if affected_session in position_of_day
        ]
        window_rows = mark_window(length, event_positions, horizon) & live
        earn |= window_rows
        moves = earnings_reaction.past_moves(cfg, close, sigma, events, ranges_config["warmup_bars"])
        for row_position in np.flatnonzero(window_rows):
            history_multiplier[row_position] = earnings_reaction.earnings_stats(
                moves, ranges_config, bar_index[row_position].date()
            )[0]
    input_frame["earn"] = earn
    input_frame["m_hist"] = history_multiplier
    # dividends: log shift for ex-dates inside (d, d+h]
    shift = np.zeros(length)
    for ex_day, amount in extra["dividends"].get(ticker, []):
        position = position_of_day.get(calendar.next_session(cfg, ex_day))
        if position is None or not amount:
            continue
        for row_position in range(max(0, position - horizon), min(position, length)):
            shift[row_position] += range_math.ex_dividend_shift(float(close.iloc[row_position]), [amount])
    input_frame["div_shift"] = shift
    input_frame["has_div"] = shift != 0
    # cues
    bench = extra["bench"]
    input_frame["beta"] = rolling_beta(close, bench["close"]).clip(*ranges_config["beta_split"]["beta_clip"])
    input_frame["own"] = np.log(frame["open"].shift(-1) / close) if cfg.get("premarket_quotes") else np.nan
    input_frame["idx_cue"] = extra["index_cue"].reindex(bar_index) if extra["index_cue"] is not None else np.nan
    input_frame["has_cue"] = input_frame["idx_cue"].notna() & input_frame["beta"].notna()
    return input_frame
