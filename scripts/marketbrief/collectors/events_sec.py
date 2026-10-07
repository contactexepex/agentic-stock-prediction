"""SEC part of the events collector (US): the results releases (8-K/6-K item 2.02) and the 10-Q/10-K acceptances
of each ticker, timed by their acceptance times.

Not every 2.02 is a quarter's results release (Tesla's quarterly delivery reports, pre-announcements, guidance
updates): every 2.02 is stored as it was filed, and analytics/event_history's results_filter keeps one release per
quarter when the dates are read, using only the reports accepted by the as-of date (so the walk-forward backtest
never looks ahead)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from marketbrief.collectors.event_timing import timing
from marketbrief.constants.config_keys import CFG_SEC_TICKER
from marketbrief.constants.events import ITEM_RESULTS, PRIORITY_FILING, REPORT_FORMS, RESULT_8K_FORMS
from marketbrief.sources.sec_acceptance import time_summary
from marketbrief.sources.sec_client import Edgar
from marketbrief.sources.sec_filings import related_ciks, ticker_submissions

ISO_DATE_LENGTH = 10


def sec_earnings(
    cfg: dict, tickers: dict, user_agent: str, reports: dict | None = None, times: dict | None = None
) -> tuple[dict[str, list[tuple[date, str | None, int]]], list[dict]]:
    """Item 2.02 filings from SEC EDGAR: 8-K/6-K filings with item 2.02 (results of operations),
    timed by acceptance. Given a dict, `reports` receives the 10-Q/10-K filings per ticker: (acceptance date,
    timing, form, period end, acceptance time in UTC). Acceptance times are the checked/corrected ones of Edgar.recent; given a dict,
    `times` receives the summary of those checks (sec_acceptance.time_summary).
    Each ticker's filings are those of its mapped CIK plus the predecessor/related CIKs in
    `fundamentals.predecessor_ciks` (sec_filings.ticker_submissions), each filing once.
    Returns (rows per ticker, one entry per ticker and CIK whose submissions request failed)."""
    edgar = Edgar(user_agent)
    cik_by_ticker = edgar.cik_map()
    related = related_ciks(cfg)
    found: dict[str, list] = {}
    failed: list[dict] = []
    for key, meta in tickers.items():
        cik = cik_by_ticker.get(meta.get(CFG_SEC_TICKER, key).upper())
        if cik is None:
            continue
        recent, errors = ticker_submissions(edgar, key, cik, related)
        failed += errors
        if recent is None:
            continue
        add_filings(cfg, key, recent, found, reports)
    if times is not None:
        times.update(time_summary(edgar))
    return found, failed


def add_filings(cfg: dict, key: str, recent: dict, found: dict, reports: dict | None) -> None:
    """Add one ticker's 2.02 results filings to `found` and, when `reports` is given, its 10-Q/10-K filings."""
    count = len(recent["form"])
    items = recent.get("items") or [""] * count
    period = recent.get("reportDate") or [None] * count
    for index, form in enumerate(recent["form"]):
        accepted = recent["acceptanceDateTime"][index]
        if not accepted:
            continue
        if form in RESULT_8K_FORMS and ITEM_RESULTS in (items[index] or ""):
            day, when = timing(cfg, pd.Timestamp(accepted))
            found.setdefault(key, []).append((day, when, PRIORITY_FILING))
        elif form in REPORT_FORMS and reports is not None:
            stamp = pd.Timestamp(accepted)
            day, when = timing(cfg, stamp)
            period_end = date.fromisoformat(period[index][:ISO_DATE_LENGTH]) if period[index] else None
            accepted_at = stamp.tz_convert("UTC").isoformat() if stamp.tzinfo is not None else None
            reports.setdefault(key, []).append((day, when, form, period_end, accepted_at))
