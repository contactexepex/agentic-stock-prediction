"""The replayed ranges: one row per as-of day and ticker, built as ranges.py builds them."""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import NormalDist
import numpy as np
import pandas as pd
from marketbrief.replay.backtest import observations
from marketbrief.analytics import adaptive_conformal, range_switches
from marketbrief.analytics import range_math, scoring
from marketbrief.constants.range_inputs import INPUTS
from marketbrief.core.market_config import benchmark_key
from marketbrief.utils.event_dates import major_event_between
from marketbrief.core import calendar
from marketbrief.constants.replay import DEFAULT_LEVELS
from marketbrief.replay.rule_replay.inputs import major_dates, next_earnings, regimes, rsi_series, window_days


def ticker_frame(cfg: dict, rc: dict, df: pd.DataFrame, t: str, h: int, extra: dict) -> pd.DataFrame:
    """Per as-of date of one ticker: close, EWMA sigma, 20-day sigma (naive), outcome, range inputs."""
    c = df["close"]
    f = pd.DataFrame({"close": c, "sigma": range_math.ewma_sigma(c, rc["ewma_lambda"]),
                      "s20": np.log(c / c.shift(1)).rolling(20).std(ddof=1),
                      "fwd": np.log(c.shift(-h) / c), "bars": np.arange(1, len(c) + 1),
                      "ret1": c / c.shift(1) - 1, "ret5": c / c.shift(5) - 1, "rsi": rsi_series(c)})
    f = f.join(observations.input_columns(cfg, rc, df, t, h, extra))
    f["own"] = np.nan                      # no stored pre-market/ADR history (next open = look-ahead)
    if (cfg.get("index_cue") or {}).get("beta", 1.0) != "fit":
        f["idx_cue"] = np.nan              # numeric beta: futures before the open, not stored
    f["target"] = pd.Series(df.index, index=df.index).shift(-h)
    return f


