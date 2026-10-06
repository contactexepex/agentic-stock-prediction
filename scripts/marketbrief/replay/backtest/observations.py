"""Backtest observations: rolling beta, index cue series and the per-ticker input columns."""
from __future__ import annotations

import numpy as np
import pandas as pd
from marketbrief.analytics import earnings_reaction, index_cue
from marketbrief.analytics import range_math
from marketbrief.constants.indicators import TRADING_DAYS
from marketbrief.core import calendar, market_config


def rolling_beta(close: pd.Series, bench: pd.Series, n: int = TRADING_DAYS, min_obs: int = 60) -> pd.Series:
    j = pd.concat([index_cue.log_returns(close), index_cue.log_returns(bench)], axis=1, join="inner").dropna()
    a, b = j.iloc[:, 0], j.iloc[:, 1]
    return (a.rolling(n, min_periods=min_obs).cov(b) / b.rolling(n, min_periods=min_obs).var()).reindex(close.index)


def index_cue_series(cfg: dict, bars: dict, rc: dict) -> pd.Series | None:
    """Historical proxy of the index cue (log move expected for the benchmark), by as-of date."""
    ic = cfg.get("index_cue") or {}
    bench = bars.get(market_config.benchmark_key(cfg))
    if not ic.get("symbol") or bench is None:
        return None
    if ic.get("beta", 1.0) != "fit":
        return float(ic.get("beta", 1.0)) * np.log(bench["open"].shift(-1) / bench["close"])
    cue = bars.get(ic["symbol"])
    if cue is None:
        return None
    nxt = pd.Series(bench.index[1:].tolist() + [pd.NaT], index=bench.index)
    a = pd.DataFrame({"asof": bench.index, "date": nxt.to_numpy()}).dropna()
    rc_ = index_cue.log_returns(cue["close"]).dropna()
    b = pd.DataFrame({"date": rc_.index, "r": rc_.to_numpy()})
    j = pd.merge_asof(a.sort_values("date"), b, on="date", allow_exact_matches=False).set_index("asof")["r"]
    betas = pd.Series({d: index_cue.fit_cue_beta(bench["close"], cue["close"], d, int(rc["beta_split"]["fit_sessions"]))
                       for d in j.index}, dtype=float)
    return (betas * j).reindex(bench.index)


def mark_window(n: int, positions: list[int], h: int) -> np.ndarray:
    """Rows i whose horizon (i, i+h] contains one of the positions."""
    out = np.zeros(n, dtype=bool)
    for p in positions:
        out[max(0, p - h):max(0, p)] = True
    return out


def observations(bars, tickers, h: int, rc: dict, rank: dict, cfg: dict | None = None,
                 extra: dict | None = None) -> pd.DataFrame:
    out = []
    for t in tickers:
        df = bars.get(t)
        if df is None or len(df) < rc["warmup_bars"] + h + 21:
            continue
        c = df["close"]
        s = range_math.standardized(c, h, rc["ewma_lambda"], rc["warmup_bars"])
        logr = np.log(c / c.shift(1))
        s20 = logr.rolling(20).std(ddof=1)
        s = s.assign(close=c.reindex(s.index), s20=s20.reindex(s.index), ticker=t)
        if cfg is not None and extra is not None:
            s = s.join(input_columns(cfg, rc, df, t, h, extra))
        s["rank"] = [rank.get(d) for d in s.index]
        out.append(s.dropna(subset=["rank", "z", "s20"]))
    if not out:
        return pd.DataFrame()
    df = pd.concat(out)
    df["rank"] = df["rank"].astype(int)
    return df[np.isfinite(df["z"])]


def input_columns(cfg: dict, rc: dict, df: pd.DataFrame, t: str, h: int, extra: dict) -> pd.DataFrame:
    """Per as-of date: earnings in horizon and the walk-forward multiple, ex-dividend log shift,
    beta at d and the cue proxies."""
    c, idx = df["close"], df.index
    n = len(idx)
    pos = {d.date(): i for i, d in enumerate(idx)}
    cols = pd.DataFrame(index=idx)
    # earnings: each as-of date d uses the events as known at d (SEC 2.02 filings classified by
    # the 10-Q/10-K reports accepted by d; event_history.earnings_versions)
    earn, mh = np.zeros(n, dtype=bool), np.full(n, np.nan)
    sigma = range_math.ewma_sigma(c, rc["ewma_lambda"])
    days = np.array([d.date() for d in idx])
    versions = extra["earnings"].get(t, [])
    for k, (start, events) in enumerate(versions):
        end = versions[k + 1][0] if k + 1 < len(versions) else None
        live = np.ones(n, dtype=bool)
        if start is not None:
            live &= days >= start
        if end is not None:
            live &= days < end
        if not live.any():
            continue
        eps = [pos[s] for d, tm in events for s in earnings_reaction.affected_sessions(cfg, d, tm) if s in pos]
        win = mark_window(n, eps, h) & live
        earn |= win
        moves = earnings_reaction.past_moves(cfg, c, sigma, events, rc["warmup_bars"])
        for i in np.flatnonzero(win):
            mh[i] = earnings_reaction.earnings_stats(moves, rc, idx[i].date())[0]
    cols["earn"] = earn
    cols["m_hist"] = mh
    # dividends: log shift for ex-dates inside (d, d+h]
    shift = np.zeros(n)
    for d, a in extra["dividends"].get(t, []):
        p = pos.get(calendar.next_session(cfg, d))
        if p is None or not a:
            continue
        for i in range(max(0, p - h), p):
            shift[i] += range_math.ex_dividend_shift(float(c.iloc[i]), [a])
    cols["div_shift"] = shift
    cols["has_div"] = shift != 0
    # cues
    bench = extra["bench"]
    cols["beta"] = rolling_beta(c, bench["close"]).clip(*rc["beta_split"]["beta_clip"])
    cols["own"] = np.log(df["open"].shift(-1) / c) if cfg.get("premarket_quotes") else np.nan
    cols["idx_cue"] = extra["index_cue"].reindex(idx) if extra["index_cue"] is not None else np.nan
    cols["has_cue"] = cols["idx_cue"].notna() & cols["beta"].notna()
    return cols
