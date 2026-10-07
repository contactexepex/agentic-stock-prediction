"""Cross-market features of the signal model: other markets' last sessions, FX, rates, commodities and
the ADR premium, each known before the open of D (library, pure functions; docs/DESIGN.md section 15).

The model's label buys at the open of D (the first benchmark session after the as-of date d), so a
feature of row d may only use a bar that was final before that open. The rule is the same for every
symbol and both markets, by clock time, not by date:

    a bar dated t of a symbol is available at  t + close_time (the symbol's `close_time` in the market
    config, "<HH:MM> <IANA zone>", its exchange's regular close incl. a closing auction; FX "23:59
    Europe/London", the end of Yahoo's London-day bar) + BAR_SETTLE_MINUTES (the collector's settle time);
    row d uses the newest bar available at or before the regular open of D (calendar.session_open_utc),
    and nothing when that bar is dated more than CROSS_MAX_AGE_DAYS calendar days before D.

What that gives (regular hours; tests/test_cross_market.py checks each feature):
- India (open 09:15 IST = 03:45 UTC): Asia (KOSPI, Taiwan, Shanghai, Nikkei, Hang Seng) of date d (their
  session of D closes after India opens), Europe of d, the US session of d (closes 20:00-21:00 UTC), FX,
  futures (17:00 ET) and the US 10-year yield of d; the ADRs' US close of d with USD/INR of d.
- US (open 09:30 ET = 13:30-14:30 UTC): Asia of D itself (closes by 08:10 UTC + settle), Europe of d (its
  session of D closes at 15:30-16:40 UTC, after the US open), FX, futures and yields of d.
A symbol's return is its close over its own previous stored close (its own sessions), so a holiday of
the symbol's exchange makes the next return span two sessions; a stale bar is missing, never 0.

ADR premium (India; symbols of role `adr` with `adr_of: <ticker>`): premium_d = ln(ADR close x USD/INR
/ the ticker's close of d), using the ADR's bar dated d and the newest available USD/INR bar; the
feature is premium_d minus the mean of the ticker's previous ADR_PREMIUM_DAYS premiums (missing until
there are that many). The ADR-to-share ratio and the persistent premium cancel in the deviation. A
ticker without an ADR gets 0 (not applicable: a neutral deviation, so the feature's coverage is not
cut by tickers that can never have it); a ticker with an ADR gets NaN before the ADR's data exists."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.constants.calendar import BAR_SETTLE_MINUTES
from marketbrief.constants.model import (ADR_PREMIUM_DAYS, CROSS_ADR, CROSS_MARKET_FEATURES, CROSS_MAX_AGE_DAYS,
                                         KIND_ADR_PREMIUM, KIND_CHANGE, META_ADR_OF, META_CLOSE_TIME,
                                         MSG_NO_CLOSE_TIME, ROLE_ADR)
from marketbrief.core import calendar as cal

SETTLE = pd.Timedelta(minutes=BAR_SETTLE_MINUTES)


def close_time(cfg: dict, key: str) -> str:
    """The symbol's `close_time` from the market config; exits with a message when it is missing."""
    value = (cfg["symbols"].get(key) or {}).get(META_CLOSE_TIME)
    if not value:
        raise SystemExit(MSG_NO_CLOSE_TIME.format(key=key))
    return value


