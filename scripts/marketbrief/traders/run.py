"""One trader's pre-open gate pass over its file (docs/SPEC.md F4.2-F4.3): validate, then add with one retry.

The trader writes work/traders/<strategy_id>.jsonl: one prediction per active company x horizon it calls, and one
abstain line `{"strategy_id", "ticker", "abstain": true, "horizons", "reason", "prompt_version"}` for what
it skips. The file's write time, capped at the gate's clock (file_stamp), is the made_at of every line of a trader
without a clock (the Sonnet traders: any made_at they state is replaced) and of every line of the forecaster that
states none (stamped). `validate` checks every line
(gate.check_record) and that every active company is covered. `add`:

- kill switch off (`enabled: false` in the agent file): nothing is read; every active company gets `killed`;
- the gate's clock after the deadline (D's open - 15 minutes): nothing from the file is stored; every active
  company without a stored prediction gets `timeout`;
- attempt 1 with any error: nothing is stored (exit 1); the caller sends the errors back once;
- attempt 2 (the retry) or no errors: valid predictions are stored; every company with a refused or missing horizon
  gets `gate_failed` (attempts 2) and every explicit skip `abstained`; a BLOCKED company gets `blocked_quality`, one
  with earnings within a day `earnings_window` (its records dropped). One abstention row per trader x company x day.
Ids already stored are never written again (a rerun adds nothing)."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from marketbrief.traders import constants as c
from marketbrief.traders.gate import check_record
from marketbrief.traders.inputs import GateInputs
from marketbrief.traders.records import prediction_id
from marketbrief.traders.registry import Trader
from marketbrief.traders.sessions import deadline, entry_session
from marketbrief.utils.timefmt import ISO_UTC, as_utc_timestamp

PRECEDENCE = (c.AB_KILLED, c.AB_TIMEOUT, c.AB_BLOCKED, c.AB_EARNINGS, c.AB_GATE_FAILED, c.AB_ABSTAINED)


def read_lines(path: Path) -> list:
    """The file's non-empty lines, parsed (a line that is not JSON stays text and is refused)."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append(line)
    return out


def run_as_of(gi: GateInputs):
    """The run's as-of date: the newest indicator date of the active companies."""
    dates = [gi.features[t]["as_of_date"] for t in gi.active if t in gi.features]
    if not dates:
        raise SystemExit("no indicator snapshot for any active company: run features.py first")
    return max(dates)


def timed_out(gi: GateInputs) -> bool:
    """True when the gate's clock is past the deadline of the run's entry session."""
    return gi.now > deadline(gi.cfg, entry_session(gi.cfg, run_as_of(gi)))


def abstain_errors(rec: dict, one: Trader, gi: GateInputs) -> list[tuple[str, str]]:
    """An explicit abstain line: this trader, an active company, its own horizons, a reason of 1-60 words."""
    errors = [(c.CODE_SCHEMA, c.MSG_UNKNOWN_FIELD.format(field=k)) for k in rec if k not in c.ABSTAIN_FIELDS]
    if rec.get("strategy_id") != one.strategy_id:
        errors.append((c.CODE_STRATEGY, c.MSG_NOT_TRADER.format(strategy_id=rec.get("strategy_id"),
                                                                want=one.strategy_id)))
    if rec.get("prompt_version") != one.prompt_version:
        errors.append((c.CODE_STRATEGY, c.MSG_PROMPT_VERSION.format(got=rec.get("prompt_version"),
                                                                    want=one.prompt_version)))
    if rec.get("ticker") not in gi.active:
        errors.append((c.CODE_TICKER, c.MSG_TICKER.format(ticker=rec.get("ticker"))))
    horizons = rec.get("horizons", list(one.horizons))
    if not isinstance(horizons, list) or not horizons or any(h not in one.horizons for h in horizons):
        errors.append((c.CODE_STRATEGY, c.MSG_HORIZON.format(horizon=horizons, horizons=list(one.horizons))))
    words = len(rec["reason"].split()) if isinstance(rec.get("reason"), str) else 0
    if not 1 <= words <= c.REASON_WORDS:
        errors.append((c.CODE_REASON, c.MSG_REASON.format(words=c.REASON_WORDS, count=words)))
    made = as_utc_timestamp(rec.get("made_at")) if ISO_UTC.match(str(rec.get("made_at"))) else None
    if made is None:
        errors.append((c.CODE_TIME, c.MSG_MADE_AT.format(made_at=rec.get("made_at"))))
    elif made > as_utc_timestamp(gi.now + timedelta(minutes=c.FUTURE_TOLERANCE_MINUTES)):
        errors.append((c.CODE_TIME, c.MSG_FUTURE.format(made_at=made.isoformat(), now=gi.now.isoformat())))
    return errors


