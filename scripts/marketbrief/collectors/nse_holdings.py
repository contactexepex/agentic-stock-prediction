"""Quarterly shareholding pattern (company-filed promoter %) and the depository pledge/encumbrance dataset of the
India relations collector, per ticker, polled only while the latest quarter is missing (at most
`symbol_calls_per_run` tickers per run unless --full) -> data/india/holdings/.

Pledge dataset fields (NSE "Pledged data", SEBI system-driven disclosures of encumbrance): its promoter holding
counts only demat accounts flagged as promoter in the depositories' records, so it differs from the company-filed
shareholding pattern and is stored as `sdd_promoter_pct`, never as `promoter_pct`. `percPromoterShares` = promoter
shares encumbered as % of that promoter holding; `percTotShares` = the same as % of all shares;
`percSharesPledged` = every pledge in the depository system (any holder, e.g. margin pledges) as % of demat
shares."""

from __future__ import annotations

from datetime import date, timedelta

from marketbrief.collectors.nse_runner import NseRun, coverage
from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.kinds import KIND_HOLDINGS
from marketbrief.constants.nse_collection import (
    ENDPOINT_PLEDGE,
    ENDPOINT_SHAREHOLDING,
    MSG_HOLDINGS_CALLS,
    MSG_HOLDINGS_NO_ROWS,
    MSG_HOLDINGS_POLLED,
    PLEDGE_ID_PREFIX,
    SEEN_KEEP_QUARTERS,
    SEEN_LOOKBACK_DAYS,
    SHP_ID_PREFIX,
    SOURCE_PLEDGE,
    SOURCE_SHAREHOLDING,
)
from marketbrief.core.storage import recent_ids
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_parsing import iso, parse_day, parse_ts, pick, rows_of, short_hash
from marketbrief.utils.numbers import parse_nse_number

PERIOD_LENGTH = 10  # the period in an id: YYYY-MM-DD
TICKER_SUFFIX_LENGTH = 11  # "-YYYY-MM-DD" after the ticker


