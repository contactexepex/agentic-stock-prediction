"""NSE's provisional FII/DII cash figures of the NSE primary-source collector -> data/india/flows/."""

from __future__ import annotations

import re

from marketbrief.collectors.nse_runner import NseRun, coverage
from marketbrief.constants.columns import COL_DATE, COL_ID
from marketbrief.constants.nse_collection import ENDPOINT_FLOWS, MSG_FLOWS_COVERAGE, SOURCE_FIIDII
from marketbrief.sources.nse_parsing import parse_day, pick, rows_of
from marketbrief.utils.numbers import parse_nse_number


def flows(run: NseRun) -> list[dict]:
    """One row per category (FII/FPI, DII) and day of NSE's FII/DII report."""
    rows = rows_of(run.nse.json(ENDPOINT_FLOWS))
    coverage(MSG_FLOWS_COVERAGE, len(rows), None, run.problems)
    found = []
    for row in rows:
        day, category = parse_day(pick(row, "date")), pick(row, "category")
        if day is None or not category:
            continue
        found.append(
            {
                COL_ID: f"nse-fiidii-{day}-{re.sub(r'[^a-z]+', '', category.lower())}",
                COL_DATE: str(day),
                "category": category,
                "buy_cr": parse_nse_number(pick(row, "buyValue")),
                "sell_cr": parse_nse_number(pick(row, "sellValue")),
                "net_cr": parse_nse_number(pick(row, "netValue")),
                "provisional": True,
                "source": SOURCE_FIIDII,
                "first_seen_at": run.now,
            }
        )
    return found
