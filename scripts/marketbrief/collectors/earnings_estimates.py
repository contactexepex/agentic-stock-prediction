"""Yahoo consensus EPS per earnings report (issue #17), stored by the events collector into
data/<market>/earnings_estimates/YYYY/MM/<today>.jsonl. Point in time: a row is appended when a report is first
seen or one of its values changed, with collected_at = when we saw it, so the estimate a decision at time t may
use is the newest row collected by t (view macro earnings_estimates_asof). A past report's estimate is the one
Yahoo shows today, so it is no evidence of what was known before that report unless it was collected before it."""

from __future__ import annotations

import json

from marketbrief.constants.events import SOURCE_YAHOO_CONSENSUS, YAHOO_ESTIMATE_COLUMNS
from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.constants.kinds import KIND_EARNINGS_ESTIMATES
from marketbrief.core import paths

VALUES = tuple(YAHOO_ESTIMATE_COLUMNS.values())


def stored_estimates(market: str) -> dict[tuple[str, str], tuple]:
    """(ticker, report_at) -> the values of its newest stored row."""
    newest: dict[tuple[str, str], tuple[str, tuple]] = {}
    for path in sorted((paths.data_dir(market) / KIND_EARNINGS_ESTIMATES).glob(JSONL_GLOB)):
        for line in path.read_text(encoding=ENCODING_UTF8).splitlines():
            if line.strip():
                row = json.loads(line)
                key = (row["ticker"], row["report_at"])
                if key not in newest or row["collected_at"] >= newest[key][0]:
                    newest[key] = (row["collected_at"], tuple(row.get(value) for value in VALUES))
    return {key: values for key, (_, values) in newest.items()}


def new_estimate_rows(stored: dict, ticker: str, rows: list[dict], now: str) -> list[dict]:
    """The rows of one ticker that are new or changed against `stored` (which is updated)."""
    out = []
    for row in rows:
        key, values = (ticker, row["report_at"]), tuple(row.get(value) for value in VALUES)
        if stored.get(key) == values:
            continue
        stored[key] = values
        out.append({"id": f"{ticker}-{row['report_date']}", "ticker": ticker, **row,
                    "source": SOURCE_YAHOO_CONSENSUS, "collected_at": now})
    return out
