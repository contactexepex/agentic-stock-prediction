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
    """(standardized returns, their ages in sessions) of the tickers' stored bars for horizon h."""
    zs, ages = [], []
    last = max(session_rank.values()) if session_rank else 0
    for ticker in tickers:
        df = bars.get(ticker)
        if df is None or len(df) < ranges_config["warmup_bars"] + horizon + 1:
            continue
        s = range_math.standardized(df["close"], horizon, ranges_config["ewma_lambda"], ranges_config["warmup_bars"])
        s = s[np.isfinite(s["z"])]
        for d, z in zip(s.index, s["z"], strict=False):
            r = session_rank.get(d)
            if r is not None and last - r < ranges_config["history_sessions"]:
                zs.append(z)
                ages.append(last - r)
    return np.array(zs), np.array(ages, dtype=float)


def live_pool(
    live: pd.DataFrame, horizon: int, bench: pd.DataFrame, session_rank: dict, ranges_config: dict
) -> tuple[np.ndarray, np.ndarray]:
    """(realized z, recency x live weights) of the scored live ranges of horizon h."""
    lv = live[live["horizon_days"] == horizon] if not live.empty else live
    if not len(lv):
        return np.array([]), np.array([])
    last = len(bench) - 1
    ages = np.array([max(0, last - session_rank.get(pd.Timestamp(d), last)) for d in lv["as_of_date"]], dtype=float)
    weights = range_math.recency_weights(ages, ranges_config["half_life_sessions"]) * ranges_config["live_weight"]
    return lv["z"].to_numpy(dtype=float), weights


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


def quantiles(z: np.ndarray, w: np.ndarray, levels: dict, ranges_config: dict, use_aci: bool) -> tuple[dict, str]:
    """(the quantiles of the pool, their source): normal ones when the pool is too small."""
    if len(z) >= ranges_config["min_pool"]:
        return {k: range_math.weighted_quantile(z, w, v) for k, v in levels.items()}, SOURCE_POOL
    if use_aci:
        return {k: NormalDist().inv_cdf(v) for k, v in levels.items()}, SOURCE_NORMAL
    lo80, hi80 = range_math.normal_quantiles(0.8)
    lo50, hi50 = range_math.normal_quantiles(0.5)
    return {"q10": lo80, "q25": lo50, "q75": hi50, "q90": hi80}, SOURCE_NORMAL


def compute(cfg: dict, ranges_config: dict, con, bars: dict[str, pd.DataFrame], now: str | None = None) -> list[dict]:
    """The calibration row of each horizon."""
    bench = bars[benchmark_key(cfg)]
    as_of = bench.index[-1].date()
    session_rank = {d: i for i, d in enumerate(bench.index)}
    live = con.execute(LIVE_RANGE_SQL).df()
    now, rows = now or utc_now(), []
    tracker, akey = aci_state(con, cfg, ranges_config, as_of, now)
    for horizon in ranges_config["horizons"]:
        use_aci = tracker is not None and enabled(ranges_config, SWITCH_ACI, cfg["market"], horizon)
        levels = tracker.levels(horizon, akey) if use_aci else CALIBRATION_QUANTILES
        z_hist, age_hist = history_pool(bars, cfg["tickers"], horizon, ranges_config, session_rank)
        w_hist = range_math.recency_weights(age_hist, ranges_config["half_life_sessions"])
        z_live, w_live = live_pool(live, horizon, bench, session_rank, ranges_config)
        z, w = np.concatenate([z_hist, z_live]), np.concatenate([w_hist, w_live])
        q, source = quantiles(z, w, levels, ranges_config, use_aci)
        row = {
            "id": f"{as_of}-{horizon}d",
            "as_of_date": str(as_of),
            "computed_at": now,
            "horizon_days": horizon,
            **{k: round(v, ROUND_DECIMALS) for k, v in q.items()},
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
