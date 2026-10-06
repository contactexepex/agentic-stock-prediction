"""Results of the NSE primary-source collector: SEBI Integrated Filing XBRL per period and basis (standalone or
consolidated) -> data/india/financials/. Results filings of the tickers missing the latest quarter are read (at most
`symbol_calls_per_run` tickers, the newest `financial_filings_per_ticker` unseen filings each); with `since`
(backfill): every ticker, and every unseen filing broadcast on or after `since`."""
from __future__ import annotations

import re
from datetime import date
from typing import NamedTuple

from marketbrief.collectors.nse_holdings import due_tickers, latest_quarter_end
from marketbrief.collectors.nse_runner import NseRun, coverage
from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.kinds import KIND_FINANCIALS
from marketbrief.constants.nse_collection import (ENDPOINT_INTEGRATED, FINANCIAL_ID_PREFIX, INTEGRATED_TYPE,
                                                  MSG_FINANCIALS_CALLS, MSG_FINANCIALS_NONE_LISTED,
                                                  MSG_FINANCIALS_POLLED, SEEN_LOOKBACK_DAYS)
from marketbrief.core.storage import recent_ids
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_parsing import iso, parse_day, parse_ts, pick, rows_of, xbrl
from marketbrief.utils.numbers import parse_nse_number

# Integrated Filing XBRL items by taxonomy: Ind AS companies, banks (IFBanking), life insurers (IFLI).
REVENUE = ("RevenueFromOperations", "InterestEarned", "NetPremiumIncome")
TOTAL_INCOME = ("Income",)
PBT = ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitLossBeforeTax")
NET_PROFIT = ("ProfitLossForPeriod", "ProfitLossForThePeriod", "ProfitLossAfterTaxAndExtraordinaryItems")
TO_OWNERS = ("ProfitOrLossAttributableToOwnersOfParent",
             "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates")
EPS_BASIC = ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
             "BasicEarningsPerShareAfterExtraordinaryItems",
             "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized")
EPS_DILUTED = ("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
               "DilutedEarningsPerShareAfterExtraordinaryItems",
               "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized")
PERIOD_TYPES = {3: "quarterly", 6: "half_yearly", 9: "nine_months", 12: "annual"}
DAYS_PER_MONTH = 30.44
FIELD_NATURE = "NatureOfReportStandaloneConsolidated"
FIELD_AUDITED = "WhetherResultsAreAuditedOrUnaudited"
ID_PARTS_AFTER_TICKER = 7   # <ticker>-<basis>-<start yyyy-mm-dd>-<end yyyy-mm-dd>
DATE_TEXT_LENGTH = 10


def first(facts: dict, names: tuple) -> tuple[float | None, str | None]:
    """(value, item name) of the first of `names` that has a number among the facts, else (None, None)."""
    for name in names:
        value = parse_nse_number(facts.get(name))
        if value is not None:
            return value, name
    return None, None


class FilingContext(NamedTuple):
    """What a filing's rows share: the ticker, the basis (standalone or consolidated), the taxonomy, the index
    entry's meta and the main facts."""
    ticker: str
    basis: str | None
    taxonomy: str | None
    meta: dict
    main: dict


def financial_row(filing: FilingContext, period: tuple[str, str], facts: dict, now: str) -> dict | None:
    """The record of one non-dimensional duration context (period = ISO start and end), or None when it carries
    no revenue or profit."""
    ticker, basis, taxonomy, meta, main = filing
    revenue, revenue_item = first(facts, REVENUE)
    net, _ = first(facts, NET_PROFIT)
    if revenue is None and net is None:
        return None
    start, end = date.fromisoformat(period[0]), date.fromisoformat(period[1])
    months = round((end - start).days / DAYS_PER_MONTH)
    return {
        COL_ID: f"{FINANCIAL_ID_PREFIX}{ticker}-{basis}-{start}-{end}-{meta['seq']}", COL_TICKER: ticker,
        "basis": basis, "period_type": PERIOD_TYPES.get(months, f"{months}m"), "period_start": str(start),
        "period_end": str(end), "revenue": revenue, "revenue_item": revenue_item,
        "total_income": first(facts, TOTAL_INCOME)[0], "profit_before_tax": first(facts, PBT)[0],
        "net_profit": net, "profit_to_owners": first(facts, TO_OWNERS)[0], "eps_basic": first(facts, EPS_BASIC)[0],
        "eps_diluted": first(facts, EPS_DILUTED)[0],
        "audited": main.get(FIELD_AUDITED) or meta.get("audited"), "taxonomy": taxonomy,
        "filing_type": meta.get("type_Sub"), "filed_at": meta.get("filed_at"), "url": meta.get("xbrl"),
        "seq_id": meta["seq"], "first_seen_at": now,
    }