def file_stamp(path: Path, gi: GateInputs) -> str:
    """When the trader wrote its file: the file's modification time, never later than the gate's clock (ISO UTC).
    It is the made_at of every line that states none (the Sonnet traders have no clock; CLAUDE.md data rule 3)."""
    written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) if path.exists() else gi.now
    return min(written, gi.now).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamped(lines: list, stamp: str, one: Trader) -> tuple[list, list[int]]:
    """(the lines with made_at = `stamp`, the line numbers whose own made_at was replaced). A trader without a clock
    (no Bash) always gets the stamp: a made_at it states could only be invented. A trader with a clock keeps its own
    and gets the stamp only where it wrote none."""
    out, replaced = [], []
    for number, rec in enumerate(lines, 1):
        if isinstance(rec, dict) and (not one.has_clock or rec.get("made_at") in (None, "")):
            if rec.get("made_at") not in (None, "", stamp):
                replaced.append(number)
            rec = {**rec, "made_at": stamp}
        out.append(rec)
    return out, replaced


def gate_abstain(rec: dict, one: Trader, gi: GateInputs, out: dict, covered: dict) -> list[tuple[str, str]]:
    """An abstain line: its errors; records the skip and its horizons; a horizon already covered is a repeat."""
    ticker = rec.get("ticker")
    errors = abstain_errors(rec, one, gi)
    horizons = rec.get("horizons", list(one.horizons)) if not errors else []
    if not errors:
        out["skipped"][ticker] = (sorted(set(out["skipped"].get(ticker, ([], ""))[0]) | set(horizons)),
                                  rec["reason"].strip())
    twice = covered[ticker] & set(horizons)
    errors += [(c.CODE_DUPLICATE, c.MSG_HORIZON_TWICE.format(ticker=ticker, horizon=h)) for h in sorted(twice)]
    covered[ticker] |= set(horizons)
    return errors


def gate_prediction(rec, one: Trader, gi: GateInputs, out: dict, state: dict, number: int) -> list[tuple[str, str]]:
    """A prediction line: its errors; a horizon the trader already abstained on is refused as a repeat."""
    ticker = rec.get("ticker") if isinstance(rec, dict) else None
    horizon = rec.get("horizon_days") if isinstance(rec, dict) else None
    if isinstance(horizon, int) and horizon in state["covered"][ticker] and horizon in state["skipped_h"][ticker]:
        errors = [(c.CODE_DUPLICATE, c.MSG_HORIZON_TWICE.format(ticker=ticker, horizon=horizon))]
    else:
        verdict = check_record(rec, one, gi, state["seen"])
        errors = verdict.errors
        out["warnings"] += [{"line": number, "code": code, "detail": msg} for code, msg in verdict.warnings]
        if verdict.row is not None:
            out["rows"].append(verdict.row)
    if errors and ticker in gi.active and isinstance(horizon, int):
        out["failed"][ticker][horizon] = sorted({code for code, _ in errors})
    if isinstance(horizon, int):
        state["covered"][ticker].add(horizon)
    return errors


def gate_lines(lines: list, one: Trader, gi: GateInputs, stamp: str | None = None) -> dict:
    """Every line gated, plus coverage: {rows, errors, warnings, skipped: {ticker: (horizons, reason)},
    failed: {ticker: {horizon: codes}}}. stamp: the made_at of lines without one, and of every line of a clockless
    trader (file_stamp)."""
    out = {"rows": [], "errors": [], "warnings": [], "skipped": {}, "failed": defaultdict(dict)}
    if stamp:
        lines, replaced = stamped(lines, stamp, one)
        out["warnings"] += [{"line": n, "code": c.CODE_STAMPED, "detail": c.MSG_STAMPED.format(stamp=stamp)}
                            for n in replaced]
    state = {"seen": set(), "covered": defaultdict(set), "skipped_h": defaultdict(set)}
    for number, rec in enumerate(lines, 1):
        ticker = rec.get("ticker") if isinstance(rec, dict) else None
        if isinstance(rec, dict) and rec.get("abstain") is True:
            errors = gate_abstain(rec, one, gi, out, state["covered"])
            if not errors:
                state["skipped_h"][ticker] |= set(rec.get("horizons", list(one.horizons)))
        else:
            errors = gate_prediction(rec, one, gi, out, state, number)
        for code, message in errors:
            out["errors"].append({"line": number, "ticker": ticker, "code": code, "detail": message})
    for ticker in sorted(gi.active):
        missing = [h for h in one.horizons if h not in state["covered"][ticker] and not stored(one, gi, ticker, h)]
        if missing and not automatic_code(gi, ticker):
            out["errors"].append({"line": None, "ticker": ticker, "code": c.CODE_NO_RECORD,
                                  "detail": c.MSG_NO_RECORD.format(ticker=ticker) + f" (N+{missing})"})
            for horizon in missing:
                out["failed"][ticker][horizon] = [c.CODE_NO_RECORD]
    return out


def stored(one: Trader, gi: GateInputs, ticker: str, horizon: int) -> bool:
    """True when this prediction is already stored (a rerun)."""
    feats = gi.features.get(ticker)
    return feats is not None and prediction_id(one.strategy_id, feats["as_of_date"], ticker, horizon) in \
        gi.stored_predictions


def automatic_code(gi: GateInputs, ticker: str) -> str | None:
    """blocked_quality or earnings_window when the rules forbid any call on the company."""
    feats = gi.features.get(ticker)
    if feats is None or feats["quality"] == c.QUALITY_BLOCKED:
        return c.AB_BLOCKED
    days = feats["days_to_earnings"]
    return c.AB_EARNINGS if days is not None and days <= c.EARNINGS_DAYS_BLOCK else None