def available_at(dates: pd.DatetimeIndex, close: str) -> pd.DatetimeIndex:
    """UTC instant at which each bar dated `dates` is final: its local close plus the settle time."""
    clock, zone = close.split()
    hours, minutes = (int(part) for part in clock.split(":"))
    local = pd.DatetimeIndex(dates).normalize().tz_localize(None) + pd.Timedelta(hours=hours, minutes=minutes)
    return local.tz_localize(zone, ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC") + SETTLE


def open_instants(cfg: dict, sessions: pd.Series) -> pd.DatetimeIndex:
    """The regular open (UTC) of each session date in `sessions` (D of each row)."""
    unique = {day: pd.Timestamp(cal.session_open_utc(cfg, day.date())) for day in pd.DatetimeIndex(sessions.unique())}
    return pd.DatetimeIndex([unique[day] for day in sessions])


def newest_available(series: pd.Series, close: str, opens: pd.DatetimeIndex,
                     sessions: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """(value, bar date) per row of the series' newest bar available at or before the row's open of D;
    NaN / NaT when there is none or it is dated more than CROSS_MAX_AGE_DAYS before D."""
    series = series.dropna().sort_index()
    n = len(opens)
    if series.empty:
        return np.full(n, np.nan), np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    ready = available_at(series.index, close)
    keep = ~ready.isna()
    series, ready = series[keep], ready[keep]
    pos = np.searchsorted(ready.asi8, opens.asi8, side="right") - 1
    found = pos >= 0
    safe = np.clip(pos, 0, None)
    dates = series.index.to_numpy()[safe]
    age = (pd.DatetimeIndex(sessions).to_numpy() - dates) / np.timedelta64(1, "D")
    ok = found & (age <= CROSS_MAX_AGE_DAYS)
    values = np.where(ok, series.to_numpy(dtype=float)[safe], np.nan)
    return values, np.where(ok, dates, np.datetime64("NaT"))


def daily_move(close: pd.Series, kind: str) -> pd.Series:
    """Close over the previous close minus 1 (KIND_RETURN) or close minus the previous close (KIND_CHANGE)."""
    close = close.dropna().sort_index()
    return close - close.shift(1) if kind == KIND_CHANGE else (close / close.shift(1) - 1).where(close.shift(1) > 0)


def enabled_features(market: str, groups) -> dict[str, tuple[str, str]]:
    """feature -> (symbol key, kind) of the enabled groups of a market (CROSS_MARKET_FEATURES order)."""
    out = {}
    for group, features in CROSS_MARKET_FEATURES.get(market, {}).items():
        if group in groups:
            out.update(features)
    return out


def market_level(cfg: dict, bars: dict, rows: pd.DataFrame, groups) -> pd.DataFrame:
    """The enabled market-wide cross features per as-of date. rows: indexed by as-of date with `session_d`."""
    out = pd.DataFrame(index=rows.index)
    opens = open_instants(cfg, rows["session_d"])
    for feature, (key, kind) in enabled_features(cfg["market"], groups).items():
        if kind == KIND_ADR_PREMIUM:
            continue
        if key not in bars:
            out[feature] = np.nan
            continue
        moves = daily_move(bars[key]["close"], kind)
        out[feature], _ = newest_available(moves, close_time(cfg, key), opens, rows["session_d"])
    return out


def adr_symbols(cfg: dict) -> dict[str, str]:
    """{watchlist ticker: ADR symbol key} of the market config's symbols of role `adr`."""
    return {meta[META_ADR_OF]: key for key, meta in cfg["symbols"].items()
            if meta.get("role") == ROLE_ADR and meta.get(META_ADR_OF)}


def adr_premium_dev(cfg: dict, bars: dict, ticker: str, rows: pd.DataFrame, fx_key: str) -> np.ndarray:
    """adr_premium_dev of one ticker per row (rows: its as-of dates with `session_d`, indexed by date)."""
    adr_key = adr_symbols(cfg).get(ticker)
    if adr_key is None:
        return np.zeros(len(rows))
    if adr_key not in bars or fx_key not in bars or ticker not in bars:
        return np.full(len(rows), np.nan)
    opens = open_instants(cfg, rows["session_d"])
    adr, adr_dates = newest_available(bars[adr_key]["close"], close_time(cfg, adr_key), opens, rows["session_d"])
    fx, _ = newest_available(bars[fx_key]["close"], close_time(cfg, fx_key), opens, rows["session_d"])
    local = bars[ticker]["close"].reindex(rows.index).to_numpy(dtype=float)
    same_day = adr_dates == rows.index.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        premium = np.where(same_day & (local > 0) & (adr > 0) & (fx > 0), np.log(adr * fx / local), np.nan)
    series = pd.Series(premium, index=rows.index).dropna()
    deviation = series - series.shift(1).rolling(ADR_PREMIUM_DAYS, min_periods=ADR_PREMIUM_DAYS).mean()
    return deviation.reindex(rows.index).to_numpy(dtype=float)


def add_cross_features(cfg: dict, bars: dict, panel: pd.DataFrame, groups) -> pd.DataFrame:
    """The panel plus the enabled cross-market features (market-wide on date, the ADR premium per ticker)."""
    groups = tuple(groups or ())
    features = enabled_features(cfg["market"], groups)
    if not features:
        return panel
    by_date = panel.drop_duplicates("date").set_index("date")[["session_d"]].sort_index()
    wide = market_level(cfg, bars, by_date, groups)
    panel = panel.merge(wide.rename_axis("date").reset_index(), on="date", how="left")
    if CROSS_ADR in groups:
        (adr_feature, (fx_key, _)), = CROSS_MARKET_FEATURES[cfg["market"]][CROSS_ADR].items()
        values = np.full(len(panel), np.nan)
        for ticker, idx in panel.groupby("ticker").groups.items():
            rows = panel.loc[idx, ["date", "session_d"]].set_index("date")
            values[panel.index.get_indexer(idx)] = adr_premium_dev(cfg, bars, ticker, rows, fx_key)
        panel[adr_feature] = values
    return panel

