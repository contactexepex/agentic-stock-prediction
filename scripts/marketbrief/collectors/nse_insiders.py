"""Insider trades of the India relations collector: SEBI PIT disclosures. The filing index `corporates-pit-gg` (the
older `corporates-pit` feed dwindled in April 2026; its last rows are dated 2 May 2026) plus each new watchlist
filing's XBRL with one record per disclosed trade -> data/india/insiders/."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.collectors.nse_runner import NseRun, coverage, date_windows
from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.kinds import KIND_INSIDERS
from marketbrief.constants.nse_collection import (
    ENDPOINT_PIT,
    MSG_NO_XBRL,
    MSG_PIT_COVERAGE,
    MSG_PIT_LABEL_DAYS,
    MSG_PIT_LABEL_SINCE,
    NSE_DATE_ARGUMENT,
    PIT_ID_PREFIX,
    SEEN_LOOKBACK_DAYS,
    SOURCE_PIT,
)
from marketbrief.core.storage import recent_ids
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_parsing import iso, parse_ts, pick, rows_of, xbrl
from marketbrief.utils.numbers import parse_nse_number

PERCENT_DECIMALS = 4
FIELD_CATEGORY, FIELD_PERSON = "CategoryOfPerson", "NameOfThePerson"
FIELD_TRADE_FROM = "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate"
FIELD_TRADE_TO = "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate"
FIELD_HELD_BEFORE = "SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding"
FIELD_HELD_AFTER = "SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding"


def percent_of(facts: dict, name: str) -> float | None:
    """An XBRL "pure" value (a fraction: 0.0019 = 0.19%) stored as a percent."""
    value = parse_nse_number(facts.get(name))
    return round(value * 100, PERCENT_DECIMALS) if value is not None else None


def pit_rows(xml: str, ticker: str, app: str, disclosed: datetime | None, url: str, now: str) -> list[dict]:
    """One record per disclosure context in a PIT V2 XBRL instance."""
    _, facts = xbrl(xml)
    found = []
    for context, fact in sorted(facts.items()):
        if FIELD_PERSON not in fact:
            continue
        found.append(
            {
                COL_ID: f"{PIT_ID_PREFIX}{ticker}-{app}-{context}",
                COL_TICKER: ticker,
                "source": SOURCE_PIT,
                "person": fact.get(FIELD_PERSON),
                "person_category": fact.get(FIELD_CATEGORY),
                "security_type": fact.get("TypeOfInstrument"),
                "transaction": fact.get("SecuritiesAcquiredOrDisposedTransactionType"),
                "mode": fact.get("ModeOfAcquisitionOrDisposal"),
                "shares": parse_nse_number(fact.get("SecuritiesAcquiredOrDisposedNumberOfSecurity")),
                "value": parse_nse_number(fact.get("SecuritiesAcquiredOrDisposedValueOfSecurity")),
                "holding_before_pct": percent_of(fact, FIELD_HELD_BEFORE),
                "holding_after_pct": percent_of(fact, FIELD_HELD_AFTER),
                "trade_from": fact.get(FIELD_TRADE_FROM) or None,
                "trade_to": fact.get(FIELD_TRADE_TO) or None,
                "disclosed_at": iso(disclosed),
                "url": url,
                "first_seen_at": now,
            }
        )
    return found


def pit_index(run: NseRun, windows: list[tuple[date, date]]) -> list[dict]:
    """The PIT filing index rows of the windows (one call each)."""
    index = []
    for start, end in windows:
        index += rows_of(
            run.nse.json(
                ENDPOINT_PIT,
                {
                    "index": "equities",
                    "from_date": start.strftime(NSE_DATE_ARGUMENT),
                    "to_date": end.strftime(NSE_DATE_ARGUMENT),
                },
            )
        )
    return index


def insiders(run: NseRun, lookback: int, since: date | None = None) -> list[dict]:
    """The PIT filing index over the last `lookback` days (with `since`: one call per week from
    `since` to today), then each new watchlist filing's XBRL."""
    windows = [(run.today - timedelta(days=lookback), run.today)] if since is None else date_windows(since, run.today)
    index = pit_index(run, windows)
    label = (
        MSG_PIT_LABEL_DAYS.format(lookback=lookback)
        if since is None
        else MSG_PIT_LABEL_SINCE.format(since=since, windows=len(windows))
    )
    coverage(
        MSG_PIT_COVERAGE.format(label=label),
        len(index),
        sum((listed_row.get("symbol") or "").strip().upper() in run.symbols for listed_row in index),
        run.problems,
    )
    done = {
        stored_id.rsplit("-", 1)[0]
        for stored_id in recent_ids(run.market, KIND_INSIDERS, days=SEEN_LOOKBACK_DAYS)
        if stored_id.startswith(PIT_ID_PREFIX)
    }
    found = []
    for row in index:
        ticker = run.symbols.get((row.get("symbol") or "").strip().upper())
        app, xml_url = pick(row, "appId"), pick(row, "xmlFileName")
        if not ticker or not app or f"{PIT_ID_PREFIX}{ticker}-{app}" in done:
            continue
        if since is not None:
            done.add(f"{PIT_ID_PREFIX}{ticker}-{app}")  # backfill: a filing listed in two windows is read once
        if not xml_url:
            run.problems.failed.append({"source": f"insiders:{ticker}:{app}", "url": None, "error": MSG_NO_XBRL})
            continue
        try:
            xml = run.nse.text(xml_url)
        except FetchError as exc:
            run.problems.failed.append(exc.entry(f"insiders:{ticker}:{app}"))
            if exc.host:
                break
            continue
        found += pit_rows(
            xml,
            ticker,
            app,
            parse_ts(pick(row, "broadcastDateTime", "exchdisstime")),
            pick(row, "ixbrl") or xml_url,
            run.now,
        )
    return found
