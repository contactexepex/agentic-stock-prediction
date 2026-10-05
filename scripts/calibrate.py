#!/usr/bin/env python3
"""Daily range calibration for one market (self-calibration, docs/DESIGN.md section 4.5).

Pool = standardized returns of all watchlist tickers over the last `history_sessions` (from
stored bars, no AI) plus live scored ranges (their realized z), weighted by recency and with
live results counting `live_weight` times more. Writes the 10/25/75/90% quantiles per horizon
to data/<market>/calibration/. Falls back to normal quantiles when the pool is too small."""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import rangelib as rl
from common import (append_jsonl, benchmark_key, connect, day_file, load_ranges_config, market_arg,
                    require_market, utc_now)
from features import load_bars

QS = {"q10": 0.10, "q25": 0.25, "q75": 0.75, "q90": 0.90}


def history_pool(bars: dict[str, pd.DataFrame], tickers, h: int, rc: dict,
                 session_rank: dict) -> tuple[np.ndarray, np.ndarray]:
    zs, ages = [], []
    last = max(session_rank.values()) if session_rank else 0
    for t in tickers:
        df = bars.get(t)
        if df is None or len(df) < rc["warmup_bars"] + h + 1:
            continue
        s = rl.standardized(df["close"], h, rc["ewma_lambda"], rc["warmup_bars"])
        s = s[np.isfinite(s["z"])]
        for d, z in zip(s.index, s["z"]):
            r = session_rank.get(d)
            if r is not None and last - r < rc["history_sessions"]:
                zs.append(z)
                ages.append(last - r)
    return np.array(zs), np.array(ages, dtype=float)


def compute(cfg: dict, rc: dict, con, bars: dict[str, pd.DataFrame]) -> list[dict]:
    bench = bars[benchmark_key(cfg)]
    as_of = bench.index[-1].date()
    session_rank = {d: i for i, d in enumerate(bench.index)}
    live = con.execute("SELECT horizon_days, as_of_date, z FROM range_record WHERE z IS NOT NULL").df()
    now, rows = utc_now(), []
    for h in rc["horizons"]:
        z_hist, age_hist = history_pool(bars, cfg["tickers"], h, rc, session_rank)
        w_hist = rl.recency_weights(age_hist, rc["half_life_sessions"])
        lv = live[live["horizon_days"] == h] if not live.empty else live
        z_live = lv["z"].to_numpy(dtype=float) if len(lv) else np.array([])
        if len(lv):
            age_live = np.array([max(0, len(bench) - 1 - session_rank.get(pd.Timestamp(d), len(bench) - 1))
                                 for d in lv["as_of_date"]], dtype=float)
            w_live = rl.recency_weights(age_live, rc["half_life_sessions"]) * rc["live_weight"]
        else:
            w_live = np.array([])
        z, w = np.concatenate([z_hist, z_live]), np.concatenate([w_hist, w_live])
        if len(z) >= rc["min_pool"]:
            q = {k: rl.weighted_quantile(z, w, v) for k, v in QS.items()}
            source = "pool"
        else:
            lo80, hi80 = rl.normal_quantiles(0.8)
            lo50, hi50 = rl.normal_quantiles(0.5)
            q, source = {"q10": lo80, "q25": lo50, "q75": hi50, "q90": hi80}, "normal"
        rows.append({"id": f"{as_of}-{h}d", "as_of_date": str(as_of), "computed_at": now, "horizon_days": h,
                     **{k: round(v, 5) for k, v in q.items()}, "n_history": int(len(z_hist)),
                     "n_live": int(len(z_live)), "source": source})
    return rows


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    rc, con = load_ranges_config(cfg["market"]), connect(cfg["market"])
    bars = load_bars(con)
    if benchmark_key(cfg) not in bars:
        raise SystemExit("no benchmark bars; run collect_prices.py first")
    rows = compute(cfg, rc, con, bars)
    append_jsonl(day_file(cfg["market"], "calibration", pd.Timestamp(rows[0]["as_of_date"]).date()), rows)
    print(json.dumps({"step": "calibrate", "market": cfg["market"], "calibration": rows}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
