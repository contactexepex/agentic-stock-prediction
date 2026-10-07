"""F2.8 heatmap and chart data (decision 42) from settled trades (newest settlement of each, status settled):
cells of win rate and net profit after costs by strategy x horizon, strategy x company and strategy x reason code,
each per ISO week of the exit (and "all"), per market, view and basis; plus cumulative net profit lines per
strategy (accuracy view) and per family x pick rule (head-to-head view) in exit-date order."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from marketbrief.lab.constants import MONEY_DIGITS, PROB_DIGITS, STATUS_SETTLED, VIEW_ACCURACY
from marketbrief.lab.scoreboard import latest_settlements

ALL = "all"
DIMENSIONS = {"horizon": "horizon_days", "company": "ticker", "reason_code": "reason_code"}


def iso_week(day: str) -> str:
    """YYYY-Www of a date."""
    year, week, _ = date.fromisoformat(str(day)[:10]).isocalendar()
    return f"{year}-W{week:02d}"


def cells(trades: list[dict], basis: str) -> list[dict]:
    """Heatmap cells: {market, view, basis, dimension, strategy_id, column, week, trades, wins, win_rate, net_pnl}."""
    groups: dict[tuple, list[float]] = defaultdict(list)
    for trade in trades:
        for dimension, column in DIMENSIONS.items():
            for week in (ALL, iso_week(trade["exit_date_actual"])):
                key = (trade["market"], trade["view"], dimension, trade["strategy_id"], str(trade[column]), week)
                groups[key].append(trade["net_pnl"])
    return [{"market": k[0], "view": k[1], "basis": basis, "dimension": k[2], "strategy_id": k[3], "column": k[4],
             "week": k[5], "trades": len(v), "wins": sum(x > 0 for x in v),
             "win_rate": round(sum(x > 0 for x in v) / len(v), PROB_DIGITS), "net_pnl": round(sum(v), MONEY_DIGITS)}
            for k, v in sorted(groups.items())]


def cumulative(trades: list[dict], basis: str) -> list[dict]:
    """Cumulative net profit per series and exit date: series = strategy_id (accuracy) or family:pick_rule."""
    daily: dict[tuple, float] = defaultdict(float)
    for trade in trades:
        series = trade["strategy_id"] if trade["view"] == VIEW_ACCURACY else f"{trade['family']}:{trade['pick_rule']}"
        daily[(trade["market"], trade["view"], series, str(trade["exit_date_actual"]))] += trade["net_pnl"]
    out, running = [], defaultdict(float)
    for (market, view, series, day), value in sorted(daily.items()):
        running[(market, view, series)] += value
        out.append({"market": market, "view": view, "basis": basis, "series": series, "date": day,
                    "net_pnl": round(value, MONEY_DIGITS),
                    "cumulative_net_pnl": round(running[(market, view, series)], MONEY_DIGITS)})
    return out


def heatmap_data(settled: list[dict], basis: str = "forward") -> dict:
    """{cells, lines} of one basis."""
    trades = [t for t in latest_settlements(settled) if t["status"] == STATUS_SETTLED]
    return {"cells": cells(trades, basis), "lines": cumulative(trades, basis)}
