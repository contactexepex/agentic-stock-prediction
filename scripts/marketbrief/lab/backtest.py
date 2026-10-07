"""F2.3 back-test of the strategies that need no news (always-up and momentum from bars; model-only when B10's
walk-forward probabilities per horizon are given), on adjusted daily bars: data/'s stored bars, plus the long-history
cache's earlier dates with --history (model/history_cache.py). Labelled basis "backtest" and never pooled with
forward results; written only to the output folder, never to data/.

Each as-of row t of a ticker (its own stored sessions): entry at the open of the next row (D), exit at the close of
the k-th row after D (N+k), the market's default amount, the quantity rule of F1.4, the costs of lab/costs.py (US
order fee at the EUR/USD close on or before each side, from the stored or cached EURUSD bars). Limits: today's
watchlist (survivorship bias), split adjustment as of the fetch, no target or range (no stored ranges in the past)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.contracts.watchlist import DEFAULT_AMOUNT
from marketbrief.lab.constants import (MIN_RANKED_TRADES, MONEY_DIGITS, PCT_DIGITS, PERCENT, PROB_DIGITS,
                                       SIGNAL_ALWAYS_UP, SIGNAL_MODEL, SIGNAL_MOMENTUM)
from marketbrief.lab.luck import luck_test


def frame_costs(market: str, rate: dict, values: tuple[np.ndarray, np.ndarray], shares: np.ndarray,
                eurusd: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """lab/costs.round_trip_costs for arrays (each line rounded to cents, then summed)."""
    entry, exit_ = values
    both = entry + exit_
    if market == "india":
        brokerage, exchange = rate.get("brokerage_each_side", 0.0) * both, rate["exchange_txn_each_side"] * both
        sebi = rate["sebi_fee_each_side"] * both
        dp = np.maximum(rate.get("dp_charge_min", 0.0), rate.get("dp_charge_rate", 0.0) * exit_)
        lines = [brokerage, rate["stt_each_side"] * both, exchange, sebi, rate["stamp_duty_buy"] * entry, dp,
                 rate["gst_rate"] * (brokerage + exchange + sebi + dp), rate.get("slippage_each_side", 0.0) * both]
    else:
        fee = rate.get("order_fee_eur", 0.0)
        lines = [fee * eurusd[0] + fee * eurusd[1], rate["sec_fee_sell"] * exit_,
                 np.minimum(rate["finra_taf_per_share_sell"] * shares, rate["finra_taf_max_per_trade"]),
                 rate.get("commission_each_side", 0.0) * both, rate.get("slippage_each_side", 0.0) * both]
    return np.sum([np.round(line, MONEY_DIGITS) for line in lines], axis=0)


def rate_series(eurusd: pd.Series | None, dates: pd.Series) -> np.ndarray:
    """The newest EUR/USD close on or before each date (the oldest one before the series starts)."""
    if eurusd is None or eurusd.empty:
        return np.full(len(dates), np.nan)
    eurusd = eurusd.dropna().sort_index()
    pos = np.searchsorted(eurusd.index.values, pd.DatetimeIndex(dates).values, side="right") - 1
    return eurusd.to_numpy(dtype=float)[np.clip(pos, 0, None)]


def ticker_trades(market: str, bars: pd.DataFrame, horizon: int, context: dict) -> pd.DataFrame:
    """Every as-of row's N+k trade of one ticker (before the signal filter): as_of, entry/exit dates, net, return,
    up_last (momentum)."""
    bars = bars.dropna(subset=["open", "close"]).sort_index()
    n = len(bars) - 1 - horizon
    if n <= 0:
        return pd.DataFrame()
    opens, closes = bars["open"].to_numpy(dtype=float), bars["close"].to_numpy(dtype=float)
    dates = pd.Series(bars.index)
    amount = DEFAULT_AMOUNT[market]
    entry_price, exit_price = opens[1:n + 1], closes[1 + horizon:n + 1 + horizon]
    shares = np.floor(amount / entry_price) if market == "india" else np.round(amount / entry_price, 6)
    entry_value, exit_value = shares * entry_price, shares * exit_price
    fx = (rate_series(context.get("eurusd"), dates[1:n + 1]), rate_series(context.get("eurusd"),
                                                                          dates[1 + horizon:n + 1 + horizon]))
    cost = frame_costs(market, context["rate"], (entry_value, exit_value), shares, fx)
    net = exit_value - entry_value - cost
    previous = np.concatenate([[np.nan], closes[:-1]])
    out = pd.DataFrame({"as_of": dates[:n].to_numpy(), "entry_date": dates[1:n + 1].to_numpy(),
                        "exit_date": dates[1 + horizon:n + 1 + horizon].to_numpy(), "shares": shares,
                        "net_pnl": net, "return_pct": net / amount * PERCENT, "up_last": closes[:n] > previous[:n]})
    return out[out["shares"] > 0]


def signal_mask(trades: pd.DataFrame, spec: dict, probs: pd.Series | None) -> np.ndarray:
    """Which as-of rows trade under the strategy (always-up: all; momentum: last session up; model: p >= threshold)."""
    signal = spec["parameters"]["signal"]
    if signal == SIGNAL_ALWAYS_UP:
        return np.ones(len(trades), dtype=bool)
    if signal == SIGNAL_MOMENTUM:
        return trades["up_last"].to_numpy(dtype=bool)
    if signal == SIGNAL_MODEL and probs is not None:
        p = probs.reindex(pd.DatetimeIndex(trades["as_of"])).to_numpy(dtype=float)
        return np.nan_to_num(p, nan=0.0) >= float(spec["threshold"])
    return np.zeros(len(trades), dtype=bool)


def summary(trades: pd.DataFrame, key: str, m: int) -> dict:
    """The scoreboard numbers of a back-test slice (no target or range measures)."""
    trades = trades.sort_values(["exit_date", "ticker", "as_of"])
    net = trades["net_pnl"].to_numpy()
    streak = worst = 0
    for value in net:
        streak = streak + 1 if value < 0 else 0
        worst = max(worst, streak)
    total = np.cumsum(net)
    drawdown = float(np.min(total - np.maximum.accumulate(np.maximum(total, 0.0)))) if len(net) else 0.0
    returns = trades["return_pct"].to_numpy()
    return {"trades": int(len(net)), "net_pnl": round(float(net.sum()), MONEY_DIGITS),
            "mean_return_pct": round(float(returns.mean()), PCT_DIGITS) if len(net) else None,
            "win_rate": round(float((net > 0).mean()), PROB_DIGITS) if len(net) else None,
            "worst_losing_streak": worst,
            "max_drawdown": round(min(drawdown, 0.0), MONEY_DIGITS),
            "target_reached_rate": None, "median_reached_session": None, "avg_target_error_pct": None,
            "range_hit_rate": None, "luck_test": luck_test(returns.tolist(), key, m),
            "sample_badge": "too_few_to_rank" if len(net) < MIN_RANKED_TRADES else "ok",
            "first_entry": str(trades["entry_date"].min().date()) if len(net) else None,
            "last_exit": str(trades["exit_date"].max().date()) if len(net) else None}


def run_backtest(market: str, bars: dict[str, pd.DataFrame], specs: list[dict], horizons: tuple[int, ...],
                 context: dict) -> list[dict]:
    """Scoreboard rows (basis backtest, view accuracy) per strategy and horizon ("all" = pooled). context: rate,
    eurusd (Series by date or None), probs ({(ticker, k): Series of p by as-of date} or None)."""
    probs = context.get("probs") or {}
    usable = [s for s in specs if s["parameters"]["signal"] in (SIGNAL_ALWAYS_UP, SIGNAL_MOMENTUM)
              or (s["parameters"]["signal"] == SIGNAL_MODEL and s["parameters"]["news_weight"] == 0 and probs)]
    per: dict[tuple[str, object], list[pd.DataFrame]] = {}
    for ticker in sorted(bars):
        for k in horizons:
            trades = ticker_trades(market, bars[ticker], k, context)
            if trades.empty:
                continue
            trades["ticker"], trades["horizon_days"] = ticker, k
            for spec in usable:
                if k in spec["horizons"]:
                    chosen = trades[signal_mask(trades, spec, probs.get((ticker, k)))]
                    for key in ((spec["id"], k), (spec["id"], "all")):
                        per.setdefault(key, []).append(chosen)
    rows = []
    for (sid, horizon), parts in sorted(per.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        frame = pd.concat(parts, ignore_index=True)
        spec = next(s for s in usable if s["id"] == sid)
        m = sum(1 for key in per if key[1] == horizon)
        rows.append({"scope": "strategy", "market": market, "view": "accuracy", "basis": "backtest",
                     "strategy_id": sid, "family": spec["family"], "horizon_days": horizon,
                     **summary(frame, f"backtest|{market}|{sid}|{horizon}", m)})
    return rows
