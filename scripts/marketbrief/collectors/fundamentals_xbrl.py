"""SEC XBRL company facts -> `fundamentals` rows: the facts of the CONCEPTS tags, each period's kind (quarter, year to
date, annual, instant), its fiscal label and the rows a filing adds (a value that is new for its tag and period).

`period` is `quarter` (70-130 days; 16-week quarters included), `ytd` (150-300 days: `H1` = 6 months / 2 quarters,
`9M` = 3 quarters), `annual` (340-380 days, `FY`) or `instant` (balance-sheet items and share counts). Fiscal year and
period are those of the filing whose own reporting period ends on that date (SEC's fy/fp describe the filing, not the
fact). A fiscal Q4 is rarely reported as such: the views derive it as FY minus 9M (and quarterly cash flows from the
year-to-date totals) and mark it derived."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import NamedTuple

from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.fundamentals_collection import (
    ANNUAL_DAYS,
    CONCEPTS,
    DEFAULT_NAMESPACE,
    FACTS_URL,
    FISCAL_ANNUAL,
    FISCAL_Q4,
    PERIOD_ANNUAL,
    PERIOD_INSTANT,
    PERIOD_QUARTER,
    PERIOD_YTD,
    PERIODIC_FORMS,
    QUARTER_DAYS,
    YEAR_AGO_DAYS,
    YTD_DAYS,
    YTD_LABELS,
)


def facts_url(cik: int) -> str:
    """The company-facts URL of a CIK."""
    return FACTS_URL.format(cik=int(cik))


def extract(doc: dict, cik: int) -> list[dict]:
    """Company facts JSON -> one dict per fact of a CONCEPTS tag (expected unit, periodic forms)."""
    found = []
    for concept, (unit, tags) in CONCEPTS.items():
        for rank, tag in enumerate(tags):
            namespace, name = tag.split(":", 1) if ":" in tag else (DEFAULT_NAMESPACE, tag)
            for fact in doc.get("facts", {}).get(namespace, {}).get(name, {}).get("units", {}).get(unit, []):
                if fact.get("form") not in PERIODIC_FORMS or fact.get("val") is None:
                    continue
                found.append(
                    {
                        "concept": concept,
                        "tag": f"{namespace}:{name}",
                        "tag_rank": rank,
                        "unit": unit,
                        "start": fact.get("start"),
                        "end": fact["end"],
                        "value": fact["val"],
                        "accession": fact["accn"],
                        "form": fact["form"],
                        "filing_date": fact["filed"],
                        "fy": fact.get("fy"),
                        "fp": fact.get("fp"),
                        "cik": str(int(cik)),
                    }
                )
    return found


def period_kind(start: str | None, end: str) -> str | None:
    """instant (no start), quarter, ytd or annual by the period's length in days; None for a stub or transition."""
    if not start:
        return PERIOD_INSTANT
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    for kind, (low, high) in ((PERIOD_QUARTER, QUARTER_DAYS), (PERIOD_YTD, YTD_DAYS), (PERIOD_ANNUAL, ANNUAL_DAYS)):
        if low <= days <= high:
            return kind
    return None


def report_periods(facts: list[dict]) -> tuple[dict[str, tuple], dict[str, tuple]]:
    """Each filing's own reporting period = the latest end date of its duration facts.
    Returns accession -> (report end, fy, fp) and report end -> (fy, fp) of the earliest filing."""
    by_accession: dict[str, tuple] = {}
    for fact in facts:
        known = by_accession.get(fact["accession"])
        if fact["start"] and (known is None or fact["end"] > known[0]):
            by_accession[fact["accession"]] = (fact["end"], fact["fy"], fact["fp"], fact["filing_date"])
    by_end: dict[str, tuple] = {}
    for end, fiscal_year, fiscal_period, _filed in sorted(
        by_accession.values(), key=lambda accession_row: accession_row[3], reverse=True
    ):
        if fiscal_year and fiscal_period:
            by_end[end] = (fiscal_year, fiscal_period)  # earliest filing for the period wins (sorted newest first)
    return {accession: report[:3] for accession, report in by_accession.items()}, by_end


