"""The Rule vs AI page (B13; docs/ws/b13.md): rm.compare, page_key `_`, served by
GET /api/v1/markets/{market}/compare. Payload RuleVsAi = design/mockups/06-rule-vs-ai/data.json per market (notes.md
there names every key and its selection rule): the shared blocks of rm_common, the head-to-head scoreboard rows, the
settled head-to-head trades with their your-cost settlement rows, the head-to-head picks, the AI reasons of kind
head_to_head, the end-of-day analyses and the weekly research reviews, each read as of the cut-off by its own
storage time and kept to the market's collected companies. The research reviews (the handover's rm.review) ride in
this one page, since a route reads one table.

Also the ctx-first reads Home needs (B11): `eod_analyses(ctx)` (newest first) and `head_to_head_trades(ctx)`."""

from __future__ import annotations

import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from marketbrief.constants.warehouse import MARKET_PAGE_KEY, STRATEGY_FIELDS
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import reads as lab_reads
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext, ContractCase, PageBuilder
from marketbrief.warehouse.rm_strategies import (
    ALL_HORIZONS,
    CELL_FIELDS,
    companies,
    market_mockup,
    pick,
    scoreboard_rows,
)

RM_COMPARE = "compare"
RM_REVIEW = "review"
DIMENSION_COMPANY = "company"
VIEW_HEAD_TO_HEAD = "head_to_head"
REASON_KIND_HEAD_TO_HEAD = "head_to_head"
RECORD_KIND_SETTLEMENT = "settlement"
SCOPES = ("strategy", "pick_rule", "strategy_regime")
SATURDAY = 5  # date.weekday(): the weekly research run (routine/WEEKLY_PROMPT.md, Saturday 10:00 local)
DAYS_PER_WEEK = 7
STRATEGY_PAGE_FIELDS = tuple(name for name in STRATEGY_FIELDS if name not in ("parameters", "live_from"))
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state", "amount", "amount_overridden", "currency")
TRADE_FIELDS = (
    "trade_id",
    "prediction_id",
    "strategy_id",
    "family",
    "view",
    "pick_rule",
    "ticker",
    "horizon_days",
    "made_at",
    "entry_date",
    "exit_date",
    "exit_date_actual",
    "status",
    "amount",
    "currency",
    "entry_price",
    "exit_price",
    "net_pnl",
    "return_pct",
    "prob_up",
    "target_price",
    "target_error_pct",
    "target_reached",
    "range_hit",
    "move_pct",
    "market_pct",
    "sector_pct",
    "news_pct",
    "company_pct",
    "reason_code",
    "reason_codes",
    "regime",
    "settled_at",
)
CANDIDATE_FIELDS = (
    "horizon_days",
    "prediction_id",
    "prob_up",
    "move_pct",
    "loss_pct",
    "costs_pct",
    "expected_gain_pct",
    "gain_per_session_pct",
    "expected_move_pct",
    "your_cost_pct",
    "expected_gain_your_pct",
    "cost_viable",
    "eligible",
)
PICK_FIELDS = (
    "id",
    "market",
    "ticker",
    "made_at",
    "as_of_date",
    "session_date",
    "family",
    "pick_rule",
    "status",
    "strategy_id",
    "strongest_basis",
    "horizon_days",
    "prediction_id",
    "prob_up",
    "move_pct",
    "loss_pct",
    "costs_pct",
    "expected_gain_pct",
    "amount",
    "currency",
)
YOUR_COST_FIELDS = (
    "trade_id",
    "record_id",
    "net_pnl_market",
    "return_pct_market",
    "net_pnl_your",
    "return_pct_your",
    "market_costs",
    "your_costs",
    "your_cost_pct",
    "computed_at",
)
REASON_FIELDS = (
    "id",
    "trade_id",
    "market",
    "ticker",
    "strategy_id",
    "session_date",
    "kind",
    "rank",
    "text",
    "cited_ids",
    "reason_codes",
    "created_at",
)
EOD_FIELDS = (
    "id",
    "market",
    "session_date",
    "settled_trades",
    "results",
    "summary",
    "cited_ids",
    "reason_ids",
    "created_at",
)
EOD_FAMILIES = ("rule", "baseline", "ai")
EOD_FAMILY_FIELDS = ("trades", "wins", "net_pnl")
EOD_PICK_RULES = ("best_expected_gain", "highest_probability")
EOD_PICK_FIELDS = ("trades", "net_pnl")
REVIEW_FIELDS = (
    "id",
    "market",
    "iso_week",
    "period_start",
    "period_end",
    "leaders",
    "findings",
    "proposals",
    "report_path",
    "written_at",
)
LEADER_FIELDS = ("scope", "strategy_id", "net_pnl", "trades")
FINDING_FIELDS = ("text", "cited_ids")
PROPOSAL_FIELDS = ("proposal_id", "kind", "file", "diff", "rationale", "cited_ids", "status")
NEWS_IMPACT_FIELDS = (
    "id",
    "market",
    "iso_week",
    "as_of",
    "event_type",
    "status",
    "materiality",
    "horizon_days",
    "n_events",
    "mean_abnormal_pct",
    "ci_low_pct",
    "ci_high_pct",
    "mean_benchmark_pct",
    "mean_sector_pct",
    "enough",
    "news_ids",
    "computed_at",
)
TIME_FIELDS = ("made_at", "settled_at", "computed_at", "created_at", "written_at", "as_of")


