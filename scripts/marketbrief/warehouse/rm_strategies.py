"""The Strategy lab page (B13; docs/ws/b13.md): rm.strategies, page_key `_`, served by
GET /api/v1/markets/{market}/strategies. Payload StrategyLab = design/mockups/05-strategy-lab/data.json per market
(notes.md there names every key and its selection rule): the shared blocks of rm_common, every scoreboard row of the
market (forward basis from B2's scoreboard over the settled trades stored by the cut-off, backtest basis from B2's
back-test on the stored bars), the heatmap cells and cumulative lines (forward basis) and the back-test run's facts.
The two bases are never pooled: every row carries its `basis` and the page filters on it.

Also the scoreboard-row shaping the other strategy pages reuse (Rule vs AI, Paper portfolios): `scoreboard_rows(ctx)`
gives the forward rows in the catalogue's fields, computed once per build."""

from __future__ import annotations

from marketbrief.constants.warehouse import MARKET_PAGE_KEY, REFERENCE_STRATEGY
from marketbrief.lab import reports as lab_reports
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder

RM_STRATEGIES = "strategies"
ALL_HORIZONS = "all"
BASIS_BACKTEST = "backtest"
SCOPE_STRATEGY = "strategy"
# Scoreboard row fields (docs/DATA_CATALOGUE.md "Scoreboard row"; 05-strategy-lab notes.md `rows`)
ROW_FIELDS = (
    "scope",
    "market",
    "view",
    "basis",
    "strategy_id",
    "family",
    "pick_rule",
    "ticker",
    "regime",
    "horizon_days",
    "trades",
    "net_pnl",
    "mean_return_pct",
    "win_rate",
    "target_reached_rate",
    "median_reached_session",
    "avg_target_error_pct",
    "range_hit_rate",
    "worst_losing_streak",
    "max_drawdown",
    "sample_badge",
    "first_entry",
    "last_exit",
)
LUCK_FIELDS = (
    "method",
    "n",
    "m",
    "low_pct",
    "high_pct",
    "excludes_zero",
    "corrected_low_pct",
    "corrected_high_pct",
    "corrected",
)
YOUR_COST_FIELDS = ("net_pnl", "mean_return_pct", "win_rate", "worst_losing_streak", "max_drawdown")
BACKTEST_YOUR_COST_FIELDS = ("net_pnl", "mean_return_pct")
GO_LIVE_ROW_FIELDS = (
    "proven",
    "months_forward",
    "trades_needed",
    "beats_best_baseline",
    "best_baseline_net_pnl",
    "drawdown_limit",
    "drawdown_within_limit",
    "holds_in_calm_and_volatile",
    "cost_view",
)
BACKTEST_RUN_FIELDS = ("history", "first_date", "last_date", "eurusd", "note")
CELL_FIELDS = ("market", "view", "basis", "strategy_id", "dimension", "column", "week", "trades", "wins", "win_rate",
               "net_pnl")
LINE_FIELDS = ("market", "view", "basis", "series", "date", "net_pnl", "cumulative_net_pnl")
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state")
# B2's back-test refuses US without stored EUR/USD closes (lab/reports.MSG_BACKTEST_NO_EURUSD); its message is the note


def pick(record: dict, fields: tuple[str, ...]) -> dict:
    """The named fields of a record (a missing one is null)."""
    return {name: record.get(name) for name in fields}


def luck(test: dict | None) -> dict | None:
    """A luck test in its catalogue fields."""
    return None if test is None else pick(test, LUCK_FIELDS)


def row_order(row: dict) -> tuple:
    """A total order of scoreboard rows: basis, view, scope, strategy, pick rule, company, regime, horizon (all
    first, then 1..5)."""
    horizon = row["horizon_days"]
    return (
        row["basis"],
        row["view"],
        row["scope"],
        row["strategy_id"] or "",
        row["pick_rule"] or "",
        row["ticker"] or "",
        row["regime"] or "",
        (0, 0) if str(horizon) == ALL_HORIZONS else (1, int(horizon)),
    )


