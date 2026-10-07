"""The signal model's panel: one row per (ticker, as-of date) with every feature known before the next
session opens, and the forward labels (library; docs/DESIGN.md section 15).

Rows: watchlist tickers on benchmark sessions, from the ticker's `warmup_bars`-th bar on. Features are
computed from data up to the row's date only (technical_panel, market_panel); labels look forward and
are only ever used as training targets once resolved (walk_forward). The panel itself never mixes a
label into a feature."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from marketbrief.constants.config_keys import CFG_TICKERS
from marketbrief.constants.model import (FLOW_FEATURES, HORIZONS, LABEL_OPEN_TO_CLOSE, MARKET_FEATURES,
                                         REGIME_FEATURES, TECHNICAL_FEATURES)
from marketbrief.constants.features import MSG_NO_BENCHMARK_FOR_KEY
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.model import market_panel
from marketbrief.model.cross_market import add_cross_features, enabled_features
from marketbrief.model.labels import end_offset, forward_labels
from marketbrief.model.technical_panel import ticker_indicators

SECTOR_RETURN = "ret_5d"


def cue_key(cfg: dict) -> str | None:
    """The market's index cue symbol (config `index_cue.symbol`), if any."""
    return (cfg.get("index_cue") or {}).get("symbol")


def add_sector_strength(cfg: dict, panel: pd.DataFrame) -> pd.DataFrame:
    """rel_sector_5d = own 5-day return minus the mean of the sector peers' on the same date (features.py)."""
    sector = panel["ticker"].map({t: (m.get("sector") or t) for t, m in cfg[CFG_TICKERS].items()})
    grouped = panel.assign(_sector=sector).groupby(["date", "_sector"])[SECTOR_RETURN]
    total, count = grouped.transform("sum"), grouped.transform("count")
    own = panel[SECTOR_RETURN]
    peers = count - own.notna().astype(int)
    peer_mean = (total - own.fillna(0)) / peers.where(peers > 0)
    panel["rel_sector_5d"] = (own - peer_mean).where(own.notna())
    return panel


def event_flags(events: pd.DataFrame, ticker: str, kind: str, rows: pd.DataFrame, horizon: int) -> np.ndarray:
    """1 when a `kind` date stored by the as-of date falls inside the open-to-close holding window
    (D to its end session), 0 when none, NaN before the first stored row of that kind (unknown)."""
    if events.empty:
        return np.full(len(rows), np.nan)
    of_kind = events[events["type"] == kind]
    if of_kind.empty:
        return np.full(len(rows), np.nan)
    first_seen = of_kind["seen"].min()
    own = of_kind[of_kind["ticker"] == ticker]
    out = []
    end_col = f"window_end_{horizon}d"
    for day, start, end in zip(rows["date"], rows["session_d"], rows[end_col], strict=True):
        if day < first_seen:
            out.append(np.nan)
            continue
        if pd.isna(start) or pd.isna(end):
            out.append(0.0)
            continue
        known = own[own["seen"] <= day]
        out.append(float(((known["date"] >= start) & (known["date"] <= end)).any()))
    return np.array(out, dtype=float)


def session_windows(days: pd.DatetimeIndex) -> pd.DataFrame:
    """Per as-of date: D (the next benchmark session) and the end of each open-to-close window, from the
    benchmark's own sessions (the last dates of the panel run past them: approximated by weekdays)."""
    out = pd.DataFrame(index=days)
    ordered = list(days)
    extra = pd.bdate_range(days[-1] + timedelta(days=1), periods=6) if len(days) else []
    sessions = ordered + list(extra)
    out["session_d"] = [sessions[i + 1] for i in range(len(ordered))]
    for horizon in HORIZONS:
        k = end_offset(LABEL_OPEN_TO_CLOSE, horizon)
        out[f"window_end_{horizon}d"] = [sessions[i + k] for i in range(len(ordered))]
    return out