def stored(ctx: BuildContext, kind: str, time_column: str) -> list[dict]:
    """Every row of a kind stored by the cut-off (its own storage time), JSON columns parsed, times ISO UTC with a
    Z, in time then id order."""
    json_columns = [name for name, kind_type in SCHEMAS[kind][1].items() if kind_type == "JSON"]
    rows = lab_reads.stored(ctx.con, kind, time_column, ctx.cutoff_time)
    for row in rows:
        for name in json_columns:
            if isinstance(row.get(name), str):
                row[name] = json.loads(row[name])
        for name in TIME_FIELDS:
            if row.get(name) is not None:
                row[name] = rm_common.iso_z(row[name])
    return rows


def newest_first(rows: list[dict], time_column: str) -> list[dict]:
    """Rows by time descending, then id."""
    return sorted(sorted(rows, key=lambda row: row["id"]), key=lambda row: row[time_column], reverse=True)


def head_to_head_trades(ctx: BuildContext) -> list[dict]:
    """The newest settlement of every head-to-head trade stored by the cut-off (collected companies), in its page
    fields, by entry date, company, pick rule, strategy and trade id."""

    def compute() -> list[dict]:
        trades = [pick(t, TRADE_FIELDS) for t in rm_common.settled_trades(ctx) if t["view"] == VIEW_HEAD_TO_HEAD]
        for trade in trades:
            for name in TIME_FIELDS:
                if trade.get(name) is not None:
                    trade[name] = rm_common.iso_z(trade[name])
        order = ("entry_date", "ticker", "pick_rule", "strategy_id", "trade_id")
        return sorted(trades, key=lambda t: tuple(t[name] or "" for name in order))

    return ctx.shared("b13_head_to_head_trades", compute)


def your_costs(ctx: BuildContext) -> list[dict]:
    """The cost_views rows of the head-to-head trades' newest settlements stored by the cut-off (the your-cost
    figures of the page's trades), in time order."""

    def compute() -> list[dict]:
        settlement_ids = {t["id"] for t in rm_common.settled_trades(ctx) if t["view"] == VIEW_HEAD_TO_HEAD}
        return [
            pick(row, YOUR_COST_FIELDS)
            for row in stored(ctx, "cost_views", "computed_at")
            if row["record_kind"] == RECORD_KIND_SETTLEMENT and row["record_id"] in settlement_ids
        ]

    return ctx.shared("b13_your_costs", compute)


