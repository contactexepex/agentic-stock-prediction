"""The forecast outcome a report was built from (issue #50), for its `report-data` line.

A filled report is kept on a same-day rerun only while it still describes the same data (presentation/report/cli.py).
As of date and regime alone missed a rerun whose forecast came out differently: on 2026-10-07 (US) the first run's
report kept its "collect gate SCHEMA failure" abstain reason after a second run without that failure. The outcome is
a short hash of the calls stored for the as-of date (their ids) and the blocking failure codes of the gate
summaries before the report (`work/steps/validate_<stage>.json` of the market, routine/PROMPT.md: written by this
run; a stage the run did not repeat keeps its last summary in a reused checkout); a change in either rebuilds the
report, and the old one is saved as `previous_report`."""

from __future__ import annotations

import hashlib
import json

from marketbrief.core import paths

CALL_IDS_SQL = "SELECT DISTINCT id FROM predictions WHERE as_of_date = ?::DATE ORDER BY id"
GATE_SUMMARY_GLOB = "work/steps/validate_*.json"
REPORT_STAGE = "report"          # the report gate runs on the report itself, after it is built: not an input
OUTCOME_HASH_CHARS = 12


def gate_failures(market: str) -> dict[str, list[str]]:
    """Stage -> sorted blocking failure codes of this market's gate summaries saved in work/steps/ (none: {})."""
    out = {}
    for path in sorted(paths.ROOT.glob(GATE_SUMMARY_GLOB)):
        try:
            summary = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(summary, dict) or summary.get("market") != market or summary.get("stage") == REPORT_STAGE:
            continue
        failures = summary.get("failures") if isinstance(summary.get("failures"), list) else []
        codes = {str(failure.get("code")) if isinstance(failure, dict) else str(failure) for failure in failures}
        out[str(summary.get("stage"))] = sorted(codes)
    return out


def forecast_outcome(con, market: str, as_of) -> str:
    """A short hash of the as-of date's stored call ids and this run's gate failures before the report."""
    calls = [row[0] for row in con.execute(CALL_IDS_SQL, [str(as_of)]).fetchall()]
    text = json.dumps({"calls": calls, "gates": gate_failures(market)}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:OUTCOME_HASH_CHARS]
