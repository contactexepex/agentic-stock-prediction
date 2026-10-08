"""Seeding (F8.1): the config's companies (`company_meta:`, or the legacy `tickers:`) written once as add events,
so the watchlist events hold today's list.

effective_from = the start of stored history (00:00 UTC of the market's first stored price day), recorded_at = the
seeding time, channel `seed`, one row per company in config order (the loader keeps that order). Identity: name and
Yahoo symbol from the config, sector from `sectors:`; India: exchange NSE and the NSE symbol (the config's `nse`, else
the Yahoo symbol without .NS); US: CIK and exchange from SEC's ticker/exchange file (sources.sec_company), checked
once at seeding. Refused when the market already has seed events (a second seed would only repeat them)."""
from __future__ import annotations

from datetime import datetime, timezone

from marketbrief.constants.config_keys import CFG_SECTORS, META_NSE_SYMBOL
from marketbrief.constants.kinds import KIND_PRICES, KIND_WATCHLIST_EVENTS
from marketbrief.core import paths
from marketbrief.core.clock import clock
from marketbrief.lifecycle import accessor
from marketbrief.lifecycle import constants as text
from marketbrief.lifecycle.constants import CHANNEL_SEED, EVENT_ADD, OK, SKIPPED
from marketbrief.lifecycle.events import stored_events
from marketbrief.lifecycle.loader import config_companies
from marketbrief.lifecycle.store import iso, load_lifecycle_config, store_rows
from marketbrief.lifecycle.validator import event_row, field_errors

SEED_REQUESTED_BY = "cli:session"
NSE_SUFFIX = ".NS"


def history_start(market: str) -> datetime | None:
    """00:00 UTC of the market's first stored price day."""
    days = sorted(path.stem for path in (paths.data_dir(market) / KIND_PRICES).glob("*/*/*.csv"))
    return datetime.fromisoformat(days[0]).replace(tzinfo=timezone.utc) if days else None


def seed_requests(market: str, sources) -> tuple[list[dict], list[str]]:
    """(one add request per config ticker, problems)."""
    config = accessor.config_lists(market)
    tickers, sectors = config_companies(market, config)[0], config.get(CFG_SECTORS) or {}
    sector_of = {ticker: sector for sector, members in sectors.items() for ticker in members or []}
    exchanges = (load_lifecycle_config().get("exchanges") or {}).get(market, {})
    requests, problems = [], []
    for ticker, meta in tickers.items():
        meta = meta or {}
        yahoo = meta.get("yahoo", ticker)
        request = {"market": market, "ticker": ticker, "event": EVENT_ADD, "name": meta.get("name") or ticker,
                   "sector": sector_of.get(ticker), "yahoo": yahoo, "reason": text.SEED_REASON,
                   "requested_by": SEED_REQUESTED_BY, "channel": CHANNEL_SEED,
                   "idempotency_key": f"seed-{market}-{ticker}".replace("&", "_")}
        if market == "india":
            request.update(exchange="NSE", nse_symbol=meta.get(META_NSE_SYMBOL) or yahoo.removesuffix(NSE_SUFFIX),
                           onboarding={"identifiers": SKIPPED, "backfill": SKIPPED, "collect_gate": SKIPPED})
        else:
            found = sources.sec_company(meta.get("sec_ticker", ticker))
            exchange = exchanges.get(found["exchange"]) if found else None
            request.update(exchange=exchange, cik=f"{int(found['cik']):010d}" if found else None,
                           onboarding={"identifiers": OK if found and exchange else SKIPPED, "backfill": SKIPPED,
                                       "collect_gate": SKIPPED})
        problems += [f"{ticker}: {error}" for error in field_errors(request)]
        requests.append(request)
    return requests, problems


def seed(market: str, sources) -> dict:
    """Write the seed events of one market (all or nothing)."""
    existing = [row for row in stored_events(market) if row.get("channel") == CHANNEL_SEED]
    if existing:
        return {"ok": False, "errors": [text.ERR_SEED_EXISTS.format(market=market, count=len(existing))]}
    start = history_start(market)
    if start is None:
        return {"ok": False, "errors": [text.ERR_SEED_NO_HISTORY.format(market=market)]}
    requests, problems = seed_requests(market, sources)
    if problems:
        return {"ok": False, "errors": problems}
    now, rows, ids = clock().replace(microsecond=0), [], set()
    for request in requests:
        row = event_row(request, now, start, ids)
        ids.add(row["id"])
        rows.append(row)
    path = store_rows(rows, KIND_WATCHLIST_EVENTS, market, now)
    return {"ok": True, "market": market, "seeded": len(rows), "effective_from": iso(start), "recorded_at": iso(now),
            "path": path}
