"""Daily range calibration for one market (self-calibration, docs/DESIGN.md section 4.5).

Pool = standardized returns of all watchlist tickers over the last `history_sessions` (from
stored bars, no AI) plus live scored ranges (their realized z), weighted by recency and with
live results counting `live_weight` times more. Writes the 10/25/75/90% quantiles per horizon
to data/<market>/calibration/. Falls back to normal quantiles when the pool is too small.
With `aci:` switched on in config/ranges.yaml (off by default), the four levels come from the ACI
miss rates (adaptive_conformal.py) of live range outcomes scored by now, and the row adds
aci_alpha50/80 and aci_steps; switched off, the rows are exactly as without ACI."""

from __future__ import annotations

import json
from statistics import NormalDist

import numpy as np
import pandas as pd

from marketbrief.analytics import adaptive_conformal
from marketbrief.analytics import range_math
from marketbrief.analytics.features import load_bars
from marketbrief.analytics.range_switches import enabled
from marketbrief.constants.calibration import (
    CALIBRATION_QUANTILES,
    LIVE_RANGE_SQL,
    MSG_NO_BENCHMARK,
    ROUND_DECIMALS,
    SOURCE_NORMAL,
    SOURCE_POOL,
    STEP_CALIBRATE,
    SWITCH_ACI,
)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core.market_config import benchmark_key, load_ranges_config
from marketbrief.core.storage import append_jsonl, day_file


def history_pool(
    bars: dict[str, pd.DataFrame], tickers, horizon: int, ranges_config: dict, session_rank: dict
) -> tuple[np.ndarray, np.ndarray]:
    """(standardized returns, their ages in sessions) of the tickers' stored bars for the horizon."""
    standardized_returns, ages = [], []
    last = max(session_rank.values()) if session_rank else 0
    for ticker in tickers:
        ticker_bars = bars.get(ticker)
        if ticker_bars is None or len(ticker_bars) < ranges_config["warmup_bars"] + horizon + 1:
            continue
        standardized_rows = range_math.standardized(
            ticker_bars["close"], horizon, ranges_config["ewma_lambda"], ranges_config["warmup_bars"]
        )
        standardized_rows = standardized_rows[np.isfinite(standardized_rows["z"])]
        for bar_date, standardized_return in zip(standardized_rows.index, standardized_rows["z"], strict=False):
            session_index = session_rank.get(bar_date)
            if session_index is not None and last - session_index < ranges_config["history_sessions"]:
                standardized_returns.append(standardized_return)
                ages.append(last - session_index)
    return np.array(standardized_returns), np.array(ages, dtype=float)


def live_pool(
    live: pd.DataFrame, horizon: int, bench: pd.DataFrame, session_rank: dict, ranges_config: dict
) -> tuple[np.ndarray, np.ndarray]:
    """(realized z, recency x live weights) of the scored live ranges of the horizon."""
    horizon_ranges = live[live["horizon_days"] == horizon] if not live.empty else live
    if not len(horizon_ranges):
        return np.array([]), np.array([])
    last = len(bench) - 1
    ages = np.array(
        [max(0, last - session_rank.get(pd.Timestamp(as_of_day), last)) for as_of_day in horizon_ranges["as_of_date"]],
        dtype=float,
    )
    weights = range_math.recency_weights(ages, ranges_config["half_life_sessions"]) * ranges_config["live_weight"]
    return horizon_ranges["z"].to_numpy(dtype=float), weights


def aci_state(con, cfg: dict, ranges_config: dict, as_of, now: str):
    """(tracker, regime key) when ACI is on for any horizon, else (None, 'all')."""
    if not any(enabled(ranges_config, SWITCH_ACI, cfg["market"], horizon) for horizon in ranges_config["horizons"]):
        return None, "all"
    # only range outcomes scored by now; with by_regime the alpha of the latest regime
    tracker = adaptive_conformal.live_tracker(con, ranges_config, now)
    reg = con.execute(
        "SELECT regime FROM regime_latest WHERE as_of_date <= ? ORDER BY as_of_date DESC LIMIT 1", [as_of]
    ).fetchone()
    return tracker, tracker.key(reg[0] if reg else None)