def financial_rows(xml: str, ticker: str, meta: dict, now: str) -> list[dict]:
    """One record per non-dimensional duration context that carries results (quarter, YTD, year)."""
    contexts, facts = xbrl(xml)
    main = next((facts[c] for c in facts if FIELD_NATURE in facts[c]), {})
    basis = (main.get(FIELD_NATURE) or meta.get("consolidated") or "").lower() or None
    taxonomy = found.group(1) if (found := re.search(r"INTEGRATED_FILING_([A-Z]+)_", meta.get("xbrl") or "")) else None
    filing = FilingContext(ticker, basis, taxonomy, meta, main)
    rows = []
    for context_id, context in contexts.items():
        if context["dimensional"] or not context["start"] or not context["end"]:
            continue
        row = financial_row(filing, (context["start"], context["end"]), facts.get(context_id, {}), now)
        if row:
            rows.append(row)
    return rows


def stored_state(market: str) -> tuple[set[str], dict[str, str]]:
    """(filing sequence ids already stored, newest stored period end per ticker) from the stored financials ids."""
    ids = recent_ids(market, KIND_FINANCIALS, days=SEEN_LOOKBACK_DAYS)
    done = {i.rsplit("-", 1)[1] for i in ids if i.startswith(FINANCIAL_ID_PREFIX)}
    latest: dict[str, str] = {}
    for stored_id in ids:
        if stored_id.startswith(FINANCIAL_ID_PREFIX):
            body = stored_id.rsplit("-", 1)[0]
            ticker = body[len(FINANCIAL_ID_PREFIX):].rsplit("-", ID_PARTS_AFTER_TICKER)[0]
            latest[ticker] = max(latest.get(ticker, ""), body[-DATE_TEXT_LENGTH:])
    return done, latest


def unseen_filings(index: list[dict], done: set[str], since: date | None) -> list[dict]:
    """The listed filings with an XBRL file that are not stored (newest period first); with `since` only those
    broadcast on or after it."""
    filings = sorted((r for r in index if pick(r, "seq_Id") and pick(r, "seq_Id") not in done and pick(r, "xbrl")),
                     key=lambda r: (parse_day(pick(r, "qe_Date")) or date.min, pick(r, "broadcast_Date") or ""),
                     reverse=True)
    if since is not None:
        filings = [r for r in filings
                   if (parse_day(pick(r, "broadcast_Date", "creation_Date")) or date.min) >= since]
    return filings


def filing_meta(row: dict) -> dict:
    """What the filing's rows need from its index entry."""
    return {"seq": pick(row, "seq_Id"), "xbrl": pick(row, "xbrl"), "consolidated": pick(row, "consolidated"),
            "audited": pick(row, "audited"), "type_Sub": pick(row, "type_Sub"),
            "filed_at": iso(parse_ts(pick(row, "broadcast_Date", "creation_Date")))}


def financials(run: NseRun, limit: int | None, per_ticker: int | None, since: date | None = None
               ) -> tuple[list[dict], int]:
    """Results filings of the tickers missing the latest quarter (at most `limit` tickers, the
    newest `per_ticker` unseen filings each). With `since` (backfill): every ticker, and every
    unseen filing broadcast on or after `since`."""
    done, latest = stored_state(run.market)
    by_ticker = {ticker: symbol for symbol, ticker in run.symbols.items()}
    due = due_tickers(latest, list(by_ticker), run.today, limit) if since is None else list(by_ticker)
    run.problems.notes.append(MSG_FINANCIALS_POLLED.format(count=len(due), quarter=latest_quarter_end(run.today)))
    found, ok, total = [], 0, 0
    for ticker in due:
        try:
            index = rows_of(run.nse.json(ENDPOINT_INTEGRATED, {"index": "equities", "symbol": by_ticker[ticker],
                                                               "type": INTEGRATED_TYPE}))
        except FetchError as exc:
            run.problems.failed.append(exc.entry(f"financials:{ticker}"))
            if exc.host:
                return found, ok
            continue
        ok += 1
        total += len(index)
        if not index:
            run.problems.notes.append(MSG_FINANCIALS_NONE_LISTED.format(ticker=ticker))
        for filing in unseen_filings(index, done, since)[:per_ticker]:
            meta = filing_meta(filing)
            try:
                found += financial_rows(run.nse.text(meta["xbrl"]), ticker, meta, run.now)
            except FetchError as exc:
                run.problems.failed.append(exc.entry(f"financials:{ticker}:{meta['seq']}"))
                if exc.host:
                    return found, ok
    if ok and total == 0:
        coverage(MSG_FINANCIALS_CALLS.format(count=ok), 0, 0, run.problems)
    return found, ok
