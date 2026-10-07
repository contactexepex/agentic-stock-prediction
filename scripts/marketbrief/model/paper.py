"""The paper strategy of the backtest and its baselines (library; research only, never a trade).

Every position follows the owner's convention: buy at the open of D, sell at the close of D+1 (1-day)
or D+4 (5-day), net of the round-trip cost of config/costs.yaml at the entry open. Per as-of date the
chosen stock-days are equally weighted; the statistics are the mean holding-period return per date
(dates with at least one position) and per position, in %, with a 95% moving-block bootstrap interval
over dates (metrics.block_bootstrap). Strategies:
- model long at threshold t: p >= t;
- always-up: every stock-day; momentum: 5-day return > 0; RSI mean reversion: RSI(14) < 30;
- benchmark_long_per_date: a new long position in the benchmark at every as-of date, its own open-to-close
  return over the same window less a full round trip each time (not a single buy-and-hold: the cost is
  charged per date, like every other strategy here);
- "sell if held" (reported apart, not a short sale): p <= 1 - t, the return a holder avoids by selling
  at the open and buying back at the close (-return, gross and net of a round trip).
Differences model minus baseline are taken per date on the dates the model holds positions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.model.metrics import block_bootstrap, r
from marketbrief.model.settings import round_trip_cost

RSI_OVERSOLD = 30.0
PERCENT = 100.0


def per_date(frame: pd.DataFrame, chosen: pd.Series, column: str) -> pd.Series:
    """The equal-weight mean of `column` over the chosen rows of each date."""
    return frame.loc[chosen, ["date", column]].groupby("date")[column].mean()


def summary(series: pd.Series, positions: int, settings: dict, block: int) -> dict:
    """Mean per date and its interval in %, dates and positions."""
    boot = settings["backtest"]
    low, high = block_bootstrap(series, block, boot["bootstrap_samples"], boot["bootstrap_seed"])
    scale = lambda x: None if x is None else r(x * PERCENT)  # noqa: E731
    return {"dates": int(series.notna().sum()), "positions": int(positions),
            "mean_pct": scale(series.mean()) if len(series) else None, "ci95_pct": [scale(low), scale(high)]}


def difference(model: pd.Series, baseline: pd.Series, settings: dict, block: int) -> dict:
    """Mean per-date difference model - baseline in % on the model's dates, with its interval."""
    joined = pd.concat([model.rename("m"), baseline.rename("b")], axis=1, join="inner").dropna()
    return summary(joined["m"] - joined["b"], len(joined), settings, block)


def prepare(frame: pd.DataFrame, market: str, costs: dict) -> pd.DataFrame:
    """Resolved rows with the cost at the entry open and the net return."""
    out = frame[frame["ret"].notna() & frame["entry_open"].notna()].copy()
    out["cost"] = round_trip_cost(market, costs, out["entry_open"].to_numpy())
    out["net"] = out["ret"] - out["cost"]
    out["avoided"] = -out["ret"]
    out["avoided_net"] = -out["ret"] - out["cost"]
    return out


def baseline_series(frame: pd.DataFrame, market: str, costs: dict) -> dict[str, tuple[pd.Series, int]]:
    """{name: (net per-date series, positions)} of the baselines."""
    picks = {"always_up": pd.Series(True, index=frame.index), "momentum_5d": frame["ret_5d"] > 0,
             "rsi_mean_reversion": frame["rsi_14"] < RSI_OVERSOLD}
    out = {name: (per_date(frame, chosen, "net"), int(chosen.sum())) for name, chosen in picks.items()}
    bench = frame.groupby("date")["bench_ret"].first().dropna() - round_trip_cost(market, costs)
    out["benchmark_long_per_date"] = (bench, len(bench))
    return out


def paper_results(frame: pd.DataFrame, market: str, costs: dict, settings: dict, block: int) -> dict:
    """Model long and sell-if-held per threshold, the baselines, and the model-minus-baseline differences."""
    rows = prepare(frame, market, costs)
    baselines = baseline_series(rows, market, costs)
    out = {"mean_cost_pct": r(rows["cost"].mean() * PERCENT) if len(rows) else None,
           "baselines": {name: summary(series, n, settings, block) for name, (series, n) in baselines.items()},
           "thresholds": {}}
    for threshold in settings["backtest"]["thresholds"]:
        longs = rows["prob"] >= threshold
        model = per_date(rows, longs, "net")
        sells = rows["prob"] <= 1 - threshold
        out["thresholds"][f"{threshold:.2f}"] = {
            "long": {**summary(model, int(longs.sum()), settings, block),
                     "gross_mean_pct": r(per_date(rows, longs, "ret").mean() * PERCENT) if longs.any() else None},
            "vs": {name: difference(model, series, settings, block) for name, (series, _) in baselines.items()},
            "sell_if_held": {"gross": summary(per_date(rows, sells, "avoided"), int(sells.sum()), settings, block),
                             "net_of_round_trip": summary(per_date(rows, sells, "avoided_net"), int(sells.sum()),
                                                          settings, block)}}
    return out


def nan_free(value):
    """JSON-safe: NaN -> None (recursively)."""
    if isinstance(value, dict):
        return {k: nan_free(v) for k, v in value.items()}
    if isinstance(value, list):
        return [nan_free(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value
