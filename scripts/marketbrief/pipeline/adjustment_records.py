"""Records built on a wrong split/bonus adjustment (issue #36 item 4; DESIGN.md section 3).

    python scripts/adjustment_records.py --market M

A wrong adjustments row is cancelled by a later one with `supersedes`. Calls and ranges made between the wrong
row's `detected_at` and its correction's were built on bars carrying the wrong factor, while scoring only knows
the active rows, so their outcomes may be off by that factor. This lists them per correction (the stock's
predictions and ranges with made_at in [wrong detected_at, correction detected_at)) with their stored outcome, so
a human can judge them and name them in the correction's `note`. Read-only: it prints JSON and writes nothing."""

from __future__ import annotations

import json

from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.database import connect

CORRECTIONS_SQL = """
WITH first_rows AS (SELECT DISTINCT ON (id) * FROM adjustments ORDER BY id, detected_at)
SELECT fix.id AS correction_id, wrong.id AS wrong_id, wrong.ticker, wrong.ex_date, wrong.factor AS wrong_factor,
       fix.factor AS correction_factor, wrong.detected_at AS wrong_detected_at,
       fix.detected_at AS correction_detected_at
FROM first_rows fix JOIN first_rows wrong ON fix.supersedes = wrong.id
ORDER BY fix.detected_at, fix.id
"""
CALLS_SQL = """
SELECT 'prediction' AS kind, p.id, p.made_at, p.as_of_date, p.horizon_days, o.scored_at IS NOT NULL AS scored
FROM predictions p LEFT JOIN (SELECT DISTINCT ON (prediction_id) prediction_id, scored_at FROM outcomes
                              ORDER BY prediction_id, scored_at) o ON o.prediction_id = p.id
WHERE p.ticker = ? AND p.made_at >= ? AND p.made_at < ?
"""
RANGES_SQL = """
SELECT 'range' AS kind, r.id, r.made_at, r.as_of_date, r.horizon_days, o.scored_at IS NOT NULL AS scored
FROM ranges_latest r LEFT JOIN (SELECT DISTINCT ON (range_id) range_id, scored_at FROM range_outcomes
                         ORDER BY range_id, scored_at) o ON o.range_id = r.id
WHERE r.ticker = ? AND r.made_at >= ? AND r.made_at < ?
"""


def table_exists(con, name: str) -> bool:
    """True when the DuckDB connection has a table or view of that name."""
    return bool(con.execute("SELECT count(*) FROM duckdb_views() WHERE view_name = ?", [name]).fetchone()[0]
                or con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [name]).fetchone()[0])


def affected_records(con) -> list[dict]:
    """Each correction with the predictions and ranges made while the wrong row was active (oldest first)."""
    if not table_exists(con, "adjustments"):
        return []
    out = []
    for row in con.execute(CORRECTIONS_SQL).df().to_dict("records"):
        params = [row["ticker"], row["wrong_detected_at"], row["correction_detected_at"]]
        records = []
        for name, sql in (("predictions", CALLS_SQL), ("ranges_latest", RANGES_SQL)):
            if table_exists(con, name):
                records += con.execute(sql, params).df().to_dict("records")
        records.sort(key=lambda record: (str(record["made_at"]), record["kind"], record["id"]))
        out.append(
            {
                **{key: str(value) for key, value in row.items() if key not in ("wrong_factor", "correction_factor")},
                "wrong_factor": row["wrong_factor"],
                "correction_factor": row["correction_factor"],
                "records": [
                    {**record, "made_at": str(record["made_at"]), "as_of_date": str(record["as_of_date"]),
                     "horizon_days": int(record["horizon_days"]), "scored": bool(record["scored"])}
                    for record in records
                ],
            }
        )
    return out


def main() -> int:
    """Entry point of scripts/adjustment_records.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    print(json.dumps({"market": cfg["market"], "corrections": affected_records(connect(cfg["market"]))}, indent=2))
    return 0
