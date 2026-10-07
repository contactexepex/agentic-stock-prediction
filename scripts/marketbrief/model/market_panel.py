"""Market-level and flow features of the signal model at every as-of date (benchmark session).

All from stored daily bars and rows dated on or before the as-of date d (the information known before
the next session D opens):
- benchmark 5-day return and 10-day realized vol, the vol index level and its 1-day change (closes),
  and the regime as regime.classify labels it from them plus the scheduled major events near D
  (the live features.py uses a pre-open vol quote when there is one; the model uses closes in training
  and scoring alike, so both see the same definition);
- cue_ret_1d: the last daily return of the market's index cue (config `index_cue`: US ES futures, India
  the S&P 500) on its newest bar dated on or before d. For India that bar is the US session of date d,
  which closes after India's close but before D opens. Missing when that bar is over 4 days old;
- India flows: NSE FII/FPI and DII provisional net cash (date <= d) and NSDL FPI equity net (reporting
  date < d, published the next day); US flows: FINRA short-volume share (date <= d) and Form 4 net
  open-market buying over 30 days (accepted by d), as sign * ln(1 + |USD| / 1e6)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from marketbrief.analytics import indicators as ind
from marketbrief.analytics import regime as regime_rules
from marketbrief.constants.model import REGIME_COLUMNS
from marketbrief.core import calendar as ev

CUE_MAX_AGE_DAYS = 4
FLOW_MAX_AGE_DAYS = 5
INSIDER_WINDOW_DAYS = 30
INSIDER_SCALE_USD = 1e6


def latest_on_or_before(series: pd.Series, days: pd.DatetimeIndex, max_age: int | None = None,
                        strict: bool = False) -> pd.Series:
    """For each day, the series' newest value dated on or before it (before it when strict), NaN
    when none or older than max_age calendar days."""
    if series.empty:
        return pd.Series(np.nan, index=days)
    series = series.sort_index()
    probe = days - pd.Timedelta(days=1) if strict else days
    pos = series.index.searchsorted(probe, side="right") - 1
    values = np.where(pos >= 0, series.to_numpy()[np.clip(pos, 0, None)], np.nan).astype(float)
    if max_age is not None:
        found = series.index[np.clip(pos, 0, None)]
        values = np.where((pos >= 0) & ((days - found).days <= max_age), values, np.nan)
    return pd.Series(values, index=days)


def daily_change(series: pd.Series) -> pd.Series:
    """Each value over the previous one minus 1."""
    return series / series.shift(1) - 1


def regime_labels(cfg: dict, frame: pd.DataFrame) -> list[str]:
    """regime.classify per as-of date from the frame's bench_ret_5d, bench_vol_10d, vol_level, vol_change_1d."""
    days = [d.date() for d in frame.index]
    if not days:
        return []
    events = ev.market_events(cfg, days[0], days[-1] + timedelta(days=40))
    labels = []
    for day, row in zip(days, frame.itertuples(), strict=True):
        near = ev.major_events_near(events, ev.next_session(cfg, day, include=False))
        label, _, _ = regime_rules.classify(cfg["regime"], none_if_nan(row.vol_level), none_if_nan(row.bench_ret_5d),
                                            none_if_nan(row.bench_vol_10d), bool(near),
                                            none_if_nan(row.vol_change_1d))
        labels.append(label)
    return labels


def none_if_nan(value) -> float | None:
    """A float, or None for NaN (regime.classify treats None as missing)."""
    return None if value is None or pd.isna(value) else float(value)


def market_features(cfg: dict, bars: dict[str, pd.DataFrame], bench_key: str, vol_key: str,
                    cue_key: str | None) -> pd.DataFrame:
    """One row per benchmark session: bench_ret_5d, bench_vol_10d, vol_level, vol_change_1d, cue_ret_1d
    and the regime one-hot columns."""
    bench = bars[bench_key]["close"]
    days = bench.index
    out = pd.DataFrame(index=days)
    out["bench_ret_5d"] = bench / bench.shift(5) - 1
    out["bench_vol_10d"] = [ind.realized_vol(bench.iloc[max(0, i - 30):i + 1]) for i in range(len(bench))]
    vol = bars[vol_key]["close"] if vol_key in bars else pd.Series(dtype=float)
    out["vol_level"] = latest_on_or_before(vol, days)
    out["vol_change_1d"] = latest_on_or_before(daily_change(vol), days)
    cue = bars[cue_key]["close"] if cue_key and cue_key in bars else pd.Series(dtype=float)
    out["cue_ret_1d"] = latest_on_or_before(daily_change(cue), days, CUE_MAX_AGE_DAYS)
    out = out.astype(float)
    labels = regime_labels(cfg, out)
    out["regime"] = labels
    for label, column in REGIME_COLUMNS.items():
        out[column] = [1.0 if x == label else 0.0 for x in labels]
    return out


def india_flow_features(inputs: dict, days: pd.DatetimeIndex) -> pd.DataFrame:
    """fii_net_cr, dii_net_cr (date <= d) and fpi_equity_net_cr (reporting date < d) per as-of date."""
    out = pd.DataFrame(index=days)
    flows = inputs.get("flows", pd.DataFrame())
    for category, column in (("FII/FPI", "fii_net_cr"), ("DII", "dii_net_cr")):
        rows = flows[flows["category"] == category] if not flows.empty else flows
        series = pd.Series(rows["net_cr"].to_numpy(), index=pd.to_datetime(rows["date"])) if len(rows) else \
            pd.Series(dtype=float)
        out[column] = latest_on_or_before(series, days, FLOW_MAX_AGE_DAYS)
    fpi = inputs.get("fpi", pd.DataFrame())
    series = pd.Series(fpi["net_cr"].to_numpy(), index=pd.to_datetime(fpi["date"])) if len(fpi) else \
        pd.Series(dtype=float)
    out["fpi_equity_net_cr"] = latest_on_or_before(series, days, FLOW_MAX_AGE_DAYS, strict=True)
    return out


def insider_net(rows: pd.DataFrame, day: pd.Timestamp) -> float:
    """sign * ln(1 + |net USD| / 1e6) of the purchases minus sales dated in the 30 days to `day`, accepted by it."""
    start = day - pd.Timedelta(days=INSIDER_WINDOW_DAYS)
    window = rows[(rows["seen"] <= day) & (rows["transaction_date"] > start) & (rows["transaction_date"] <= day)]
    net = float(window["signed_value"].fillna(0).sum())
    return float(np.sign(net) * np.log1p(abs(net) / INSIDER_SCALE_USD))


def us_flow_features(inputs: dict, ticker: str, days: pd.DatetimeIndex) -> pd.DataFrame:
    """short_volume_pct (date <= d) and insider_net_30d per as-of date for one ticker; NaN before the
    first stored row of the kind (no history is not the same as no flow)."""
    out = pd.DataFrame(index=days)
    shorts = inputs.get("shorts", pd.DataFrame())
    rows = shorts[shorts["ticker"] == ticker] if len(shorts) else shorts
    series = pd.Series(rows["short_pct"].to_numpy(), index=pd.to_datetime(rows["date"])) if len(rows) else \
        pd.Series(dtype=float)
    out["short_volume_pct"] = latest_on_or_before(series, days, FLOW_MAX_AGE_DAYS)
    insiders = inputs.get("insiders", pd.DataFrame())
    if insiders.empty:
        out["insider_net_30d"] = np.nan
        return out
    first_seen = insiders["seen"].min()
    own = insiders[insiders["ticker"] == ticker]
    out["insider_net_30d"] = [insider_net(own, d) if d >= first_seen else np.nan for d in days]
    return out
