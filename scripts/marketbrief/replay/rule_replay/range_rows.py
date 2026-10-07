"""The replayed ranges: one row per as-of day, ticker and horizon N+k, built as ranges.py builds them (the window
from the as-of close to the exit close spans k + 1 sessions, core/horizons.window_sessions)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np
import pandas as pd

from marketbrief.analytics import adaptive_conformal, range_math, range_switches, scoring
from marketbrief.constants.range_inputs import INPUTS
from marketbrief.constants.replay import DEFAULT_LEVELS, MIN_EWMA_BARS
from marketbrief.core import calendar
from marketbrief.core.horizons import window_sessions
from marketbrief.core.market_config import benchmark_key
from marketbrief.replay.backtest import observations
from marketbrief.replay.rule_replay.inputs import major_dates, next_earnings, regimes, rsi_series, window_days
from marketbrief.utils.event_dates import major_event_between


def ticker_frame(
    cfg: dict, ranges_config: dict, frame: pd.DataFrame, ticker: str, horizon: int, extra: dict
) -> pd.DataFrame:
    """Per as-of date of one ticker: close, EWMA sigma, 20-day sigma (naive), outcome at the exit close of N+k
    (k + 1 sessions after the as-of close), range inputs."""
    close = frame["close"]
    sessions = window_sessions(horizon)
    ticker_data = pd.DataFrame(
        {
            "close": close,
            "sigma": range_math.ewma_sigma(close, ranges_config["ewma_lambda"]),
            "s20": np.log(close / close.shift(1)).rolling(20).std(ddof=1),
            "fwd": np.log(close.shift(-sessions) / close),
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
    ticker_data["target"] = pd.Series(frame.index, index=frame.index).shift(-sessions)
    return ticker_data


@dataclass
class DayContext:
    """What every ticker of one as-of day shares: regime, quantile levels and quantiles, target date, event."""

    day: date
    rank_today: int
    regime: str
    levels: dict
    aci_key: str | None
    quantiles: dict
    pit: object
    quantile_source: str
    target_date: date
    major: bool


class HorizonReplay:
    """Replay of one horizon: the pooled outcomes, each ticker's frame and the optional ACI tracker."""

    def __init__(self, cfg: dict, ranges_config: dict, bars: dict, horizon: int, extra: dict, rank: dict):
        """Prepare the pool of outcomes, the ticker frames, the quantiles and the ACI tracker."""
        self.cfg, self.ranges_config, self.horizon, self.extra, self.rank = cfg, ranges_config, horizon, extra, rank
        self.sessions = window_sessions(horizon)  # as-of close -> exit close of N+k
        self.market_name = cfg["market"]
        self.use = {
            input_name: range_switches.enabled(ranges_config, input_name, self.market_name, horizon)
            for input_name in INPUTS
        }
        pool = observations.observations(bars, cfg["tickers"], horizon, ranges_config, rank)
        self.pool_z = pool["z"].to_numpy() if len(pool) else np.array([])
        self.pool_rank = pool["rank"].to_numpy() if len(pool) else np.array([])
        self.frames = {
            ticker: ticker_frame(cfg, ranges_config, bars[ticker], ticker, horizon, extra)
            for ticker in cfg["tickers"]
            if ticker in bars
        }
        self.normal_dist = NormalDist()
        self.normal = {
            "q10": range_math.normal_quantiles(0.8)[0],
            "q25": range_math.normal_quantiles(0.5)[0],
            "q75": range_math.normal_quantiles(0.5)[1],
            "q90": range_math.normal_quantiles(0.8)[1],
        }
        # ACI (adaptive_conformal.py; off unless config/ranges.yaml or --aci switches it on): each day's quantile
        # levels come from the misses of ranges whose exit close is on or before d (known pre-open next session)
        self.tracker = (
            adaptive_conformal.Tracker(ranges_config)
            if range_switches.enabled(ranges_config, "aci", self.market_name, horizon)
            else None
        )
        self.pending: dict[int, dict[str, list]] = {}  # exit rank -> key -> [n, misses50, misses80]

    def run(self, days: list[date], regime_frame: pd.DataFrame, majors: list[date]) -> pd.DataFrame:
        """One row per as-of day and ticker, scored where the outcome is stored."""
        rows = []
        for day in days:
            timestamp = pd.Timestamp(day)
            rank_today = self.rank.get(timestamp)
            if rank_today is None:
                continue
            regime = regime_frame.loc[day, "regime"] if day in regime_frame.index else "EVENT_HEAVY"
            context = self.day_context(day, rank_today, regime, majors)
            for ticker, frame in self.frames.items():
                if timestamp not in frame.index:
                    continue
                row = self.ticker_row(ticker, frame.loc[timestamp], context)
                if row is not None:
                    rows.append(row)
        return pd.DataFrame(rows)

    def learn_known_outcomes(self, rank_today: int) -> None:
        """Feed the ACI tracker the miss rates of ranges whose target close is on or before today."""
        for target_rank in sorted(pending_rank for pending_rank in self.pending if pending_rank <= rank_today):
            for key, (count, misses50, misses80) in sorted(self.pending.pop(target_rank).items()):
                self.tracker.update(self.horizon, "50", key, misses50 / count)
                self.tracker.update(self.horizon, "80", key, misses80 / count)

    def day_context(self, day: date, rank_today: int, regime: str, majors: list[date]) -> DayContext:
        """Quantile levels (fixed or from ACI), quantiles (pool or normal), target date and major-event flag."""
        levels, aci_key = DEFAULT_LEVELS, None
        if self.tracker is not None:
            self.learn_known_outcomes(rank_today)
            aci_key = self.tracker.key(regime)
            levels = self.tracker.levels(self.horizon, aci_key)
        quantiles, pit, source = self.quantiles_for(rank_today, levels)
        # range_context.target_date: the exit session of N+k
        target_date = calendar.sessions_ahead(self.cfg, day + timedelta(days=1), self.sessions)[-1]
        major = major_event_between(majors, day, target_date)
        return DayContext(day, rank_today, regime, levels, aci_key, quantiles, pit, source, target_date, major)

    def quantiles_for(self, rank_today: int, levels: dict):
        """calibrate.py: weighted pool quantiles when the pool is big enough, else normal ones."""
        ranges_config = self.ranges_config
        known = (self.pool_rank + self.sessions <= rank_today) & (
            self.pool_rank > rank_today - ranges_config["history_sessions"]
        )
        if known.sum() >= ranges_config["min_pool"]:
            z_pool = self.pool_z[known]
            weight = range_math.recency_weights(
                (rank_today - self.pool_rank[known]).astype(float), ranges_config["half_life_sessions"]
            )
            quantiles = {
                level_name: range_math.weighted_quantile(z_pool, weight, level) for level_name, level in levels.items()
            }
            order = np.argsort(z_pool)
            sorted_z, sorted_weights = z_pool[order], weight[order]
            cumulative = np.cumsum(sorted_weights) - 0.5 * sorted_weights

            def pit(value):
                """Probability integral transform: the inverse of weighted_quantile on the pool."""
                return float(np.interp(value, sorted_z, cumulative) / sorted_weights.sum())

            return quantiles, pit, "pool"
        quantiles = (
            self.normal
            if levels is DEFAULT_LEVELS
            else {level_name: self.normal_dist.inv_cdf(level) for level_name, level in levels.items()}
        )
        return quantiles, self.normal_dist.cdf, "normal"

    def sigma_and_center(self, ticker: str, observation, context: DayContext):
        """Earnings flag, horizon sigma and centre shift (beta split, ex-dividend) of one ticker-day."""
        ranges_config = self.ranges_config
        if self.use["earnings_history"]:
            in_horizon = bool(observation["earn"])
            history_multiple = (
                observation["m_hist"] if in_horizon and observation["m_hist"] == observation["m_hist"] else None
            )
            fixed = ranges_config["earnings_vol_multiple"]
            multiple = history_multiple if history_multiple is not None and history_multiple != fixed else None
        else:
            next_date = next_earnings(self.extra["earnings"].get(ticker, []), context.day)
            in_horizon, multiple = bool(next_date and next_date <= context.target_date), None
        sigma_h, _ = range_math.horizon_sigma(
            float(observation["sigma"]),
            self.sessions,
            in_horizon,
            ranges_config,
            context.regime,
            context.major,
            multiple,
        )
        center = 0.0
        beta, index_cue = observation["beta"], observation["idx_cue"]
        if self.use["beta_split"] and index_cue == index_cue and beta == beta:
            beta_split = ranges_config["beta_split"]
            center += range_math.beta_split_center(
                float(beta),
                float(index_cue),
                None,
                beta_split["index_weight"],
                beta_split["own_weight"],
                ranges_config["cue_weight"],
            )
        cap = ranges_config["max_center_shift_sigma"] * sigma_h
        center = max(-cap, min(cap, center))
        if self.use["ex_dividend"] and observation["div_shift"]:
            center += float(observation["div_shift"])
        return in_horizon, sigma_h, center

    def ticker_row(self, ticker: str, observation, context: DayContext) -> dict | None:
        """The replayed range of one ticker-day with its outcome, or None when ranges.py would skip it."""
        daily_sigma = observation["sigma"]
        if (
            not (daily_sigma > 0 and math.isfinite(daily_sigma))
            or observation["bars"] < MIN_EWMA_BARS
            or not math.isfinite(observation["close"])
        ):
            return None  # ranges.py needs ewma_vol (31 bars)
        base = float(observation["close"])
        in_horizon, sigma_h, center = self.sigma_and_center(ticker, observation, context)

        def band(z_quantile):
            """The price at a standardised quantile around the centre."""
            return base * math.exp(center + z_quantile * sigma_h)

        quantiles, levels = context.quantiles, context.levels
        row = {
            "date": context.day,
            "ticker": ticker,
            "rank": context.rank_today,
            "h": self.horizon,
            "regime": context.regime,
            "base": base,
            "alpha50": 2 * levels["q25"],
            "alpha80": 2 * levels["q10"],
            "center": center,
            "sigma_h": sigma_h,
            "q_source": context.quantile_source,
            "earn": in_horizon,
            "div": bool(self.use["ex_dividend"] and observation["div_shift"]),
            "major": context.major,
            "lo50": band(quantiles["q25"]),
            "hi50": band(quantiles["q75"]),
            "lo80": band(quantiles["q10"]),
            "hi80": band(quantiles["q90"]),
            "target_date": context.target_date,
            "ret1": observation["ret1"],
            "ret5": observation["ret5"],
            "rsi": observation["rsi"],
        }
        naive_sigma = observation["s20"]
        if naive_sigma == naive_sigma and naive_sigma > 0:
            row["naive_lo50"], row["naive_hi50"] = range_math.naive_range(base, float(naive_sigma), self.sessions, 0.5)
            row["naive_lo80"], row["naive_hi80"] = range_math.naive_range(base, float(naive_sigma), self.sessions, 0.8)
        if observation["fwd"] == observation["fwd"]:
            self.add_outcome(row, observation, context, base, center, sigma_h)
        return row

    def add_outcome(self, row: dict, observation, context: DayContext, base: float, center: float, sigma_h: float):
        """Score the range on the stored close and queue the outcome for the ACI tracker."""
        close = base * math.exp(float(observation["fwd"]))
        standardized = (float(observation["fwd"]) - center) / sigma_h
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
                "pit": context.pit(standardized),
                "qs": scoring.range_scores_row(row["lo50"], row["hi50"], row["lo80"], row["hi80"], close, base)[
                    "qs_pct"
                ],
            }
        )
        if self.tracker is not None:  # the outcome becomes known at the exit close (rank today + k + 1)
            accumulator = self.pending.setdefault(context.rank_today + self.sessions, {}).setdefault(
                context.aci_key, [0, 0, 0]
            )
            accumulator[0] += 1
            accumulator[1] += not row["hit50"]
            accumulator[2] += not row["hit80"]
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


def replay_rows(
    cfg: dict, ranges_config: dict, bars: dict, extra: dict, start: date | None = None, end: date | None = None
) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    """Range rows per horizon (one per as-of day x ticker; scored where the outcome is stored) and
    the regime per day. Everything at d uses only what is known pre-open the next session."""
    bench = bars[benchmark_key(cfg)]
    days = window_days(bench, ranges_config, start, end)
    rank = {timestamp: position for position, timestamp in enumerate(bench.index)}
    regime_frame = regimes(cfg, bars, days)
    majors = major_dates(cfg, days[0], days[-1] + timedelta(days=30)) if days else []
    out = {
        horizon: HorizonReplay(cfg, ranges_config, bars, horizon, extra, rank).run(days, regime_frame, majors)
        for horizon in ranges_config["horizons"]
    }
    return out, regime_frame
