"""Collect India primary-source data for watchlist tickers from NSE (session code in nse_runner.py):
  announcements  corporate announcements (exchange filings: results, board outcomes, orders,
                 press releases), one market-wide call per run    -> data/india/announcements/
                 Ids are `nse-ann-<seq_id>`; the news-analyst scores them like news items.
  financials     SEBI Integrated Filing (Financials) per ticker, polled only while the latest
                 quarter is missing (capped per run unless --full); each new filing's XBRL gives
                 revenue, total income, profit before tax, net profit, profit to owners and EPS
                 for every period it reports (quarter; half year in Q2; nine months in Q3; full
                 year in Q4), standalone or consolidated. Amounts in INR. -> data/india/financials/
  flows          FII/FPI and DII cash-market net buying (provisional, INR crore) -> data/india/flows/
  delivery       delivery quantity and % per watchlist ticker from the daily security-wise
                 bhavcopy (sec_bhavdata_full_DDMMYYYY.csv) for recent sessions not yet stored
                                                                  -> data/india/delivery/
Append-only, de-duplicated by id; files are dated by the UTC collection day. Prints a JSON
summary; a failed source gets a "failed" entry (with the host to allowlist when unreachable),
an endpoint that answers with no rows at all for the whole market gets a "warnings" entry, and
"notes" give market-wide versus watchlist row counts.
Exit code 1 only if every kind failed. Needs `relations.source: nse` in the market config."""

from __future__ import annotations

from datetime import date

from marketbrief.collectors.collector_store import Problems
from marketbrief.collectors.nse_announcements import announcements
from marketbrief.collectors.nse_delivery import delivery
from marketbrief.collectors.nse_financials import financials
from marketbrief.collectors.nse_flows import flows
from marketbrief.collectors.nse_runner import NseRun, collector_main, run_summary, since_arg, store
from marketbrief.constants.config_keys import CFG_MARKET, CFG_RELATIONS
from marketbrief.constants.kinds import KIND_ANNOUNCEMENTS, KIND_FINANCIALS, KIND_FLOWS
from marketbrief.constants.nse_collection import (
    COLLECTOR_NSE_INDIA,
    DEFAULT_ANNOUNCEMENT_LOOKBACK_DAYS,
    DEFAULT_DELIVERY_LOOKBACK_DAYS,
    DEFAULT_PER_TICKER_FILINGS,
    DEFAULT_SYMBOL_CALLS_PER_RUN,
    MSG_FULL_NSE_HELP,
    NSE_KINDS,
)
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_client import Nse
from marketbrief.sources.nse_parsing import nse_symbols


def collect_kind(run: NseRun, kind: str, settings: dict, args) -> tuple[list[dict], int]:
    """(rows, sources answered) of one kind (see the module docstring)."""
    full = bool(getattr(args, "full", False))
    since = getattr(args, "since", None)
    if kind == KIND_ANNOUNCEMENTS:
        lookback = int(settings.get("announcement_lookback_days", DEFAULT_ANNOUNCEMENT_LOOKBACK_DAYS))
        return announcements(run, lookback, since), 1
    if kind == KIND_FINANCIALS:
        limit = None if full else int(settings.get("symbol_calls_per_run", DEFAULT_SYMBOL_CALLS_PER_RUN))
        per_ticker = None if full else int(settings.get("financial_filings_per_ticker", DEFAULT_PER_TICKER_FILINGS))
        if since is not None:
            limit = per_ticker = None
        return financials(run, limit, per_ticker, since)
    if kind == KIND_FLOWS:
        return flows(run), 1
    return delivery(run, int(settings.get("delivery_lookback_days", DEFAULT_DELIVERY_LOOKBACK_DAYS)))


def collect(cfg: dict, nse: Nse, kinds: list[str], today: date | None = None, args=None) -> dict:
    """Fetch, de-duplicate and append each kind; return the JSON summary."""
    market, settings = cfg[CFG_MARKET], cfg.get(CFG_RELATIONS) or {}
    run = NseRun(nse, nse_symbols(cfg), today or utc_today(), utc_now(), market, Problems())
    new = {}
    for kind in kinds:
        failures_before = len(run.problems.failed)
        try:
            rows, ok = collect_kind(run, kind, settings, args)
        except FetchError as exc:
            run.problems.failed.append(exc.entry(kind))
            new[kind] = None
            continue
        if not ok and len(run.problems.failed) > failures_before:
            new[kind] = None
            continue
        new[kind] = store(market, kind, rows, run.today)
    return run_summary(COLLECTOR_NSE_INDIA, run, new)


def extra_args(parser) -> None:
    """The NSE primary-source collector's own options."""
    parser.add_argument("--full", action="store_true", help=MSG_FULL_NSE_HELP)
    since_arg(parser)  # announcements by week, and every ticker's results filings broadcast since then


def main() -> int:
    """Entry point of scripts/collect_nse_india.py."""
    return collector_main(__doc__, COLLECTOR_NSE_INDIA, NSE_KINDS, collect, extra_args)
