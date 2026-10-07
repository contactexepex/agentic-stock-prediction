"""The market overview of the dashboard: benchmark and volatility index from the stored bars, the
regime in plain words, the overnight cues and global factors from the newest stored quotes, and the
sector moves (the mean 1-day and 5-day return of each sector's stocks, as the HTML report computes
the 1-day move)."""

from __future__ import annotations

import pandas as pd
from view_data import REGIME_PLAIN

from marketbrief.constants.dashboard import CUE_ROLES
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.lifecycle.loader import active_sectors, active_tickers
from marketbrief.presentation.dashboard.stock import as_list, bar_rows, iso_time, last_session
from marketbrief.utils.numbers import json_safe_float

SPARK_BARS = 30


def index_tile(cfg: dict, key: str | None, bars: pd.DataFrame) -> dict | None:
    """A market-level symbol's last session (close, change, gap) and its last closes for a sparkline."""
    if not key:
        return None
    rows = bar_rows(bars[bars["ticker"] == key])
    return {
        "key": key,
        "name": cfg["symbols"].get(key, {}).get("name", key),
        "last": last_session(rows),
        "spark": [[r[0], r[4]] for r in rows[-SPARK_BARS:]],
    }


def regime_view(row: dict | None) -> dict | None:
    """The regime row with its plain-language meaning."""
    if row is None:
        return None
    code = row["regime"]
    return {
        "code": code,
        "plain": REGIME_PLAIN.get(code, code),
        "as_of": pd.Timestamp(row["as_of_date"]).date().isoformat(),
        "stress": bool(row["stress"]),
        "vol_level": json_safe_float(row["vol_level"]),
        "vol_change_1d": json_safe_float(row["vol_change_1d"]),
        "bench_ret_5d": json_safe_float(row["bench_ret_5d"]),
        "major_events": as_list(row["major_event_names"]),
        "notes": as_list(row["notes"]),
    }


def cue_rows(cfg: dict, quotes: pd.DataFrame) -> list[dict]:
    """Cue and factor symbols of the market config with their newest stored quote."""
    by_symbol = {q.symbol: q for q in quotes.itertuples()} if len(quotes) else {}
    out = []
    for key, meta in cfg["symbols"].items():
        if meta.get("role") not in CUE_ROLES:
            continue
        q = by_symbol.get(key)
        out.append(
            {
                "key": key,
                "name": meta.get("name", key),
                "role": meta["role"],
                "price": json_safe_float(q.price) if q is not None else None,
                "change": json_safe_float(q.change_pct) if q is not None else None,
                "quoted_at": iso_time(q.ts) if q is not None else None,
                "collected_at": iso_time(q.collected_at) if q is not None else None,
            }
        )
    return out


def sector_rows(cfg: dict, feats: pd.DataFrame) -> list[dict]:
    """Per sector: each stock's 1-day and 5-day return and the sector's mean of each."""
    indexed = feats.set_index("ticker") if len(feats) else feats
    out = []
    for sector, members in (active_sectors(cfg) if cfg.get("sectors") else {"": active_tickers(cfg)}).items():
        stocks = []
        for t in members:
            f = indexed.loc[t] if t in indexed.index else None
            stocks.append(
                {
                    "ticker": t,
                    "ret_1d": json_safe_float(f["ret_1d"]) if f is not None else None,
                    "ret_5d": json_safe_float(f["ret_5d"]) if f is not None else None,
                }
            )
        one = [s["ret_1d"] for s in stocks if s["ret_1d"] is not None]
        five = [s["ret_5d"] for s in stocks if s["ret_5d"] is not None]
        out.append(
            {
                "sector": sector,
                "stocks": stocks,
                "move_1d": sum(one) / len(one) if one else None,
                "move_5d": sum(five) / len(five) if five else None,
            }
        )
    return out


def overview(cfg: dict, bars: pd.DataFrame, regime_row: dict | None, quotes: pd.DataFrame, feats: pd.DataFrame) -> dict:
    """Benchmark, volatility index, regime, cues and sectors."""
    return {
        "benchmark": index_tile(cfg, benchmark_key(cfg), bars),
        "vol_index": index_tile(cfg, vol_index_key(cfg), bars),
        "regime": regime_view(regime_row),
        "cues": cue_rows(cfg, quotes),
        "sectors": sector_rows(cfg, feats),
    }
