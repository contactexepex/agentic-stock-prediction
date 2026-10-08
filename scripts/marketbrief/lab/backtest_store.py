"""`lab.py backtest --store`: the F2.3 back-test result (lab/reports.run_backtest) as `lab_backtests` rows
(core/schema_b2.py), appended once per id (run.append_new: a rerun of the same run_id stores nothing new). The rows
go to data/ through the append-only day file of computed_at (CLAUDE.md data rules); nothing is overwritten."""
from __future__ import annotations

from datetime import datetime

from marketbrief.constants.kinds import KIND_LAB_BACKTESTS
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import reads
from marketbrief.lab.run import append_new

BACKTEST_VERSION = "lab-bt-v1"
RUN_STORED, RUN_HISTORY = "stored", "history"
# lab/backtest.summary key -> lab_backtests column (the your-cost view is nested under "your_cost")
SAME_NAME = ("strategy_id", "family", "trades", "net_pnl", "mean_return_pct", "win_rate", "worst_losing_streak",
             "max_drawdown", "luck_test", "sample_badge", "first_entry", "last_exit")


def run_id(market: str, as_of_date: str, history: bool) -> str:
    """<market>-<as_of_date>-<stored|history>."""
    return f"{market}-{as_of_date}-{RUN_HISTORY if history else RUN_STORED}"


def row_id(run: str, strategy_id: str, horizon) -> str:
    """bt:<run_id>:<strategy_id>:<horizon> (horizon "1".."5" or "all")."""
    return f"bt:{run}:{strategy_id}:{horizon}"


def backtest_rows(result: dict, now: datetime) -> list[dict]:
    """One lab_backtests row per back-test row of `result` (reports.run_backtest), with the run's fields."""
    run = run_id(result["market"], result["as_of_date"], result["history"])
    head = {"run_id": run, "market": result["market"], "computed_at": now.isoformat(),
            "as_of_date": result["as_of_date"], "history": bool(result["history"]), "splice": result["splice"],
            "eurusd_source": result["eurusd"], "probs_source": result["probs_source"], "note": result["note"],
            "data_first_date": result["first_date"], "data_last_date": result["last_date"],
            "method_version": BACKTEST_VERSION}
    out = []
    for row in result["rows"]:
        horizon = str(row["horizon_days"])
        rec = dict.fromkeys(SCHEMAS[KIND_LAB_BACKTESTS][1])
        rec.update(head, id=row_id(run, row["strategy_id"], horizon), horizon=horizon,
                   **{key: row[key] for key in SAME_NAME},
                   your_net_pnl=row["your_cost"]["net_pnl"], your_mean_return_pct=row["your_cost"]["mean_return_pct"])
        out.append(rec)
    return out


def store_backtest(con, result: dict, now: datetime) -> dict:
    """Append the rows whose id is not stored by `now`; {rows, written}."""
    rows = backtest_rows(result, now)
    known = {r["id"] for r in reads.stored(con, KIND_LAB_BACKTESTS, "computed_at", now)}
    return {"rows": len(rows), "written": append_new(result["market"], KIND_LAB_BACKTESTS, rows, "computed_at",
                                                     known)}