def picks(ctx: BuildContext) -> list[dict]:
    """Every head-to-head pick made by the cut-off (collected companies; first row of each id), in its page fields,
    by session date, company, family and pick rule (Home filters today's session from it)."""

    def compute() -> list[dict]:
        rows = [row for row in lab_reads.picks(ctx.con, ctx.cutoff_time) if row["ticker"] in ctx.collected]
        out = []
        for row in rows:
            item = pick(row, PICK_FIELDS)
            item["made_at"] = rm_common.iso_z(item["made_at"])
            item["candidates"] = [pick(candidate, CANDIDATE_FIELDS) for candidate in row.get("candidates") or []]
            out.append(item)
        order = ("session_date", "ticker", "family", "pick_rule", "id")
        return sorted(out, key=lambda p: tuple(p[name] or "" for name in order))

    return ctx.shared("b13_picks", compute)


def reasons(ctx: BuildContext) -> list[dict]:
    """The AI reasons of kind head_to_head written by the cut-off (collected companies), newest first."""

    def compute() -> list[dict]:
        rows = [
            pick(row, REASON_FIELDS)
            for row in stored(ctx, "trade_reasons_ai", "created_at")
            if row["kind"] == REASON_KIND_HEAD_TO_HEAD and row["ticker"] in ctx.collected
        ]
        return newest_first(rows, "created_at")

    return ctx.shared("b13_reasons", compute)


def eod_record(row: dict) -> dict:
    """One end-of-day analysis in its page fields."""
    results = row.get("results") or {}
    return {
        **pick(row, EOD_FIELDS),
        "results": {
            **{name: pick(results.get(name) or {}, EOD_FAMILY_FIELDS) for name in EOD_FAMILIES},
            **{name: pick(results.get(name) or {}, EOD_PICK_FIELDS) for name in EOD_PICK_RULES},
        },
    }


def eod_analyses(ctx: BuildContext) -> list[dict]:
    """The end-of-day analyses written by the cut-off, newest first (Home shows the newest)."""

    def compute() -> list[dict]:
        return newest_first([eod_record(row) for row in stored(ctx, "eod_analyses", "created_at")], "created_at")

    return ctx.shared("b13_eod_analyses", compute)


def review_record(row: dict) -> dict:
    """One research review in its page fields."""
    return {
        **pick(row, REVIEW_FIELDS),
        "leaders": [pick(item, LEADER_FIELDS) for item in row.get("leaders") or []],
        "findings": [pick(item, FINDING_FIELDS) for item in row.get("findings") or []],
        "proposals": [pick(item, PROPOSAL_FIELDS) for item in row.get("proposals") or []],
    }


def reviews(ctx: BuildContext) -> list[dict]:
    """The research reviews written by the cut-off, newest first (rm.compare and rm.review show the same list)."""

    def compute() -> list[dict]:
        rows = [review_record(row) for row in stored(ctx, "research_reviews", "written_at")]
        return newest_first(rows, "written_at")

    return ctx.shared("b13_reviews", compute)


def review_due(ctx: BuildContext, written: list[dict]) -> dict:
    """The next weekly research review (F6.2): the first Saturday (market-local date) on or after the cut-off whose
    ISO week has no review stored yet, and that week."""
    day = ctx.cutoff_time.astimezone(ZoneInfo(ctx.cfg["timezone"])).date()
    day += timedelta(days=(SATURDAY - day.weekday()) % DAYS_PER_WEEK)
    done = {row["iso_week"] for row in written}
    while True:
        year, week, _ = day.isocalendar()
        iso_week = f"{year}-W{week:02d}"
        if iso_week not in done:
            return {"date": day.isoformat(), "iso_week": iso_week}
        day += timedelta(days=DAYS_PER_WEEK)


def head_to_head_rows(ctx: BuildContext) -> list[dict]:
    """The head-to-head scoreboard rows of the page's scopes (forward basis), without the go-live block (the page
    lists none; the go-live bar is the reference strategy's accuracy row)."""
    return [
        {key: value for key, value in row.items() if key != "go_live"}
        for row in scoreboard_rows(ctx)
        if row["view"] == VIEW_HEAD_TO_HEAD and row["scope"] in SCOPES
    ]


