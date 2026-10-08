"""The record fields and shaping of the Rule vs AI page and rm.review (B13; rm_compare.py): the catalogue fields each
page record keeps (design/mockups/06-rule-vs-ai/notes.md), and the as-of read of a lab kind with its JSON columns
parsed and times as ISO UTC with a Z."""

from __future__ import annotations

import json

from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import reads as lab_reads
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext
from marketbrief.warehouse.rm_strategies import pick

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


def review_record(row: dict) -> dict:
    """One research review in its page fields."""
    return {
        **pick(row, REVIEW_FIELDS),
        "leaders": [pick(item, LEADER_FIELDS) for item in row.get("leaders") or []],
        "findings": [pick(item, FINDING_FIELDS) for item in row.get("findings") or []],
        "proposals": [pick(item, PROPOSAL_FIELDS) for item in row.get("proposals") or []],
    }
