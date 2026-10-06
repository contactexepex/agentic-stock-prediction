"""Collect quarterly, half-yearly and annual financial data for watchlist tickers from SEC
EDGAR's free XBRL "company facts" API (data.sec.gov/api/xbrl/companyfacts/CIK##########.json)
into data/<market>/fundamentals/YYYY/MM/<today>.jsonl.

Facts come from 10-Q and 10-K filings (and their amendments and 10-KT). Each standard concept
(revenue, gross profit, operating income, net income, diluted EPS, operating cash flow, capex,
cash, debt parts, shares) is read from a short list of us-gaap/dei tags in priority order
(CONCEPTS); companies use different tags, and every row keeps the tag it came from. Only
non-dimensional (company total) facts exist in company facts.

One row per ticker x tag x period (start, end) x filing, written only when a filing first
reports that period's value or reports a different value than the one before it (a
restatement, a split adjustment or a rounding change: `prev_value` holds the earlier value).
A comparative period repeated unchanged in a later filing adds nothing. Rows are append-only;
the views in sql/views.sql pick, per period, the best-ranked tag and its newest filing.

`period`, fiscal year and fiscal period: see marketbrief/collectors/fundamentals_xbrl.py.

Cheap to run daily: one submissions request per ticker; the company facts file (1-8 MB) is
downloaded only for a ticker never loaded before, or when a 10-Q/10-K filed in the last
`recheck_days` is not stored yet (the XBRL API can lag a filing by a few hours, so it is
retried on the next run). The first load stores periods ending in the last `history_years`.
Settings: `fundamentals:` in config/markets/<market>.yaml (history_years, recheck_days,
predecessor_ciks for a ticker whose history sits under an earlier registrant; their submission
lists are read too, so a 10-Q/10-K filed under a predecessor CIK triggers a download).
Only for markets with `filings: sec`. Requires SEC_USER_AGENT (see marketbrief/sources/sec_filings.py)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

from marketbrief.collectors.fundamentals_xbrl import extract, facts_url, new_rows
from marketbrief.constants.columns import COL_ACCESSION, COL_TICKER
from marketbrief.constants.config_keys import CFG_FUNDAMENTALS, CFG_MARKET
from marketbrief.constants.fundamentals_collection import (
    COLLECTOR_FUNDAMENTALS,
    DAYS_PER_YEAR,
    DEFAULT_HISTORY_YEARS,
    DEFAULT_RECHECK_DAYS,
    ERROR_TEXT_LIMIT,
    PERIODIC_FORMS,
)
from marketbrief.constants.kinds import KIND_FUNDAMENTALS
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.paths import data_dir
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.sources.sec_acceptance import time_summary, time_warnings
from marketbrief.sources.sec_client import Edgar
from marketbrief.sources.sec_filings import filings_of_forms, related_ciks, require_sec, ticker_submissions, watch_ciks


def stored(market: str) -> tuple[set[str], dict[str, set[str]]]:
    """Row ids already stored, and the accessions stored per ticker."""
    ids, accessions = set(), defaultdict(set)
    for path in (data_dir(market) / KIND_FUNDAMENTALS).glob("**/*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                ids.add(row["id"])
                accessions[row[COL_TICKER]].add(row[COL_ACCESSION])
    return ids, accessions


def pending_filings(periodic: list[dict], recheck: date, stored_accessions: set[str]) -> list[dict]:
    """The 10-Q/10-K filed since `recheck` whose accession is not stored yet."""
    return [
        filing
        for filing in periodic
        if date.fromisoformat(filing["filing_date"]) >= recheck and filing[COL_ACCESSION] not in stored_accessions
    ]


def company_facts(edgar: Edgar, ticker: str, cik: int, predecessors: dict[str, list[int]]) -> list[dict]:
    """The facts of the ticker's mapped CIK and its predecessor CIKs."""
    facts = []
    for company in [cik, *[predecessor for predecessor in predecessors.get(ticker.upper(), []) if predecessor != cik]]:
        facts += extract(edgar.json(facts_url(company)), company)
    return facts


def main() -> int:
    """Entry point of scripts/collect_fundamentals.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--force", action="store_true", help="download company facts even when no new filing is listed")
    args = parser.parse_args()
    cfg = require_market(args)
    market = cfg[CFG_MARKET]
    user_agent = require_sec(cfg, COLLECTOR_FUNDAMENTALS)
    if user_agent is None:
        return 0
    settings = cfg.get(CFG_FUNDAMENTALS, {})
    today = utc_today()
    since = str(
        today - timedelta(days=round(DAYS_PER_YEAR * float(settings.get("history_years", DEFAULT_HISTORY_YEARS))))
    )
    recheck = today - timedelta(days=int(settings.get("recheck_days", DEFAULT_RECHECK_DAYS)))
    predecessors = related_ciks(cfg)

    ids, accessions = stored(market)
    edgar, now = Edgar(user_agent), utc_now()
    ciks, skipped = watch_ciks(cfg, edgar)
    rows, loaded, up_to_date, new_filings, not_in_xbrl, failed = [], [], [], [], [], []
    for ticker, cik in ciks.items():
        # 10-Q/10-K listed under the mapped CIK or a predecessor CIK (each once) trigger a reload
        recent, errors = ticker_submissions(edgar, ticker, cik, predecessors)
        if errors:  # a ticker is loaded only with every one of its submission lists
            failed += errors
            continue
        periodic = filings_of_forms(recent, PERIODIC_FORMS)
        accepted = {periodic_filing[COL_ACCESSION]: periodic_filing["accepted_at"] for periodic_filing in periodic}
        pending = pending_filings(periodic, recheck, accessions[ticker])
        if accessions[ticker] and not pending and not args.force:
            up_to_date.append(ticker)
            continue
        try:
            facts = company_facts(edgar, ticker, cik, predecessors)
        except Exception as exc:
            failed.append({COL_TICKER: ticker, "error": str(exc)[:ERROR_TEXT_LIMIT]})
            continue
        loaded.append(ticker)
        got = new_rows(ticker, facts, ids, since, accepted, now)
        rows += got
        got_accessions = {row[COL_ACCESSION] for row in got}
        for filing in pending:
            # a filing without new values (e.g. a 10-K/A for Part III only, or not in the XBRL API yet)
            # adds no rows and is checked again until it is older than recheck_days
            (new_filings if filing[COL_ACCESSION] in got_accessions else not_in_xbrl).append(
                {
                    COL_TICKER: ticker,
                    "form": filing["form"],
                    COL_ACCESSION: filing[COL_ACCESSION],
                    "filing_date": filing["filing_date"],
                    "report_date": filing["report_date"],
                }
            )
        accessions[ticker] |= got_accessions

    written = append_jsonl(day_file(market, KIND_FUNDAMENTALS, today), rows)
    print(
        json.dumps(
            {
                "collector": COLLECTOR_FUNDAMENTALS,
                "market": market,
                "since": since,
                "new_rows": written,
                "loaded": loaded,
                "up_to_date": len(up_to_date),
                "new_filings": new_filings,
                "revised_rows": sum(row["prev_value"] is not None for row in rows),
                "filings_without_new_values": not_in_xbrl,
                "requests": edgar.requests,
                "sec_times": time_summary(edgar),
                "warnings": time_warnings(edgar),
                "skipped_not_sec": skipped,
                "failed": failed,
            },
            indent=2,
        )
    )
    return 0
