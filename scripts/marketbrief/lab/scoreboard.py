"""F7 scoreboard rows from settled trades (status settled; the newest settlement of each trade): per market x view
x basis and, as `scope`:
  strategy          per strategy, all horizons pooled ("all") and each horizon;
  strategy_company  per strategy and company, all horizons and each horizon (the stock strategy page);
  pick_rule         head-to-head per family and pick rule, all horizons and each horizon (head-to-head portfolios);
  strategy_regime   per strategy and the regime at prediction time, all horizons (F2.6: the effect of regimes is
                    measured, not assumed).
Each row: trades, net_pnl (headline), mean_return_pct, win_rate, target_reached_rate and median_reached_session
(F1.9, over trades with a target), avg_target_error_pct, range_hit_rate, worst_losing_streak, max_drawdown, the
luck test (lab/luck.py; m = the rows compared in the same scope, market, view, basis, company, regime and
horizon), sample_badge and, for strategy rows, the go-live bar (F7.2, the spec's proposals until the owner
sets them)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

from marketbrief.contracts.watchlist import DEFAULT_AMOUNT
from marketbrief.lab.constants import (DAYS_PER_MONTH, DRAWDOWN_LIMIT_AMOUNTS, FAMILY_BASELINE, FILTERED_REGIMES,
                                       GO_LIVE_MONTHS, GO_LIVE_TRADES, MIN_RANKED_TRADES, MONEY_DIGITS, PCT_DIGITS,
                                       PROB_DIGITS, STATUS_SETTLED, VIEW_ACCURACY)
from marketbrief.lab.luck import luck_test

ALL = "all"
KEY_NAMES = ("scope", "market", "view", "basis", "strategy_id", "family", "pick_rule", "ticker", "regime",
             "horizon_days")


def latest_settlements(rows: list[dict]) -> list[dict]:
    """The newest row of each trade_id (a re-settlement supersedes the older row)."""
    newest: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: (str(r["settled_at"]), r["id"])):
        newest[row["trade_id"]] = row
    return [newest[key] for key in sorted(newest)]


def sequence_stats(trades: list[dict]) -> tuple[int, float]:
    """(worst losing streak, max drawdown of cumulative net profit) in exit order."""
    streak = worst = 0
    total = peak = drawdown = 0.0
    for trade in trades:
        streak = streak + 1 if trade["net_pnl"] < 0 else 0
        worst = max(worst, streak)
        total += trade["net_pnl"]
        peak = max(peak, total)
        drawdown = min(drawdown, total - peak)
    return worst, drawdown


def mean_or_none(values: list) -> float | None:
    """The mean of the non-null values, or None."""
    values = [float(v) for v in values if v is not None]
    return statistics.fmean(values) if values else None


def metrics(trades: list[dict]) -> dict:
    """The F7.1 numbers of one slice (trades in exit order)."""
    trades = sorted(trades, key=lambda t: (str(t["exit_date_actual"]), t["trade_id"]))
    with_target = [t for t in trades if t.get("target_reached") is not None]
    reached = [t["target_reached_session"] for t in with_target if t["target_reached"]]
    ranged = [t for t in trades if t.get("range_hit") is not None]
    worst, drawdown = sequence_stats(trades)
    rate = mean_or_none([t["target_error_pct"] for t in trades])
    return {"trades": len(trades), "net_pnl": round(sum(t["net_pnl"] for t in trades), MONEY_DIGITS),
            "mean_return_pct": round(statistics.fmean(t["return_pct"] for t in trades), PCT_DIGITS),
            "win_rate": round(sum(t["net_pnl"] > 0 for t in trades) / len(trades), PROB_DIGITS),
            "target_reached_rate": round(len(reached) / len(with_target), PROB_DIGITS) if with_target else None,
            "median_reached_session": statistics.median(reached) if reached else None,
            "avg_target_error_pct": None if rate is None else round(rate, PCT_DIGITS),
            "range_hit_rate": round(sum(bool(t["range_hit"]) for t in ranged) / len(ranged), PROB_DIGITS)
            if ranged else None,
            "worst_losing_streak": worst, "max_drawdown": round(drawdown, MONEY_DIGITS),
            "sample_badge": "too_few_to_rank" if len(trades) < MIN_RANKED_TRADES else "ok",
            "first_entry": min(str(t["entry_date"]) for t in trades),
            "last_exit": max(str(t["exit_date_actual"]) for t in trades)}


def slice_keys(trade: dict, basis: str) -> list[tuple]:
    """Every slice key (KEY_NAMES order) a trade belongs to."""
    common = (trade["market"], trade["view"], basis)
    sid, fam, horizon = trade["strategy_id"], trade["family"], trade["horizon_days"]
    keys = []
    for h in (ALL, horizon):
        keys.append(("strategy", *common, sid, fam, None, None, None, h))
        if trade["view"] == VIEW_ACCURACY:
            keys.append(("strategy_company", *common, sid, fam, None, trade["ticker"], None, h))
        else:
            keys.append(("pick_rule", *common, None, fam, trade["pick_rule"], None, None, h))
    keys.append(("strategy_regime", *common, sid, fam, None, None, trade.get("regime"), ALL))
    return keys


def regime_holds(trades: list[dict]) -> bool | None:
    """True when net profit is positive both in calm and in volatile (UNSTABLE / EVENT_HEAVY) regimes; None while
    one of them has no trade."""
    calm = [t["net_pnl"] for t in trades if t.get("regime") not in FILTERED_REGIMES]
    rough = [t["net_pnl"] for t in trades if t.get("regime") in FILTERED_REGIMES]
    if not calm or not rough:
        return None
    return sum(calm) > 0 and sum(rough) > 0


def go_live(row: dict, trades: list[dict], best_baseline: float | None) -> dict:
    """F7.2 position against the go-live bar (accuracy view, forward basis)."""
    months = (date.fromisoformat(row["last_exit"]) - date.fromisoformat(row["first_entry"])).days / DAYS_PER_MONTH
    limit = DRAWDOWN_LIMIT_AMOUNTS * DEFAULT_AMOUNT[row["market"]]
    beats = None if best_baseline is None else bool(row["net_pnl"] > best_baseline and row["luck_test"]["corrected"])
    holds = regime_holds(trades)
    drawdown_ok = -row["max_drawdown"] <= limit
    proven = bool(row["view"] == VIEW_ACCURACY and row["basis"] == "forward" and months >= GO_LIVE_MONTHS
                  and row["trades"] >= GO_LIVE_TRADES and beats and drawdown_ok and holds)
    return {"proven": proven, "months_forward": round(months, 2), "trades_needed": max(GO_LIVE_TRADES - row["trades"],
                                                                                         0),
            "beats_best_baseline": beats, "best_baseline_net_pnl": best_baseline, "drawdown_limit": limit,
            "drawdown_within_limit": drawdown_ok, "holds_in_calm_and_volatile": holds}


def peer_key(key: tuple) -> tuple:
    """The rows compared with one another (the luck test's m): same scope, market, view, basis, company, regime
    and horizon; they differ in strategy (or family and pick rule)."""
    return key[0], key[1], key[2], key[3], key[7], key[8], key[9]


def scoreboard(settled: list[dict], basis: str = "forward", as_of: str | None = None) -> list[dict]:
    """Every scoreboard row of the settled trades (one basis: forward or backtest, never pooled)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for trade in latest_settlements(settled):
        if trade["status"] == STATUS_SETTLED:
            for key in slice_keys(trade, basis):
                groups[key].append(trade)
    peers: dict[tuple, int] = defaultdict(int)
    for key in groups:
        peers[peer_key(key)] += 1
    rows = {}
    for key, trades in sorted(groups.items(), key=lambda kv: str(kv[0])):
        row = dict(zip(KEY_NAMES, key))
        row.update(metrics(trades))
        m = peers[peer_key(key)]
        row["luck_test"] = luck_test([t["return_pct"] for t in trades], "|".join(map(str, key)), m)
        row["as_of"] = as_of
        rows[key] = (row, trades)
    out = []
    for key, (row, trades) in rows.items():
        if row["scope"] == "strategy":
            baselines = [r["net_pnl"] for k, (r, _) in rows.items() if k[0] == "strategy" and k[1:4] == key[1:4]
                         and k[9] == key[9] and r["family"] == FAMILY_BASELINE
                         and r["strategy_id"] != row["strategy_id"]]
            row["go_live"] = go_live(row, trades, max(baselines) if baselines else None)
        out.append(row)
    return out