def forward_row(row: dict, as_of: str | None) -> dict:
    """One forward scoreboard row in the catalogue's fields. B2's row carries the build's cut-off as `as_of`; the
    page shows the data's as-of date instead (no build time in a payload)."""
    your = row.get("your_cost")
    out = {
        **pick(row, ROW_FIELDS),
        "as_of": as_of,
        "luck_test": luck(row.get("luck_test")),
        "your_cost": None if your is None else {**pick(your, YOUR_COST_FIELDS), "luck_test": luck(your.get("luck_test"))},
    }
    if row["scope"] == SCOPE_STRATEGY and row.get("go_live") is not None:
        out["go_live"] = pick(row["go_live"], GO_LIVE_ROW_FIELDS)
    return out


def scoreboard_rows(ctx: BuildContext) -> list[dict]:
    """Every forward scoreboard row of the market (both views, every scope), in the catalogue's fields, ordered."""

    def compute() -> list[dict]:
        rows = [forward_row(row, ctx.as_of) for row in rm_common.lab_summary(ctx)["scoreboard"]]
        return sorted(rows, key=row_order)

    return ctx.shared("b13_scoreboard_rows", compute)


def backtest_row(row: dict) -> dict:
    """One back-test row (W1's scoreboard_backtest_row.json: no as_of, go_live, pick rule, company or regime)."""
    your = row.get("your_cost")
    return {
        **pick(row, ROW_FIELDS),
        "pick_rule": None,
        "ticker": None,
        "regime": None,
        "luck_test": luck(row.get("luck_test")),
        "your_cost": None if your is None else pick(your, BACKTEST_YOUR_COST_FIELDS),
    }


def backtest(ctx: BuildContext) -> dict:
    """{run, rows} of B2's back-test (lab/reports.run_backtest, no history cache) on the bars stored by the cut-off;
    a refused run (US without stored EUR/USD closes) has no rows and its message as the run's note."""

    def compute() -> dict:
        result = lab_reports.run_backtest(ctx.con, ctx.cfg, ctx.cutoff_time, history=False)
        if result.get("ok") is False:
            return {
                "run": {"history": False, "first_date": None, "last_date": None, "eurusd": None,
                        "note": result["message"]},
                "rows": [],
            }
        return {
            "run": pick(result, BACKTEST_RUN_FIELDS),
            "rows": sorted((backtest_row(row) for row in result["rows"]), key=row_order),
        }

    return ctx.shared("b13_backtest", compute)


def companies(ctx: BuildContext, fields: tuple[str, ...] = COMPANY_FIELDS) -> list[dict]:
    """The collected companies (B1's watchlist as of the cut-off) in `fields`, by ticker."""
    return [pick(company, fields) for company in sorted(ctx.companies, key=lambda c: c["ticker"])]


def heatmaps(ctx: BuildContext) -> dict:
    """{cells, lines} of the forward basis (B2's heatmap data), in the catalogue's fields and order."""
    data = rm_common.lab_summary(ctx)["heatmaps"]
    return {
        "cells": [pick(cell, CELL_FIELDS) for cell in data["cells"]],
        "lines": [pick(line, LINE_FIELDS) for line in data["lines"]],
    }


def strategy_lab_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.strategies: the market's one Strategy lab page."""
    tested = backtest(ctx)
    rows = scoreboard_rows(ctx) + tested["rows"]
    return {
        MARKET_PAGE_KEY: {
            **rm_common.header(ctx),
            "status": rm_common.status_block(ctx),
            **rm_common.horizons(ctx),
            "default_horizon": ALL_HORIZONS,
            "reference_strategy": REFERENCE_STRATEGY,
            "go_live": rm_common.go_live(ctx),
            "strategies": rm_common.strategies(ctx),
            "companies": companies(ctx),
            "rows": rows,
            **heatmaps(ctx),
            "bases": sorted({row["basis"] for row in rows}),
            "backtest_run": tested["run"],
        }
    }


def market_mockup(mockup: dict, market: str, _page_key: str) -> dict:
    """The mockup's payload of a market."""
    return mockup["markets"][market]


BUILDERS = (PageBuilder(RM_STRATEGIES, "StrategyLab", strategy_lab_pages, owner="B13"),)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/strategies",
        table=RM_STRATEGIES,
        mockup="design/mockups/05-strategy-lab/data.json",
        mockup_payload=market_mockup,
        map_paths=("$.strategies",),
    ),
)