def ticker_rows(key: str, bars: dict, bench: pd.DataFrame, session_pos: pd.Series, warmup: int) -> pd.DataFrame:
    """One ticker's indicators and labels on benchmark sessions, from its warmup-th bar on."""
    frame = bars[key]
    rows = ticker_indicators(frame, bench["close"])
    for horizon in HORIZONS:
        rows = rows.join(forward_labels(frame, session_pos, horizon))
    rows = rows[rows.index.isin(bench.index) & (rows["bars"] >= warmup)]
    return rows.assign(ticker=key)


def bench_labels(bench: pd.DataFrame, session_pos: pd.Series) -> pd.DataFrame:
    """The benchmark's own open-to-close returns per as-of date (the benchmark_long_per_date baseline)."""
    out = pd.DataFrame(index=bench.index)
    for horizon in HORIZONS:
        labels = forward_labels(bench, session_pos, horizon)
        out[f"bench_ret_{LABEL_OPEN_TO_CLOSE}_{horizon}d"] = labels[f"ret_{LABEL_OPEN_TO_CLOSE}_{horizon}d"]
    return out


def build_panel(cfg: dict, inputs: dict, warmup: int, cross_groups=()) -> pd.DataFrame:
    """The full panel of one market (features and labels), sorted by date and ticker; plus the cross-market
    features of `cross_groups` (cross_market.py; none by default)."""
    bars = inputs["bars"]
    bench_key = benchmark_key(cfg)
    if bench_key not in bars:
        raise SystemExit(MSG_NO_BENCHMARK_FOR_KEY.format(key=bench_key))
    bench = bars[bench_key].sort_index()
    session_pos = pd.Series(np.arange(len(bench)), index=bench.index)
    parts = [ticker_rows(t, bars, bench, session_pos, warmup) for t in cfg[CFG_TICKERS] if t in bars]
    panel = pd.concat(parts).rename_axis("date").reset_index() if parts else pd.DataFrame()
    if panel.empty:
        return panel
    market = market_panel.market_features(cfg, bars, bench_key, vol_index_key(cfg), cue_key(cfg))
    market = market.join(bench_labels(bench, session_pos)).join(session_windows(bench.index))
    panel = panel.merge(market.rename_axis("date").reset_index(), on="date", how="left")
    panel = add_sector_strength(cfg, panel)
    panel = add_flows(cfg, inputs, panel, bench.index)
    panel = add_cross_features(cfg, bars, panel, cross_groups)
    for horizon in HORIZONS:
        for kind, column in (("earnings", "earnings_in_window"), ("ex_dividend", "ex_dividend_in_window")):
            values = np.full(len(panel), np.nan)
            for ticker, idx in panel.groupby("ticker").groups.items():
                values[panel.index.get_indexer(idx)] = event_flags(inputs["events"], ticker, kind, panel.loc[idx],
                                                                   horizon)
            panel[f"{column}_{horizon}d"] = values
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True)


def add_flows(cfg: dict, inputs: dict, panel: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Join the market's flow features (FLOW_FEATURES) on date (India) or ticker and date (US)."""
    market = cfg["market"]
    if market == "india":
        flows = market_panel.india_flow_features(inputs, days).rename_axis("date").reset_index()
        return panel.merge(flows, on="date", how="left")
    if market == "us":
        parts = [market_panel.us_flow_features(inputs, t, days).rename_axis("date").reset_index().assign(ticker=t)
                 for t in panel["ticker"].unique()]
        return panel.merge(pd.concat(parts), on=["date", "ticker"], how="left")
    for column in FLOW_FEATURES.get(market, ()):
        panel[column] = np.nan
    return panel


def feature_columns(market: str, horizon: int, cross_groups=()) -> list[str]:
    """The candidate model features of a market and horizon (event flags are per horizon), plus the
    cross-market features of the enabled groups."""
    events = [f"earnings_in_window_{horizon}d", f"ex_dividend_in_window_{horizon}d"]
    return [*TECHNICAL_FEATURES, *MARKET_FEATURES, *REGIME_FEATURES, *events, *FLOW_FEATURES.get(market, ()),
            *enabled_features(market, cross_groups or ())]
