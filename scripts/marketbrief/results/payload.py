"""The results section of the cockpit's stock page (wave 2 API / wave 3 frontend): the latest results digest and
earnings-call digest of one ticker and its earlier releases, as plain JSON, read as of a time through
results_digests_asof (no look-ahead). Read only."""

from __future__ import annotations

import json
import math

import pandas as pd

from marketbrief.results.constants import DISCLAIMER, KIND_CONCALL, KIND_RESULTS

FAR_FUTURE = "9999-12-31T00:00:00+00:00"
DIGESTS_SQL = """
SELECT * FROM results_digests_asof(?::TIMESTAMPTZ) WHERE ticker = ? ORDER BY release_at DESC, id"""
JSON_COLUMNS = ("numbers", "consensus", "reaction", "bullets", "sources")
HISTORY_KEYS = ("id", "release_kind", "release_at", "period_end", "fiscal_label", "status", "numbers_status")


def plain(value):
    """A DuckDB value as JSON-safe Python: timestamps and dates as ISO text, NaN/NaT as None, arrays as lists."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("UTC").isoformat() if value.tzinfo else value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def digest_payload(row: dict) -> dict:
    """One stored digest as the page shows it (JSON columns parsed)."""
    out = {key: plain(value) for key, value in row.items()}
    for key in JSON_COLUMNS:
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])
    return out


def stock_results_payload(con, ticker: str, as_of: str | None = None, history: int = 8) -> dict:
    """{ticker, as_of, disclaimer, latest_results, latest_concall, history} for one ticker as of a time (default:
    every stored row). `history` lists up to that many releases (newest first) without bullets or sources."""
    rows = [
        digest_payload(row) for row in con.execute(DIGESTS_SQL, [as_of or FAR_FUTURE, ticker]).df().to_dict("records")
    ]
    return {
        "ticker": ticker,
        "as_of": as_of,
        "disclaimer": DISCLAIMER,
        "latest_results": next((row for row in rows if row["release_kind"] == KIND_RESULTS), None),
        "latest_concall": next((row for row in rows if row["release_kind"] == KIND_CONCALL), None),
        "history": [{key: row.get(key) for key in HISTORY_KEYS} for row in rows[:history]],
    }
