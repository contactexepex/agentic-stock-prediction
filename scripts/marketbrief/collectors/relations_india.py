"""Collect India relationship data for watchlist tickers from NSE (session code in nse_runner.py):
  insiders  SEBI PIT disclosures: the filing index `corporates-pit-gg` (the older `corporates-pit`
            feed dwindled in April 2026; its last rows are dated 2 May 2026) plus each new watchlist filing's
            XBRL with one record per disclosed trade              -> data/india/insiders/
  deals     bulk and block deals from the large-deal snapshot (complete for the latest session),
            falling back to the archive CSVs; `--deals-backfill N` also asks the historical API
            per ticker for the last N days (market-wide calls are capped at 70 rows)
                                                                  -> data/india/deals/
  holdings  quarterly shareholding pattern (company-filed promoter %) and the depository
            pledge/encumbrance dataset, per ticker, polled only while the latest quarter is
            missing (at most `symbol_calls_per_run` tickers per run unless --full)
                                                                  -> data/india/holdings/
Append-only, de-duplicated by id; files are dated by the UTC collection day. Prints a JSON
summary; a source that fails gets a "failed" entry naming the host to allowlist, and an
endpoint that answers with no rows at all for the whole market gets a "warnings" entry (so a
retired or blocked endpoint is not mistaken for a quiet day); "notes" give market-wide versus
watchlist row counts. Exit code 1 only if every kind failed. Needs `relations.source: nse` in the market config.

Pledge dataset fields (NSE "Pledged data", SEBI system-driven disclosures of encumbrance): its
promoter holding counts only demat accounts flagged as promoter in the depositories' records,
so it differs from the company-filed shareholding pattern and is stored as `sdd_promoter_pct`,
never as `promoter_pct`. `percPromoterShares` = promoter shares encumbered as % of that promoter
holding; `percTotShares` = the same as % of all shares; `percSharesPledged` = every pledge in
the depository system (any holder, e.g. margin pledges) as % of demat shares."""

from __future__ import annotations

from datetime import date

from marketbrief.collectors.collector_store import Problems
from marketbrief.collectors.nse_deals import deals
from marketbrief.collectors.nse_holdings import holdings
from marketbrief.collectors.nse_insiders import insiders
from marketbrief.collectors.nse_runner import NseRun, collector_main, run_summary, since_arg, store
from marketbrief.constants.config_keys import CFG_MARKET, CFG_RELATIONS
from marketbrief.constants.kinds import KIND_DEALS, KIND_INSIDERS
from marketbrief.constants.nse_collection import (
    COLLECTOR_RELATIONS,
    DEFAULT_DEAL_LOOKBACK_DAYS,
    DEFAULT_INSIDER_LOOKBACK_DAYS,
    DEFAULT_SYMBOL_CALLS_PER_RUN,
    MSG_DEALS_BACKFILL_HELP,
    MSG_FULL_RELATIONS_HELP,
    RELATION_KINDS,
)
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_client import Nse
from marketbrief.sources.nse_parsing import nse_symbols


def collect_kind(run: NseRun, kind: str, settings: dict, args) -> tuple[list[dict], int]:
    """(rows, sources answered) of one kind (see the module docstring)."""
    since = getattr(args, "since", None)
    if kind == KIND_INSIDERS:
        lookback = int(settings.get("insider_lookback_days", DEFAULT_INSIDER_LOOKBACK_DAYS))
        return insiders(run, lookback, since), 1
    if kind == KIND_DEALS:
        backfill = int(getattr(args, "deals_backfill", 0) or 0)
        if since is not None:  # deals: the per-ticker historical API from `since`
            backfill = max(backfill, (run.today - since).days)
        return deals(run, int(settings.get("deal_lookback_days", DEFAULT_DEAL_LOOKBACK_DAYS)), backfill)
    limit = (
        None
        if bool(getattr(args, "full", False))
        else int(settings.get("symbol_calls_per_run", DEFAULT_SYMBOL_CALLS_PER_RUN))
    )
    return holdings(run, limit)


def collect(cfg: dict, nse: Nse, kinds: list[str], today: date | None = None, args=None) -> dict:
    """Fetch, de-duplicate and append each kind; return the JSON summary."""
    market, settings = cfg[CFG_MARKET], cfg.get(CFG_RELATIONS) or {}
    run = NseRun(nse, nse_symbols(cfg), today or utc_today(), utc_now(), market, Problems())
    new = {}
    for kind in kinds:
        failures_before = len(run.problems.failed)
        try:
            rows, sources_ok = collect_kind(run, kind, settings, args)
        except FetchError as exc:
            run.problems.failed.append(exc.entry(kind))
            new[kind] = None
            continue
        if not sources_ok and len(run.problems.failed) > failures_before:
            new[kind] = None
            continue
        new[kind] = store(market, kind, rows, run.today)
    return run_summary(COLLECTOR_RELATIONS, run, new)


def extra_args(parser) -> None:
    """The relations collector's own options."""
    parser.add_argument("--deals-backfill", type=int, default=0, metavar="DAYS", help=MSG_DEALS_BACKFILL_HELP)
    parser.add_argument("--full", action="store_true", help=MSG_FULL_RELATIONS_HELP)
    since_arg(parser)  # PIT index by week, and the deals backfill from that date


def main() -> int:
    """Entry point of scripts/collect_relations_india.py."""
    return collector_main(__doc__, COLLECTOR_RELATIONS, RELATION_KINDS, collect, extra_args)
