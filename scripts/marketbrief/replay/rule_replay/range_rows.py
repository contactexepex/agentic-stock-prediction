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


def ticker_frame(
    cfg: dict, ranges_config: dict, frame: pd.DataFrame, ticker: str, horizon: int, extra: dict
) -> pd.DataFrame:
    """Per as-of date of one ticker: close, EWMA sigma, 20-day sigma (naive), outcome, range inputs."""
    close = frame["close"]
    ticker_data = pd.DataFrame(
        {
            "close": close,
            "sigma": range_math.ewma_sigma(close, ranges_config["ewma_lambda"]),
            "s20": np.log(close / close.shift(1)).rolling(20).std(ddof=1),
            "fwd": np.log(close.shift(-horizon) / close),
            "bars": np.arange(1, len(close) + 1),
            "ret1": close / close.shift(1) - 1,
            "ret5": close / close.shift(5) - 1,
            "rsi": rsi_series(close),
        }
    )
    ticker_data = ticker_data.join(observations.input_columns(cfg, ranges_config, frame, ticker, horizon, extra))
    ticker_data["own"] = np.nan  # no stored pre-market/ADR history (next open = look-ahead)
    if (cfg.get("index_cue") or {}).get("beta", 1.0) != "fit":
        ticker_data["idx_cue"] = np.nan  # numeric beta: futures before the open, not stored
    ticker_data["target"] = pd.Series(frame.index, index=frame.index).shift(-horizon)
    return ticker_data