def quantiles(
    standardized_returns: np.ndarray, weights: np.ndarray, levels: dict, ranges_config: dict, use_aci: bool
) -> tuple[dict, str]:
    """(the quantiles of the pool, their source): normal ones when the pool is too small."""
    if len(standardized_returns) >= ranges_config["min_pool"]:
        return {
            level_name: range_math.weighted_quantile(standardized_returns, weights, level)
            for level_name, level in levels.items()
        }, SOURCE_POOL
    if use_aci:
        return {level_name: NormalDist().inv_cdf(level) for level_name, level in levels.items()}, SOURCE_NORMAL
    lo80, hi80 = range_math.normal_quantiles(0.8)
    lo50, hi50 = range_math.normal_quantiles(0.5)
    return {"q10": lo80, "q25": lo50, "q75": hi50, "q90": hi80}, SOURCE_NORMAL


def compute(cfg: dict, ranges_config: dict, con, bars: dict[str, pd.DataFrame], now: str | None = None) -> list[dict]:
    """The calibration row of each horizon."""
    bench = bars[benchmark_key(cfg)]
    as_of = bench.index[-1].date()
    session_rank = {bar_date: session_index for session_index, bar_date in enumerate(bench.index)}
    live = con.execute(LIVE_RANGE_SQL).df()
    now, rows = now or utc_now(), []
    tracker, akey = aci_state(con, cfg, ranges_config, as_of, now)
    for horizon in ranges_config["horizons"]:
        use_aci = tracker is not None and enabled(ranges_config, SWITCH_ACI, cfg["market"], horizon)
        levels = tracker.levels(horizon, akey) if use_aci else CALIBRATION_QUANTILES
        z_hist, age_hist = history_pool(bars, cfg["tickers"], horizon, ranges_config, session_rank)
        w_hist = range_math.recency_weights(age_hist, ranges_config["half_life_sessions"])
        z_live, w_live = live_pool(live, horizon, bench, session_rank, ranges_config)
        standardized_returns, weights = np.concatenate([z_hist, z_live]), np.concatenate([w_hist, w_live])
        pool_quantiles, source = quantiles(standardized_returns, weights, levels, ranges_config, use_aci)
        row = {
            "id": f"{as_of}-{horizon}d",
            "as_of_date": str(as_of),
            "computed_at": now,
            "horizon_days": horizon,
            **{level_name: round(quantile, ROUND_DECIMALS) for level_name, quantile in pool_quantiles.items()},
            "n_history": int(len(z_hist)),
            "n_live": int(len(z_live)),
            "source": source,
        }
        if use_aci:  # only when switched on, so rows with ACI off stay exactly as before
            row.update(
                {
                    "source": f"{source}+aci",
                    "aci_alpha50": round(2 * levels["q25"], ROUND_DECIMALS),
                    "aci_alpha80": round(2 * levels["q10"], ROUND_DECIMALS),
                    "aci_steps": int(tracker.steps.get((horizon, "80", akey), 0)),
                }
            )
        rows.append(row)
    return rows


def main() -> int:
    """Entry point of scripts/calibrate.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    ranges_config, con = load_ranges_config(cfg["market"]), connect(cfg["market"])
    bars = load_bars(con)
    if benchmark_key(cfg) not in bars:
        raise SystemExit(MSG_NO_BENCHMARK)
    rows = compute(cfg, ranges_config, con, bars)
    append_jsonl(day_file(cfg["market"], "calibration", pd.Timestamp(rows[0]["as_of_date"]).date()), rows)
    print(json.dumps({"step": STEP_CALIBRATE, "market": cfg["market"], "calibration": rows}, indent=2))
    return 0
