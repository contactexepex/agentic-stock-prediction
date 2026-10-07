"""The day's debate, persisted (scripts/agent_reasoning.py validate F | add F [--valid-only]).

After the forecast gate and the append of the calls, the forecaster's work/reasoning.jsonl holds one record
per watchlist ticker: the bull and bear cases as passed to it (<= 80 words each), its verdict (<= 60 words),
its decision per horizon (up | down | abstain) and the evidence ids cited. The gate checks: the schema
(agent_reasoning in core/schema_model.py), id = <as_of_date>-<ticker> with the ticker's latest feature
as-of date, the word limits, every cited id exists and was public by made_at (the forecast gate's
evidence_times), made_at not in the future, every prediction id is stored for this ticker and as-of date
and matches the decision of its horizon (and every up/down decision has its stored call), no id stored
twice. `add` validates again and appends all records (or only the valid ones with --valid-only) with
written_at = now to data/<market>/agent_reasoning/."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from marketbrief.constants.model import (KIND_AGENT_REASONING, MSG_REASONING_ABSTAIN_LISTED, MSG_REASONING_AS_OF,
                                         MSG_REASONING_DECISION, MSG_REASONING_DUPLICATE, MSG_REASONING_ID,
                                         MSG_REASONING_IDS, MSG_REASONING_LATE_EVIDENCE, MSG_REASONING_MADE_AT,
                                         MSG_REASONING_MISSING_FIELD, MSG_REASONING_NO_CALL, MSG_REASONING_NOT_A_CALL,
                                         MSG_REASONING_NOT_JSON, MSG_REASONING_NOT_OBJECT, MSG_REASONING_TEXT,
                                         MSG_REASONING_TICKER, MSG_REASONING_UNKNOWN_EVIDENCE,
                                         MSG_REASONING_UNKNOWN_FIELD, REASONING_CASE_WORDS, REASONING_DECISIONS,
                                         REASONING_VERDICT_WORDS)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.horizons import horizons
from marketbrief.core.schemas import SCHEMAS
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.pipeline.forecast_gate import evidence_times
from marketbrief.utils.timefmt import as_utc_timestamp

TEXT_LIMITS = {"bull_case": REASONING_CASE_WORDS, "bear_case": REASONING_CASE_WORDS,
               "verdict": REASONING_VERDICT_WORDS}
REQUIRED = ("id", "as_of_date", "ticker", "made_at", "bull_case", "bear_case", "verdict", "decision_1d",
            "decision_5d", "evidence_ids", "prediction_ids", "prompt_version")
WRITTEN_AT = "written_at"
REQUIRED_DECISION_HORIZONS = (1, 5)   # decision_1d and decision_5d are required; decision_<k>d of the other horizons
ABSTAIN = "abstain"                   # of config/strategies.yaml is optional (absent = abstain)


def decision(rec: dict, horizon: int):
    """The record's decision for N+k: its decision_<k>d, an absent optional one counting as abstain."""
    value = rec.get(f"decision_{horizon}d")
    return ABSTAIN if value is None and horizon not in REQUIRED_DECISION_HORIZONS else value


def decision_horizons() -> tuple[int, ...]:
    """Every horizon with a decision column: the configured list plus the two required ones."""
    return tuple(sorted({*horizons(), *REQUIRED_DECISION_HORIZONS}))


def gate_context(cfg: dict, con) -> dict:
    """What the checks compare against: watchlist, as-of date per ticker, stored predictions and reasoning
    ids, and evidence publication times."""
    feats = con.execute("SELECT DISTINCT ON (ticker) ticker, as_of_date FROM features_latest "
                        "ORDER BY ticker, as_of_date DESC").fetchall()
    predictions = con.execute("SELECT id, ticker, as_of_date, horizon_days, direction FROM predictions").fetchall()
    return {"tickers": set(cfg["tickers"]), "as_of": {t: str(d) for t, d in feats},
            "predictions": {p[0]: {"ticker": p[1], "as_of": str(p[2]), "horizon": p[3], "direction": p[4]}
                            for p in predictions},
            "stored": {r[0] for r in con.execute("SELECT id FROM agent_reasoning").fetchall()},
            "evidence": evidence_times(con), "now": pd.Timestamp(clock())}


def text_errors(rec: dict) -> list[str]:
    """Word limits and decision values."""
    errors = []
    for name, limit in TEXT_LIMITS.items():
        if not isinstance(rec[name], str) or not rec[name].strip() or len(rec[name].split()) > limit:
            errors.append(MSG_REASONING_TEXT.format(name=name, limit=limit))
    for horizon in decision_horizons():
        if decision(rec, horizon) not in REASONING_DECISIONS:
            errors.append(MSG_REASONING_DECISION.format(horizon=horizon, choices=", ".join(REASONING_DECISIONS)))
    return errors


def evidence_errors(rec: dict, ctx: dict, made) -> list[str]:
    """Cited ids exist and were public by made_at."""
    ids = rec["evidence_ids"]
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        return [MSG_REASONING_IDS.format(name="evidence_ids")]
    errors = []
    unknown = [x for x in ids if x not in ctx["evidence"]]
    if unknown:
        errors.append(MSG_REASONING_UNKNOWN_EVIDENCE.format(ids=unknown))
    late = [x for x in ids if ctx["evidence"].get(x) is not None and made is not None and ctx["evidence"][x] > made]
    if late:
        errors.append(MSG_REASONING_LATE_EVIDENCE.format(ids=late))
    return errors


