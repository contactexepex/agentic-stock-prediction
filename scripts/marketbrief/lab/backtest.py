"""F2.3 back-test of the strategies that need no news (always-up and momentum from bars; the model strategies without
news when B10's walk-forward probabilities per horizon are given, lab/backtest_probs.py), on adjusted daily bars:
data/'s stored bars, plus the long-history cache's earlier dates with --history (model/history_cache.py). Labelled
basis "backtest" and never pooled with forward results; written to the output folder, and to data/ only as the
append-only kind lab_backtests with `lab.py backtest --store` (lab/backtest_store.py).

Each as-of row t of a ticker (its own stored sessions): entry at the open of the next row (D), exit at the close of
the k-th row after D (N+k), the market's default amount, the quantity rule of F1.4, both cost views of
lab/costs.py (the engine's own cost code; US order fee at the EUR/USD close on or before each side, from the
stored or cached EURUSD bars; portfolio fee
over the calendar days held). Net profit and return are in the market view; `your_cost` repeats them. Limits: today's
watchlist (survivorship bias), split adjustment as of the fetch, no target or range (no stored ranges in the past)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.contracts.watchlist import DEFAULT_AMOUNT
from marketbrief.lab import costs as lab_costs
from marketbrief.lab.constants import (MIN_RANKED_TRADES, MONEY_DIGITS, PCT_DIGITS, PERCENT, PROB_DIGITS,
                                       SIGNAL_ALWAYS_UP, SIGNAL_MODEL, SIGNAL_MOMENTUM)
from marketbrief.lab.luck import luck_test


def trade_costs(market: str, rate: dict, values: tuple[np.ndarray, np.ndarray], shares: np.ndarray,
                extra: dict) -> tuple[np.ndarray, np.ndarray]:
    """(market-view, your-view) round-trip costs per trade, each from lab/costs.cost_views (the engine's own
    cost code). extra: eurusd = (entry rates, exit rates), holding_days per trade."""
    market_view, your_view = np.zeros(len(shares)), np.zeros(len(shares))
    for n in range(len(shares)):
        views = lab_costs.cost_views(market, rate, (float(values[0][n]), float(values[1][n])), float(shares[n]),
                                     {"eurusd": (extra["eurusd"][0][n], extra["eurusd"][1][n]),
                                      "holding_days": int(extra["holding_days"][n])})
        market_view[n], your_view[n] = views["market"]["total"], views["your"]["total"]
    return market_view, your_view


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
    entries, exits = dates[1:n + 1].to_numpy(), dates[1 + horizon:n + 1 + horizon].to_numpy()
    keep = shares > 0
    fx = (rate_series(context.get("eurusd"), pd.Series(entries)), rate_series(context.get("eurusd"), pd.Series(exits)))
    fx = tuple(np.where(np.isnan(side), None, side) for side in fx)
    days = (pd.DatetimeIndex(exits) - pd.DatetimeIndex(entries)).days.to_numpy()
    market_cost, your_cost = np.zeros(n), np.zeros(n)
    if keep.any():
        market_cost[keep], your_cost[keep] = trade_costs(
            market, context["rate"], (entry_value[keep], exit_value[keep]), shares[keep],
            {"eurusd": (fx[0][keep], fx[1][keep]), "holding_days": days[keep]})
    net, net_your = exit_value - entry_value - market_cost, exit_value - entry_value - your_cost
    previous = np.concatenate([[np.nan], closes[:-1]])
    out = pd.DataFrame({"as_of": dates[:n].to_numpy(), "entry_date": entries, "exit_date": exits, "shares": shares,
                        "net_pnl": net, "return_pct": net / amount * PERCENT, "net_pnl_your": net_your,
                        "return_pct_your": net_your / amount * PERCENT, "up_last": closes[:n] > previous[:n]})
    return out[keep]


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
            "your_cost": {"net_pnl": round(float(trades["net_pnl_your"].sum()), MONEY_DIGITS),
                          "mean_return_pct": round(float(trades["return_pct_your"].mean()), PCT_DIGITS)
                          if len(net) else None},
            "target_reached_rate": None, "median_reached_session": None, "avg_target_error_pct": None,
            "range_hit_rate": None, "luck_test": luck_test(returns.tolist(), key, m),
            "sample_badge": "too_few_to_rank" if len(net) < MIN_RANKED_TRADES else "ok",
            "first_entry": str(trades["entry_date"].min().date()) if len(net) else None,
            "last_exit": str(trades["exit_date"].max().date()) if len(net) else None}


def model_without_news(spec: dict) -> bool:
    """A model strategy the base walk-forward probabilities back-test alone: news weight 0 (no news archive), no
    cross-market variant and no regime filter (neither is in the back-test)."""
    params = spec["parameters"]
    return (params["signal"] == SIGNAL_MODEL and params["news_weight"] == 0 and not params.get("cross_market")
            and not params.get("regime_filter"))


def run_backtest(market: str, bars: dict[str, pd.DataFrame], specs: list[dict], horizons: tuple[int, ...],
                 context: dict) -> list[dict]:
    """Scoreboard rows (basis backtest, view accuracy) per strategy and horizon ("all" = pooled). context: rate,
    eurusd (Series by date or None), probs ({(ticker, k): Series of p by as-of date} or None)."""
    probs = context.get("probs") or {}
    usable = [s for s in specs if s["parameters"]["signal"] in (SIGNAL_ALWAYS_UP, SIGNAL_MOMENTUM)
              or (probs and model_without_news(s))]
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