def latest_quarter_end(today: date) -> date:
    """The most recent calendar quarter end strictly before today."""
    return date(today.year, ((today.month - 1) // 3) * 3 + 1, 1) - timedelta(days=1)


def due_tickers(stored: dict[str, str], tickers: list[str], today: date, limit: int | None) -> list[str]:
    """Tickers whose latest stored period is before the latest quarter end, capped per run so a
    filing season spreads its calls over several runs: tickers with nothing stored come first
    (oldest stored period first), ties rotated by a daily hash."""
    quarter = str(latest_quarter_end(today))
    due = [ticker for ticker in tickers if stored.get(ticker, "") < quarter]
    due.sort(key=lambda ticker: (stored.get(ticker, ""), short_hash(ticker, today)))
    return due if limit is None else due[:limit]


def stored_periods(market: str, prefix: str) -> dict[str, str]:
    """Latest stored period per ticker from ids like <prefix>-<TICKER>-<YYYY-MM-DD>-<hash>."""
    latest: dict[str, str] = {}
    for stored_id in recent_ids(market, KIND_HOLDINGS, days=SEEN_LOOKBACK_DAYS):
        if stored_id.startswith(prefix + "-"):
            body = stored_id[len(prefix) + 1 :].rsplit("-", 1)[0]
            ticker, period = body[:-TICKER_SUFFIX_LENGTH], body[-PERIOD_LENGTH:]
            latest[ticker] = max(latest.get(ticker, ""), period)
    return latest


def shp_record(row: dict, ticker: str, now: str) -> dict | None:
    """A shareholding-pattern record (promoter, public and employee-trust %), or None without a period."""
    period = parse_day(pick(row, "date"))
    if period is None:
        return None
    values = {
        "promoter_pct": parse_nse_number(pick(row, "pr_and_prgrp")),  # "0" is a real 0 (no promoter)
        "public_pct": parse_nse_number(pick(row, "public_val")),
        "employee_trust_pct": parse_nse_number(pick(row, "employeeTrusts")),
    }
    filed = parse_ts(pick(row, "broadcastDate", "submissionDate"))
    return {
        COL_ID: f"{SHP_ID_PREFIX}-{ticker}-{period}-" + short_hash(filed, *values.values()),
        COL_TICKER: ticker,
        "period_end": str(period),
        "source": SOURCE_SHAREHOLDING,
        "filed_at": iso(filed),
        "url": pick(row, "xbrl"),
        "first_seen_at": now,
        **values,
    }


def pledge_record(row: dict, ticker: str, now: str) -> dict | None:
    """A promoter pledge/encumbrance record from the depositories' dataset, or None without a period."""
    period = parse_day(pick(row, "shp"))
    if period is None:
        return None
    values = {
        "sdd_promoter_pct": parse_nse_number(pick(row, "percPromoterHolding")),  # depository-flagged promoters only
        "promoter_shares": parse_nse_number(pick(row, "totPromoterHolding")),
        "total_shares": parse_nse_number(pick(row, "totIssuedShares")),
        "promoter_encumbered_shares": parse_nse_number(pick(row, "totPromoterShares")),
        "pledged_pct_of_promoter": parse_nse_number(pick(row, "percPromoterShares")),  # encumbered / promoter holding
        "pledged_pct_of_total": parse_nse_number(pick(row, "percTotShares")),  # encumbered / all shares
        "depository_pledged_shares": parse_nse_number(pick(row, "numSharesPledged")),  # all holders' pledges
        "depository_pledged_pct": parse_nse_number(pick(row, "percSharesPledged")),  # ... as % of demat shares
    }
    # NSE re-stamps broadcastDt on every daily refresh, so the id hashes the values only: a new
    # row is stored only when a number changes.
    return {
        COL_ID: f"{PLEDGE_ID_PREFIX}-{ticker}-{period}-" + short_hash(*values.values()),
        COL_TICKER: ticker,
        "period_end": str(period),
        "source": SOURCE_PLEDGE,
        "promoter_pct": None,
        "filed_at": iso(parse_ts(pick(row, "broadcastDt"))),
        "url": None,
        "first_seen_at": now,
        **values,
    }


HOLDING_DATASETS = (
    (SOURCE_SHAREHOLDING, ENDPOINT_SHAREHOLDING, SHP_ID_PREFIX, shp_record),
    (SOURCE_PLEDGE, ENDPOINT_PLEDGE, PLEDGE_ID_PREFIX, pledge_record),
)


def dataset_rows(run: NseRun, dataset: tuple, due: list[str], by_ticker: dict[str, str]) -> tuple[list, int, int, bool]:
    """(records, calls answered, rows returned, aborted) of one dataset for the due tickers; aborted when the egress
    proxy refuses the host (every other symbol fails the same way)."""
    source, endpoint, _prefix, make = dataset
    found, ok, total = [], 0, 0
    for ticker in due:
        try:
            rows = rows_of(run.nse.json(endpoint, {"index": "equities", "symbol": by_ticker[ticker]}))
        except FetchError as exc:
            run.problems.failed.append(exc.entry(f"holdings:{source}:{ticker}"))
            if exc.host:
                return found, ok, total, True
            continue
        ok += 1
        total += len(rows)
        if not rows:
            run.problems.notes.append(MSG_HOLDINGS_NO_ROWS.format(source=source, ticker=ticker))
        records = [x for r in rows if (x := make(r, ticker, run.now))]
        periods = sorted({x["period_end"] for x in records}, reverse=True)[:SEEN_KEEP_QUARTERS]
        found += [x for x in records if x["period_end"] in periods]
    return found, ok, total, False


def holdings(run: NseRun, limit: int | None) -> tuple[list[dict], int]:
    """The shareholding and pledge records of the tickers missing the latest quarter (at most `limit`)."""
    found, ok = [], 0
    by_ticker = {ticker: symbol for symbol, ticker in run.symbols.items()}
    for dataset in HOLDING_DATASETS:
        source, _endpoint, prefix, _make = dataset
        due = due_tickers(stored_periods(run.market, prefix), list(by_ticker), run.today, limit)
        run.problems.notes.append(
            MSG_HOLDINGS_POLLED.format(source=source, count=len(due), quarter=latest_quarter_end(run.today))
        )
        records, answered, total, aborted = dataset_rows(run, dataset, due, by_ticker)
        found += records
        ok += answered
        if aborted:
            return found, ok
        if (
            due
            and total == 0
            and not any(failure["source"].startswith(f"holdings:{source}") for failure in run.problems.failed)
        ):
            coverage(MSG_HOLDINGS_CALLS.format(source=source, count=len(due)), 0, 0, run.problems)
    return found, ok