def prediction_errors(rec: dict, ctx: dict) -> list[str]:
    """Prediction ids are stored calls of this ticker and day and agree with the decisions."""
    ids = rec["prediction_ids"]
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        return [MSG_REASONING_IDS.format(name="prediction_ids")]
    errors = [MSG_REASONING_NOT_A_CALL.format(id=x, ticker=rec["ticker"], as_of=rec["as_of_date"]) for x in ids
              if x not in ctx["predictions"] or ctx["predictions"][x]["ticker"] != rec["ticker"]
              or ctx["predictions"][x]["as_of"] != str(rec["as_of_date"])]
    for horizon in decision_horizons():
        decided = decision(rec, horizon)
        call_id = f"{rec['as_of_date']}-{rec['ticker']}-{horizon}d"
        call = ctx["predictions"].get(call_id) if call_id in ids else None
        if decided in ("up", "down") and (call is None or call["direction"] != decided):
            errors.append(MSG_REASONING_NO_CALL.format(horizon=horizon, decision=decided, call_id=call_id))
        if decided == ABSTAIN and call_id in ids:
            errors.append(MSG_REASONING_ABSTAIN_LISTED.format(horizon=horizon, call_id=call_id))
    return errors


def check_record(rec, ctx: dict, seen: set[str]) -> list[str]:
    """Reasons one record fails the gate (empty = valid)."""
    if not isinstance(rec, dict):
        return [MSG_REASONING_NOT_OBJECT]
    columns = SCHEMAS[KIND_AGENT_REASONING][1]
    errors = [MSG_REASONING_UNKNOWN_FIELD.format(name=k) for k in rec if k not in columns or k == WRITTEN_AT]
    errors += [MSG_REASONING_MISSING_FIELD.format(name=k) for k in REQUIRED if rec.get(k) is None]
    if errors:
        return errors
    ticker = rec["ticker"]
    if ticker not in ctx["tickers"]:
        errors.append(MSG_REASONING_TICKER.format(ticker=ticker))
    if str(rec["as_of_date"]) != ctx["as_of"].get(ticker):
        errors.append(MSG_REASONING_AS_OF.format(given=rec["as_of_date"], want=ctx["as_of"].get(ticker)))
    if rec["id"] != f"{rec['as_of_date']}-{ticker}":
        errors.append(MSG_REASONING_ID.format(want=f"{rec['as_of_date']}-{ticker}"))
    if rec["id"] in ctx["stored"] or rec["id"] in seen:
        errors.append(MSG_REASONING_DUPLICATE.format(id=rec["id"]))
    made = as_utc_timestamp(rec["made_at"])
    if made is None or made > ctx["now"]:
        errors.append(MSG_REASONING_MADE_AT.format(given=rec["made_at"]))
    return errors + text_errors(rec) + evidence_errors(rec, ctx, made) + prediction_errors(rec, ctx)


def validate_file(cfg: dict, path: Path) -> tuple[list[tuple[int, dict]], list[dict]]:
    """([(line, record)], [{line, id, errors}]) of a reasoning file."""
    ctx = gate_context(cfg, connect(cfg["market"]))
    records, problems, seen = [], [], set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as error:
            problems.append({"line": line_no, "id": None, "errors": [MSG_REASONING_NOT_JSON.format(error=error.msg)]})
            continue
        errors = check_record(rec, ctx, seen)
        records.append((line_no, rec))
        if errors:
            problems.append({"line": line_no, "id": rec.get("id") if isinstance(rec, dict) else None,
                             "errors": errors})
        elif isinstance(rec, dict):
            seen.add(rec["id"])
    return records, problems


def main() -> int:
    """validate F | add F [--valid-only]; prints a JSON summary, exit 1 when a record fails (validate, add)."""
    parser = market_arg(__doc__)
    parser.add_argument("action", choices=["validate", "add"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--valid-only", action="store_true", help="add: append the valid records, drop the rest")
    args: argparse.Namespace = parser.parse_args()
    cfg = require_market(args)
    records, problems = validate_file(cfg, args.file)
    bad = {p["line"] for p in problems}
    summary = {"step": "agent_reasoning", "action": args.action, "records": len(records), "errors": problems}
    if args.action == "add" and (not problems or args.valid_only):
        good = [r for line_no, r in records if line_no not in bad]
        columns = SCHEMAS[KIND_AGENT_REASONING][1]   # every column, an optional decision_<k>d absent -> null
        good = [{**{column: None for column in columns}, **r, WRITTEN_AT: utc_now()} for r in good]
        if good:
            append_jsonl(day_file(cfg["market"], KIND_AGENT_REASONING, utc_today()), good)
        summary["added"] = len(good)
    print(json.dumps(summary, indent=2, default=str))
    return 1 if problems and not (args.action == "add" and args.valid_only) else 0


if __name__ == "__main__":
    sys.exit(main())