def label_of(fact: dict, by_accession: dict, by_end: dict) -> tuple[int, str] | None:
    """(fiscal year, fiscal period) of the filing period a fact belongs to, or None when it cannot be told."""
    label = by_end.get(fact["end"])
    if label is None:
        report = by_accession.get(fact["accession"])
        if report and fact["end"] > report[0] and report[1] and report[2]:  # e.g. a cover-page share count
            label = (report[1], report[2])
    if label is None:  # one year before a known period end
        end = date.fromisoformat(fact["end"])
        for known_end, (fiscal_year, fiscal_period) in by_end.items():
            if YEAR_AGO_DAYS[0] <= (date.fromisoformat(known_end) - end).days <= YEAR_AGO_DAYS[1]:
                label = (fiscal_year - 1, fiscal_period)
                break
    return label


def fiscal_label(kind: str, fact: dict, by_accession: dict, by_end: dict) -> tuple[int | None, str | None]:
    """(fiscal year, fiscal period label: FY, Q1-Q4, H1, 9M) of a fact; (None, None) when it cannot be told."""
    label = label_of(fact, by_accession, by_end)
    if label is None:
        return None, None
    fiscal_year, fiscal_period = label
    if kind == PERIOD_ANNUAL:
        return fiscal_year, FISCAL_ANNUAL
    if kind == PERIOD_QUARTER:
        return fiscal_year, FISCAL_Q4 if fiscal_period == FISCAL_ANNUAL else fiscal_period
    if kind == PERIOD_YTD:
        return fiscal_year, YTD_LABELS.get(fiscal_period)
    return fiscal_year, fiscal_period


def row_id(ticker: str, fact: dict) -> str:
    """The id of a fundamentals row: ticker, tag, period and filing."""
    return f"{ticker}-{fact['tag']}-{fact['start'] or PERIOD_INSTANT}-{fact['end']}-{fact['accession']}"


class RowContext(NamedTuple):
    """What a fact's row adds to the fact: its period kind, the earlier value, the fiscal year and period and the
    filing's acceptance time."""

    kind: str
    previous: float | None
    fiscal_year: int | None
    fiscal_period: str | None
    accepted_at: str | None


def fundamentals_row(ticker: str, fact: dict, context: RowContext, now: str) -> dict:
    """The row of one fact: the value, its period, its filing and the earlier value (`prev_value`)."""
    kind, previous, fiscal_year, fiscal_period, accepted_at = context
    return {
        COL_ID: row_id(ticker, fact),
        COL_TICKER: ticker,
        "cik": fact["cik"],
        "concept": fact["concept"],
        "tag": fact["tag"],
        "tag_rank": fact["tag_rank"],
        "unit": fact["unit"],
        "period_start": fact["start"],
        "period_end": fact["end"],
        "period": kind,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "form": fact["form"],
        "accession": fact["accession"],
        "filing_date": fact["filing_date"],
        "accepted_at": accepted_at,
        "value": fact["value"],
        "prev_value": previous,
        "first_seen_at": now,
    }


def new_rows(
    ticker: str, facts: list[dict], stored_ids: set[str], since: str, accepted: dict[str, str], now: str
) -> list[dict]:
    """Rows for facts not stored yet whose value is new for their (tag, period): walk each
    period's facts in filing order; a value equal to the previous filing's is skipped."""
    by_accession, by_end = report_periods(facts)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for fact in facts:
        if fact["end"] >= since:
            groups[(fact["tag"], fact["unit"], fact["start"], fact["end"])].append(fact)
    rows = []
    for key in sorted(groups, key=lambda group_key: (group_key[0], group_key[2] or "", group_key[3])):
        kind = period_kind(key[2], key[3])
        if kind is None:
            continue
        last = None
        for fact in sorted(
            groups[key], key=lambda candidate_fact: (candidate_fact["filing_date"], candidate_fact["accession"])
        ):
            rid = row_id(ticker, fact)
            if rid in stored_ids:
                last = fact["value"]
                continue
            if last is not None and fact["value"] == last:
                continue
            fiscal_year, fiscal_period = fiscal_label(kind, fact, by_accession, by_end)
            context = RowContext(kind, last, fiscal_year, fiscal_period, accepted.get(fact["accession"]))
            rows.append(fundamentals_row(ticker, fact, context, now))
            stored_ids.add(rid)
            last = fact["value"]
    return rows
