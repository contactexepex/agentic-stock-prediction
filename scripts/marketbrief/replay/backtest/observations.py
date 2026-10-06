"""Backtest observations: rolling beta, index cue series and the per-ticker input columns."""

from __future__ import annotations

import numpy as np
import pandas as pd
from marketbrief.analytics import earnings_reaction, index_cue
from marketbrief.analytics import range_math
from marketbrief.constants.indicators import TRADING_DAYS
from marketbrief.core import calendar, market_config


def rolling_beta(close: pd.Series, bench: pd.Series, window: int = TRADING_DAYS, min_obs: int = 60) -> pd.Series:
    inner_index = pd.concat([index_cue.log_returns(close), index_cue.log_returns(bench)], axis=1, join="inner").dropna()
    stock, benchmark = inner_index.iloc[:, 0], inner_index.iloc[:, 1]
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
    nxt = pd.Series(bench.index[1:].tolist() + [pd.NaT], index=bench.index)
    asof_frame = pd.DataFrame({"asof": bench.index, "date": nxt.to_numpy()}).dropna()
    rc_ = index_cue.log_returns(cue["close"]).dropna()
    cue_frame = pd.DataFrame({"date": rc_.index, "r": rc_.to_numpy()})
    inner_index = pd.merge_asof(
        asof_frame.sort_values("date"), cue_frame, on="date", allow_exact_matches=False
    ).set_index("asof")["r"]
    betas = pd.Series(
        {
            position: index_cue.fit_cue_beta(
                bench["close"], cue["close"], position, int(ranges_config["beta_split"]["fit_sessions"])
            )
            for position in inner_index.index
        },
        dtype=float,
    )
    return (betas * inner_index).reindex(bench.index)


def mark_window(length: int, positions: list[int], horizon: int) -> np.ndarray:
    """Rows i whose horizon (i, i+h] contains one of the positions."""
    out = np.zeros(length, dtype=bool)
    for position in positions:
        out[max(0, position - horizon) : max(0, position)] = True
    return out


def observations(
    bars, tickers, horizon: int, ranges_config: dict, rank: dict, cfg: dict | None = None, extra: dict | None = None
) -> pd.DataFrame:
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
        standardized_returns["rank"] = [rank.get(position) for position in standardized_returns.index]
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
    close, idx = frame["close"], frame.index
    length = len(idx)
    pos = {dividend.date(): dividend_position for dividend_position, dividend in enumerate(idx)}
    cols = pd.DataFrame(index=idx)
    # earnings: each as-of date d uses the events as known at d (SEC 2.02 filings classified by
    # the 10-Q/10-K reports accepted by d; event_history.earnings_versions)
    earn, history_multiplier = np.zeros(length, dtype=bool), np.full(length, np.nan)
    sigma = range_math.ewma_sigma(close, ranges_config["ewma_lambda"])
    days = np.array([dividend.date() for dividend in idx])
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
        eps = [
            pos[affected_session]
            for dividend, timing in events
            for affected_session in earnings_reaction.affected_sessions(cfg, dividend, timing)
            if affected_session in pos
        ]
        win = mark_window(length, eps, horizon) & live
        earn |= win
        moves = earnings_reaction.past_moves(cfg, close, sigma, events, ranges_config["warmup_bars"])
        for dividend_position in np.flatnonzero(win):
            history_multiplier[dividend_position] = earnings_reaction.earnings_stats(
                moves, ranges_config, idx[dividend_position].date()
            )[0]
    cols["earn"] = earn
    cols["m_hist"] = history_multiplier
    # dividends: log shift for ex-dates inside (d, d+h]
    shift = np.zeros(length)
    for dividend, amount in extra["dividends"].get(ticker, []):
        position = pos.get(calendar.next_session(cfg, dividend))
        if position is None or not amount:
            continue
        for dividend_position in range(max(0, position - horizon), position):
            shift[dividend_position] += range_math.ex_dividend_shift(float(close.iloc[dividend_position]), [amount])
    cols["div_shift"] = shift
    cols["has_div"] = shift != 0
    # cues
    bench = extra["bench"]
    cols["beta"] = rolling_beta(close, bench["close"]).clip(*ranges_config["beta_split"]["beta_clip"])
    cols["own"] = np.log(frame["open"].shift(-1) / close) if cfg.get("premarket_quotes") else np.nan
    cols["idx_cue"] = extra["index_cue"].reindex(idx) if extra["index_cue"] is not None else np.nan
    cols["has_cue"] = cols["idx_cue"].notna() & cols["beta"].notna()
    return cols
