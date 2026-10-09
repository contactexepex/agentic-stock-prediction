"""What `add` stores for one trader (run.py describes the rules): the predictions that passed and one abstention row
per company that is not fully predicted, with the strongest reason code (killed > timeout > blocked_quality >
earnings_window > gate_failed > abstained)."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.traders import constants as c
from marketbrief.traders.inputs import GateInputs
from marketbrief.traders.records import abstention_row
from marketbrief.traders.registry import Trader
from marketbrief.traders.input_parts import expected
from marketbrief.traders.run import (PRECEDENCE, automatic_code, file_stamp, gate_lines, read_lines, run_as_of, stored,
                                     timed_out)
from marketbrief.traders.sessions import entry_session


def frame_for(gi: GateInputs, ticker: str) -> dict:
    """market, as_of, session and made_at (the gate's clock) of an abstention row."""
    feats = gi.features.get(ticker)
    as_of = feats["as_of_date"] if feats else run_as_of(gi)
    return {"market": gi.market, "as_of": as_of, "session": entry_session(gi.cfg, as_of),
            "made_at": gi.now.isoformat().replace("+00:00", "Z")}


def everyone(one: Trader, gi: GateInputs, code: str, reason: str) -> list[dict]:
    """The same abstention for every active company without a stored prediction (kill switch, timeout)."""
    rows = []
    for ticker in sorted(gi.active):
        horizons = [h for h in one.horizons if not stored(one, gi, ticker, h)]
        if horizons:
            rows.append(abstention_row(one, frame_for(gi, ticker), ticker, horizons,
                                       {"reason_code": code, "reason": reason, "attempts": 0}))
    return rows


def abstentions(one: Trader, gi: GateInputs, gated: dict, attempts: int) -> list[dict]:
    """Rows for the companies a gated file does not fully predict."""
    per: dict[str, dict] = defaultdict(lambda: {"horizons": set(), "codes": set(), "gate_codes": set(), "reason": None})
    predicted = {(row["ticker"], row["horizon_days"]) for row in gated["rows"]}
    for ticker, (horizons, reason) in gated["skipped"].items():
        per[ticker]["horizons"] |= set(horizons)
        per[ticker]["codes"].add(c.AB_ABSTAINED)
        per[ticker]["reason"] = reason
    for ticker, failures in gated["failed"].items():
        for horizon, codes in failures.items():
            per[ticker]["horizons"].add(horizon)
            per[ticker]["codes"].add(c.AB_GATE_FAILED)
            per[ticker]["gate_codes"] |= set(codes)
    for ticker in gi.active:
        code = automatic_code(gi, ticker)
        if code:
            per[ticker]["horizons"] |= {h for h in one.horizons if (ticker, h) not in predicted}
            per[ticker]["codes"].add(code)
    rows = []
    for ticker, cell in sorted(per.items()):
        horizons = [h for h in cell["horizons"] if (ticker, h) not in predicted and not stored(one, gi, ticker, h)]
        if not horizons:
            continue
        code = next(code for code in PRECEDENCE if code in cell["codes"])
        rows.append(abstention_row(one, frame_for(gi, ticker), ticker, horizons, {
            "reason_code": code, "reason": cell["reason"], "gate_codes": cell["gate_codes"], "attempts": attempts}))
    return rows


def store(gi: GateInputs, predictions: list[dict], skipped: list[dict]) -> dict:
    """Append the rows not stored yet: predictions in the day file of their made_at, abstentions of the gate's clock."""
    predictions = [row for row in predictions if row["id"] not in gi.stored_predictions]
    skipped = [row for row in skipped if row["id"] not in gi.stored_abstentions]
    by_day: dict = defaultdict(list)
    for row in predictions:
        by_day[pd.Timestamp(row["made_at"]).date()].append(row)
    files = []
    for day, rows in sorted(by_day.items()):
        path = day_file(gi.market, "strategy_predictions", day)
        append_jsonl(path, rows)
        files.append(str(path))
    if skipped:
        path = day_file(gi.market, "strategy_abstentions", gi.now.date())
        append_jsonl(path, skipped)
        files.append(str(path))
    return {"predictions": len(predictions), "abstentions": len(skipped), "files": files}


def add(one: Trader, gi: GateInputs, path: Path, attempt: int) -> tuple[int, dict]:
    """(exit code, summary) of one trader's add (run.py)."""
    summary = {"strategy_id": one.strategy_id, "attempt": attempt, "file": str(path)}
    if not one.enabled:
        reason = c.MSG_KILLED.format(strategy_id=one.strategy_id, path=one.agent_file.name)
        return 0, {**summary, "status": c.AB_KILLED, **store(gi, [], everyone(one, gi, c.AB_KILLED, reason))}
    if timed_out(gi):
        rows = everyone(one, gi, c.AB_TIMEOUT, "not through the gate by the deadline (open - 15 minutes)")
        return 0, {**summary, "status": c.AB_TIMEOUT, **store(gi, [], rows)}
    gated = gate_lines(read_lines(path), one, gi, file_stamp(path, gi), expected(path.parent, one.strategy_id))
    summary |= {"valid": len(gated["rows"]), "errors": gated["errors"], "warnings": gated["warnings"]}
    if gated["errors"] and attempt < c.MAX_ATTEMPTS:
        return 1, {**summary, "status": "refused: send the errors back to the trader once, then add --attempt 2",
                   "predictions": 0, "abstentions": 0}
    return 0, {**summary, "status": "stored", **store(gi, gated["rows"], abstentions(one, gi, gated, attempt))}