def replay_horizon(
    cfg: dict,
    ranges_config: dict,
    bars: dict,
    horizon: int,
    days: list[date],
    reg: pd.DataFrame,
    extra: dict,
    rank: dict,
    majors: list[date],
) -> pd.DataFrame:
    market_name = cfg["market"]
    use = {input_name: range_switches.enabled(ranges_config, input_name, market_name, horizon) for input_name in INPUTS}
    pool = observations.observations(bars, cfg["tickers"], horizon, ranges_config, rank)
    z_all = pool["z"].to_numpy() if len(pool) else np.array([])
    r_all = pool["rank"].to_numpy() if len(pool) else np.array([])
    frames = {
        ticker: ticker_frame(cfg, ranges_config, bars[ticker], ticker, horizon, extra)
        for ticker in cfg["tickers"]
        if ticker in bars
    }
    day_ts = [pd.Timestamp(day) for day in days]
    normal_dist = NormalDist()
    normal = {
        "q10": range_math.normal_quantiles(0.8)[0],
        "q25": range_math.normal_quantiles(0.5)[0],
        "q75": range_math.normal_quantiles(0.5)[1],
        "q90": range_math.normal_quantiles(0.8)[1],
    }
    fixed = ranges_config["earnings_vol_multiple"]
    beta_split = ranges_config["beta_split"]
    # ACI (adaptive_conformal.py; off unless config/ranges.yaml or --aci switches it on): each day's quantile levels
    # come from the misses of ranges whose target close is on or before d (known pre-open next session)
    tracker = (
        adaptive_conformal.Tracker(ranges_config)
        if range_switches.enabled(ranges_config, "aci", market_name, horizon)
        else None
    )
    pending: dict[int, dict[str, list]] = {}  # target rank -> key -> [n, misses50, misses80]
    rows = []
    for day, timestamp in zip(days, day_ts):
        rank_today = rank.get(timestamp)
        if rank_today is None:
            continue
        regime = reg.loc[day, "regime"] if day in reg.index else "EVENT_HEAVY"
        levels, akey = DEFAULT_LEVELS, None
        if tracker is not None:
            for target_rank in sorted(target_rank_key for target_rank_key in pending if target_rank_key <= rank_today):
                for key, (count, m50, m80) in sorted(pending.pop(target_rank).items()):
                    tracker.update(horizon, "50", key, m50 / count)
                    tracker.update(horizon, "80", key, m80 / count)
            akey = tracker.key(regime)
            levels = tracker.levels(horizon, akey)
        known = (r_all + horizon <= rank_today) & (r_all > rank_today - ranges_config["history_sessions"])
        if known.sum() >= ranges_config["min_pool"]:  # calibrate.py: pool quantiles, else normal ones
            z_pool, weight = (
                z_all[known],
                range_math.recency_weights(
                    (rank_today - r_all[known]).astype(float), ranges_config["half_life_sessions"]
                ),
            )
            quantiles = {
                level_name: range_math.weighted_quantile(z_pool, weight, level) for level_name, level in levels.items()
            }
            order = np.argsort(z_pool)
            sorted_z, warning_texts = z_pool[order], weight[order]
            cum = np.cumsum(warning_texts) - 0.5 * warning_texts
            pit = lambda item: float(np.interp(item, sorted_z, cum) / warning_texts.sum())  # noqa: E731  (inverse of weighted_quantile)
            source = "pool"
        else:
            quantiles = (
                normal
                if levels is DEFAULT_LEVELS
                else {level_name: normal_dist.inv_cdf(level) for level_name, level in levels.items()}
            )
            pit, source = normal_dist.cdf, "normal"
        tgt_cal = calendar.sessions_ahead(cfg, day + timedelta(days=1), horizon)[-1]  # ranges.target_date
        major = major_event_between(majors, day, tgt_cal)
        for ticker, frame in frames.items():
            if timestamp not in frame.index:
                continue
            observation = frame.loc[timestamp]
            daily_sigma = observation["sigma"]
            if (
                not (daily_sigma > 0 and math.isfinite(daily_sigma))
                or observation["bars"] < 31
                or not math.isfinite(observation["close"])
            ):
                continue  # ranges.py needs ewma_vol (31 bars)
            base = float(observation["close"])
            if use["earnings_history"]:
                in_h = bool(observation["earn"])
                m_hist = observation["m_hist"] if in_h and observation["m_hist"] == observation["m_hist"] else None
                mult = m_hist if m_hist is not None and m_hist != fixed else None
            else:
                event = next_earnings(extra["earnings"].get(ticker, []), day)
                in_h, mult = bool(event and event <= tgt_cal), None
            sigma_h, _ = range_math.horizon_sigma(float(daily_sigma), horizon, in_h, ranges_config, regime, major, mult)
            center = 0.0
            beta, idx_cue = observation["beta"], observation["idx_cue"]
            if use["beta_split"] and idx_cue == idx_cue and beta == beta:
                center += range_math.beta_split_center(
                    float(beta),
                    float(idx_cue),
                    None,
                    beta_split["index_weight"],
                    beta_split["own_weight"],
                    ranges_config["cue_weight"],
                )
            cap = ranges_config["max_center_shift_sigma"] * sigma_h
            center = max(-cap, min(cap, center))
            if use["ex_dividend"] and observation["div_shift"]:
                center += float(observation["div_shift"])
            band = lambda z_quantile: base * math.exp(center + z_quantile * sigma_h)  # noqa: E731
            row = {
                "date": day,
                "ticker": ticker,
                "rank": rank_today,
                "h": horizon,
                "regime": regime,
                "base": base,
                "alpha50": 2 * levels["q25"],
                "alpha80": 2 * levels["q10"],
                "center": center,
                "sigma_h": sigma_h,
                "q_source": source,
                "earn": in_h,
                "div": bool(use["ex_dividend"] and observation["div_shift"]),
                "major": major,
                "lo50": band(quantiles["q25"]),
                "hi50": band(quantiles["q75"]),
                "lo80": band(quantiles["q10"]),
                "hi80": band(quantiles["q90"]),
                "target_date": tgt_cal,
                "ret1": observation["ret1"],
                "ret5": observation["ret5"],
                "rsi": observation["rsi"],
            }
            s20 = observation["s20"]
            if s20 == s20 and s20 > 0:
                row["naive_lo50"], row["naive_hi50"] = range_math.naive_range(base, float(s20), horizon, 0.5)
                row["naive_lo80"], row["naive_hi80"] = range_math.naive_range(base, float(s20), horizon, 0.8)
            if observation["fwd"] == observation["fwd"]:
                close = base * math.exp(float(observation["fwd"]))
                zeff = (float(observation["fwd"]) - center) / sigma_h
                row.update(
                    {
                        "actual": close,
                        "bar_target": observation["target"].date(),
                        "fwd": float(observation["fwd"]),
                        "hit50": row["lo50"] <= close <= row["hi50"],
                        "hit80": row["lo80"] <= close <= row["hi80"],
                        "width50": 100 * (row["hi50"] - row["lo50"]) / base,
                        "width80": 100 * (row["hi80"] - row["lo80"]) / base,
                        "is50": 100 * range_math.interval_score(row["lo50"], row["hi50"], close, 0.5) / base,
                        "is80": 100 * range_math.interval_score(row["lo80"], row["hi80"], close, 0.8) / base,
                        "abs_err": 100 * abs(math.exp(float(observation["fwd"])) - math.exp(center)),
                        "pit": pit(zeff),
                        "qs": scoring.range_scores_row(row["lo50"], row["hi50"], row["lo80"], row["hi80"], close, base)[
                            "qs_pct"
                        ],
                    }
                )
                if tracker is not None:  # the outcome becomes known at the target close (rank rd + h)
                    acc = pending.setdefault(rank_today + horizon, {}).setdefault(akey, [0, 0, 0])
                    acc[0] += 1
                    acc[1] += not row["hit50"]
                    acc[2] += not row["hit80"]
                if "naive_lo80" in row:
                    row.update(
                        {
                            "naive_hit50": row["naive_lo50"] <= close <= row["naive_hi50"],
                            "naive_hit80": row["naive_lo80"] <= close <= row["naive_hi80"],
                            "naive_width80": 100 * (row["naive_hi80"] - row["naive_lo80"]) / base,
                            "naive_is50": 100
                            * range_math.interval_score(row["naive_lo50"], row["naive_hi50"], close, 0.5)
                            / base,
                            "naive_is80": 100
                            * range_math.interval_score(row["naive_lo80"], row["naive_hi80"], close, 0.8)
                            / base,
                        }
                    )
            rows.append(row)
    return pd.DataFrame(rows)


def replay_rows(
    cfg: dict, ranges_config: dict, bars: dict, extra: dict, start: date | None = None, end: date | None = None
) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    """Range rows per horizon (one per as-of day x ticker; scored where the outcome is stored) and
    the regime per day. Everything at d uses only what is known pre-open the next session."""
    bench = bars[benchmark_key(cfg)]
    days = window_days(bench, ranges_config, start, end)
    rank = {timestamp: position for position, timestamp in enumerate(bench.index)}
    reg = regimes(cfg, bars, days)
    majors = major_dates(cfg, days[0], days[-1] + timedelta(days=30)) if days else []
    out = {
        horizon: replay_horizon(cfg, ranges_config, bars, horizon, days, reg, extra, rank, majors)
        for horizon in ranges_config["horizons"]
    }
    return out, reg