def replay_horizon(cfg: dict, rc: dict, bars: dict, h: int, days: list[date], reg: pd.DataFrame,
                   extra: dict, rank: dict, majors: list[date]) -> pd.DataFrame:
    mk = cfg["market"]
    use = {k: range_switches.enabled(rc, k, mk, h) for k in INPUTS}
    pool = observations.observations(bars, cfg["tickers"], h, rc, rank)
    z_all = pool["z"].to_numpy() if len(pool) else np.array([])
    r_all = pool["rank"].to_numpy() if len(pool) else np.array([])
    frames = {t: ticker_frame(cfg, rc, bars[t], t, h, extra) for t in cfg["tickers"] if t in bars}
    day_ts = [pd.Timestamp(d) for d in days]
    nd = NormalDist()
    normal = {"q10": range_math.normal_quantiles(0.8)[0], "q25": range_math.normal_quantiles(0.5)[0],
              "q75": range_math.normal_quantiles(0.5)[1], "q90": range_math.normal_quantiles(0.8)[1]}
    fixed = rc["earnings_vol_multiple"]
    bs = rc["beta_split"]
    # ACI (adaptive_conformal.py; off unless config/ranges.yaml or --aci switches it on): each day's quantile levels
    # come from the misses of ranges whose target close is on or before d (known pre-open next session)
    tracker = adaptive_conformal.Tracker(rc) if range_switches.enabled(rc, "aci", mk, h) else None
    pending: dict[int, dict[str, list]] = {}   # target rank -> key -> [n, misses50, misses80]
    rows = []
    for d, ts in zip(days, day_ts):
        rd = rank.get(ts)
        if rd is None:
            continue
        regime = reg.loc[d, "regime"] if d in reg.index else "EVENT_HEAVY"
        levels, akey = DEFAULT_LEVELS, None
        if tracker is not None:
            for tr in sorted(k for k in pending if k <= rd):
                for key, (n, m50, m80) in sorted(pending.pop(tr).items()):
                    tracker.update(h, "50", key, m50 / n)
                    tracker.update(h, "80", key, m80 / n)
            akey = tracker.key(regime)
            levels = tracker.levels(h, akey)
        known = (r_all + h <= rd) & (r_all > rd - rc["history_sessions"])
        if known.sum() >= rc["min_pool"]:       # calibrate.py: pool quantiles, else normal ones
            z, w = z_all[known], range_math.recency_weights((rd - r_all[known]).astype(float), rc["half_life_sessions"])
            q = {k: range_math.weighted_quantile(z, w, p) for k, p in levels.items()}
            order = np.argsort(z)
            zs, ws = z[order], w[order]
            cum = np.cumsum(ws) - 0.5 * ws
            pit = lambda x: float(np.interp(x, zs, cum) / ws.sum())   # noqa: E731  (inverse of weighted_quantile)
            source = "pool"
        else:
            q = normal if levels is DEFAULT_LEVELS else {k: nd.inv_cdf(p) for k, p in levels.items()}
            pit, source = nd.cdf, "normal"
        tgt_cal = calendar.sessions_ahead(cfg, d + timedelta(days=1), h)[-1]   # ranges.target_date
        major = major_event_between(majors, d, tgt_cal)
        for t, f in frames.items():
            if ts not in f.index:
                continue
            o = f.loc[ts]
            sd = o["sigma"]
            if not (sd > 0 and math.isfinite(sd)) or o["bars"] < 31 or not math.isfinite(o["close"]):
                continue   # ranges.py needs ewma_vol (31 bars)
            base = float(o["close"])
            if use["earnings_history"]:
                in_h = bool(o["earn"])
                m_hist = o["m_hist"] if in_h and o["m_hist"] == o["m_hist"] else None
                mult = m_hist if m_hist is not None and m_hist != fixed else None
            else:
                e = next_earnings(extra["earnings"].get(t, []), d)
                in_h, mult = bool(e and e <= tgt_cal), None
            sigma_h, _ = range_math.horizon_sigma(float(sd), h, in_h, rc, regime, major, mult)
            center = 0.0
            beta, idx_cue = o["beta"], o["idx_cue"]
            if use["beta_split"] and idx_cue == idx_cue and beta == beta:
                center += range_math.beta_split_center(float(beta), float(idx_cue), None, bs["index_weight"],
                                               bs["own_weight"], rc["cue_weight"])
            cap = rc["max_center_shift_sigma"] * sigma_h
            center = max(-cap, min(cap, center))
            if use["ex_dividend"] and o["div_shift"]:
                center += float(o["div_shift"])
            band = lambda zq: base * math.exp(center + zq * sigma_h)  # noqa: E731
            row = {"date": d, "ticker": t, "rank": rd, "h": h, "regime": regime, "base": base,
                   "alpha50": 2 * levels["q25"], "alpha80": 2 * levels["q10"],
                   "center": center, "sigma_h": sigma_h, "q_source": source, "earn": in_h,
                   "div": bool(use["ex_dividend"] and o["div_shift"]), "major": major,
                   "lo50": band(q["q25"]), "hi50": band(q["q75"]), "lo80": band(q["q10"]), "hi80": band(q["q90"]),
                   "target_date": tgt_cal, "ret1": o["ret1"], "ret5": o["ret5"], "rsi": o["rsi"]}
            s20 = o["s20"]
            if s20 == s20 and s20 > 0:
                row["naive_lo50"], row["naive_hi50"] = range_math.naive_range(base, float(s20), h, 0.5)
                row["naive_lo80"], row["naive_hi80"] = range_math.naive_range(base, float(s20), h, 0.8)
            if o["fwd"] == o["fwd"]:
                y = base * math.exp(float(o["fwd"]))
                zeff = (float(o["fwd"]) - center) / sigma_h
                row.update({"actual": y, "bar_target": o["target"].date(), "fwd": float(o["fwd"]),
                            "hit50": row["lo50"] <= y <= row["hi50"], "hit80": row["lo80"] <= y <= row["hi80"],
                            "width50": 100 * (row["hi50"] - row["lo50"]) / base,
                            "width80": 100 * (row["hi80"] - row["lo80"]) / base,
                            "is50": 100 * range_math.interval_score(row["lo50"], row["hi50"], y, 0.5) / base,
                            "is80": 100 * range_math.interval_score(row["lo80"], row["hi80"], y, 0.8) / base,
                            "abs_err": 100 * abs(math.exp(float(o["fwd"])) - math.exp(center)), "pit": pit(zeff),
                            "qs": scoring.range_scores_row(row["lo50"], row["hi50"], row["lo80"], row["hi80"], y, base)["qs_pct"]})
                if tracker is not None:   # the outcome becomes known at the target close (rank rd + h)
                    acc = pending.setdefault(rd + h, {}).setdefault(akey, [0, 0, 0])
                    acc[0] += 1
                    acc[1] += not row["hit50"]
                    acc[2] += not row["hit80"]
                if "naive_lo80" in row:
                    row.update({"naive_hit50": row["naive_lo50"] <= y <= row["naive_hi50"],
                                "naive_hit80": row["naive_lo80"] <= y <= row["naive_hi80"],
                                "naive_width80": 100 * (row["naive_hi80"] - row["naive_lo80"]) / base,
                                "naive_is50": 100 * range_math.interval_score(row["naive_lo50"], row["naive_hi50"], y, 0.5) / base,
                                "naive_is80": 100 * range_math.interval_score(row["naive_lo80"], row["naive_hi80"], y, 0.8) / base})
            rows.append(row)
    return pd.DataFrame(rows)


def replay_rows(cfg: dict, rc: dict, bars: dict, extra: dict, start: date | None = None,
                end: date | None = None) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    """Range rows per horizon (one per as-of day x ticker; scored where the outcome is stored) and
    the regime per day. Everything at d uses only what is known pre-open the next session."""
    bench = bars[benchmark_key(cfg)]
    days = window_days(bench, rc, start, end)
    rank = {x: i for i, x in enumerate(bench.index)}
    reg = regimes(cfg, bars, days)
    majors = major_dates(cfg, days[0], days[-1] + timedelta(days=30)) if days else []
    out = {h: replay_horizon(cfg, rc, bars, h, days, reg, extra, rank, majors) for h in rc["horizons"]}
    return out, reg