def compare_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.compare: the market's Rule vs AI page `_` and one page per collected company."""
    status = rm_common.status_block(ctx)
    trades = head_to_head_trades(ctx)
    written = reviews(ctx)
    return {
        MARKET_PAGE_KEY: {
            **rm_common.header(ctx),
            "status": status,
            **rm_common.horizons(ctx),
            "default_horizon": ALL_HORIZONS,
            "go_live": rm_common.go_live(ctx),
            "strategies": rm_common.strategies(ctx, STRATEGY_PAGE_FIELDS),
            "companies": companies(ctx, COMPANY_FIELDS),
            "session_date": status["session"]["session_date"],
            "rows": head_to_head_rows(ctx),
            "trades": trades,
            "your_costs": your_costs(ctx),
            "picks": picks(ctx),
            "reasons": reasons(ctx),
            "eod": eod_analyses(ctx),
            "reviews": written,
            "review_due": review_due(ctx, written),
        },
        **{ticker: company_page(ctx, ticker) for ticker in sorted(ctx.collected)},
    }


def company_page(ctx: BuildContext, ticker: str) -> dict:
    """One company's head-to-head cut (B5's compare_rule_vs_ai with a ticker): its head-to-head heatmap cells of
    dimension company, its trades, their your-cost rows, its picks and its AI reasons; empty lists before any."""
    trades = [trade for trade in head_to_head_trades(ctx) if trade["ticker"] == ticker]
    trade_ids = {trade["trade_id"] for trade in trades}
    cells = rm_common.lab_summary(ctx)["heatmaps"]["cells"]
    return {
        "market": ctx.market,
        "as_of": ctx.as_of,
        "ticker": ticker,
        "cells": [
            pick(cell, CELL_FIELDS)
            for cell in cells
            if cell["view"] == VIEW_HEAD_TO_HEAD and cell["dimension"] == DIMENSION_COMPANY and cell["column"] == ticker
        ],
        "trades": trades,
        "your_costs": [row for row in your_costs(ctx) if row["trade_id"] in trade_ids],
        "picks": [item for item in picks(ctx) if item["ticker"] == ticker],
        "reasons": [item for item in reasons(ctx) if item["ticker"] == ticker],
    }


def news_impact(ctx: BuildContext) -> list[dict]:
    """The news-impact rows (F3) of the newest ISO week computed by the cut-off, by id."""
    rows = stored(ctx, "news_impact", "computed_at")
    if not rows:
        return []
    newest = max(row["iso_week"] for row in rows)
    return sorted((pick(row, NEWS_IMPACT_FIELDS) for row in rows if row["iso_week"] == newest), key=lambda r: r["id"])


def review_pages(ctx: BuildContext) -> dict[str, dict]:
    """rm.review: the market's research reviews, the next one due and the newest news-impact week (B5's read tools
    compare_rule_vs_ai and get_news; GET /api/v1/markets/{market}/review)."""
    written = reviews(ctx)
    return {
        MARKET_PAGE_KEY: {
            **rm_common.header(ctx),
            "reviews": written,
            "review_due": review_due(ctx, written),
            "news_impact": news_impact(ctx),
        }
    }


BUILDERS = (
    PageBuilder(RM_COMPARE, "RuleVsAiTable", compare_pages, owner="B13"),
    PageBuilder(RM_REVIEW, "ResearchReviewPage", review_pages, owner="B13"),
)
CONTRACT_CASES = (
    ContractCase(
        path="/api/v1/markets/{market}/compare",
        table=RM_COMPARE,
        mockup="design/mockups/06-rule-vs-ai/data.json",
        mockup_payload=market_mockup,
        map_paths=("$.strategies",),
        page_keys=lambda key: key == MARKET_PAGE_KEY,
    ),
)
