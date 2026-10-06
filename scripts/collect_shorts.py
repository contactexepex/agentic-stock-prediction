#!/usr/bin/env python3
"""Collect FINRA short-selling data for the watchlist (the `shorts:` section of the market
config; markets without one print `skipped`):
  shorts          daily short-sale volume from FINRA's Reg SHO consolidated file
                  (cdn.finra.org CNMSshvol<YYYYMMDD>.txt), for sessions in the lookback not yet
                  stored -> data/<market>/shorts/. It covers trades reported to FINRA's
                  facilities (off-exchange and ATS volume), not exchange volume, so short_pct is
                  the short share of that volume (around 40-50% is ordinary); compare a ticker with
                  its own history, never with short interest.
  short_interest  FINRA consolidated short interest (api.finra.org, twice a month, published about
                  a week after the settlement date) -> data/<market>/short_interest/
Append-only; ids are finra-shvol-<date>-<ticker> and finra-si-<settlement date>-<ticker>; a
revised value is a new row; a day file that is truncated or misses a watchlist ticker is
stored with `complete` false and fetched again on the next run. Prints a JSON summary: `failed`
lists every file or call that could not be read, a session file missing before the latest completed session, a truncated file (row
count differs from FINRA's trailer) and a watchlist ticker missing from a file. Exit code 1 only
if both kinds failed."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from sources import not_published, stale_cutoff, store_changed, complete_days, summary
from marketbrief.sources.errors import FetchError
from marketbrief.sources.free_source_client import FreeSourceClient
from marketbrief.utils.numbers import parse_accounting_amount
from marketbrief.utils.sessions import sessions_in_window

VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day:%Y%m%d}.txt"
SI_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
SI_FIELDS = ["settlementDate", "symbolCode", "currentShortPositionQuantity", "previousShortPositionQuantity",
             "averageDailyVolumeQuantity", "daysToCoverQuantity", "changePercent", "revisionFlag"]


def finra_symbols(cfg: dict) -> dict[str, str]:
    """FINRA symbol -> watchlist ticker (a ticker may set `finra:`)."""
    return {meta.get("finra", t).upper(): t for t, meta in cfg["tickers"].items()}


def parse_volume(text: str, day: date, symbols: dict[str, str], now: str) -> tuple[list[dict], str | None]:
    """Rows for watchlist symbols, and a problem (truncated file, wrong date) or None. The file is
    pipe-separated with a header and a trailer line holding the number of data rows."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("Date|Symbol|ShortVolume"):
        return [], f"unexpected header: {lines[0][:60] if lines else 'empty file'}"
    data = [ln.split("|") for ln in lines[1:] if "|" in ln]
    trailer = [ln for ln in lines[1:] if "|" not in ln]
    problem = None
    if not trailer or not trailer[-1].isdigit():
        problem = "no row-count trailer (file may be truncated)"
    elif int(trailer[-1]) != len(data):
        problem = f"trailer says {trailer[-1]} rows, file has {len(data)} (truncated?)"
    rows = []
    for parts in data:
        if len(parts) < 5:
            continue
        ticker = symbols.get(parts[1].upper())
        if not ticker:
            continue
        if parts[0] != f"{day:%Y%m%d}":
            problem = f"file for {day} holds date {parts[0]}"
            continue
        short, exempt, total = (parse_accounting_amount(parts[2]), parse_accounting_amount(parts[3]),
                                parse_accounting_amount(parts[4]))
        rows.append({"id": f"finra-shvol-{day}-{ticker}", "date": str(day), "ticker": ticker,
                     "short_volume": short, "short_exempt_volume": exempt, "total_volume": total,
                     "short_pct": round(short / total * 100, 2) if short is not None and total else None,
                     "markets": parts[5] if len(parts) > 5 else None, "source": "finra_regsho_cnms",
                     "first_seen_at": now})
    return rows, problem


def daily_volume(client, cfg: dict, today: date, conf: dict, now: str, failed: list, notes: list) -> tuple[list, int]:
    market, symbols = cfg["market"], finra_symbols(cfg)
    have = complete_days(market, "shorts", "ticker", set(symbols.values()))
    cutoff, rows, ok = stale_cutoff(cfg, today), [], 0
    for d in sessions_in_window(cfg, today, int(conf.get("lookback_days", 10))):
        if str(d) in have:
            ok += 1
            continue
        url = VOLUME_URL.format(day=d)
        try:
            text = client.get(url).decode("utf-8", "replace")
        except FetchError as exc:
            if not_published(exc) and d >= cutoff:
                notes.append(f"shorts: no FINRA file for {d} yet (HTTP {exc.status}); published after the close")
                continue
            failed.append(exc.entry("finra_short_volume", date=str(d)))
            if exc.host or exc.status is None:
                break
            continue
        got, problem = parse_volume(text, d, symbols, now)
        if problem:
            failed.append({"source": "finra_short_volume", "date": str(d), "url": url, "error": problem})
        missing = sorted(set(symbols.values()) - {r["ticker"] for r in got})
        if missing:
            failed.append({"source": "finra_short_volume", "date": str(d), "url": url,
                           "error": f"no row for watchlist tickers {missing}"})
        for r in got:   # an incomplete day is stored but fetched again next run (complete_days)
            r["complete"] = not problem and not missing
        ok += 1
        rows += got
    return rows, ok


def parse_short_interest(payload, symbols: dict[str, str], now: str) -> list[dict]:
    rows = []
    for r in payload if isinstance(payload, list) else []:
        ticker = symbols.get((r.get("symbolCode") or "").upper())
        settle = r.get("settlementDate")
        if not ticker or not settle:
            continue
        rows.append({"id": f"finra-si-{settle}-{ticker}", "settlement_date": settle, "ticker": ticker,
                     "short_interest": parse_accounting_amount(r.get("currentShortPositionQuantity")),
                     "prev_short_interest": parse_accounting_amount(r.get("previousShortPositionQuantity")),
                     "change_pct": parse_accounting_amount(r.get("changePercent")),
                     "avg_daily_volume": parse_accounting_amount(r.get("averageDailyVolumeQuantity")),
                     "days_to_cover": parse_accounting_amount(r.get("daysToCoverQuantity")),
                     "revised": bool(r.get("revisionFlag")), "source": "finra_short_interest",
                     "first_seen_at": now})
    return rows


def short_interest(client, cfg: dict, today: date, conf: dict, now: str, failed: list, notes: list) -> list[dict]:
    symbols = finra_symbols(cfg)
    lookback = int(conf.get("lookback_days", 45))
    body = {"limit": 5000, "fields": SI_FIELDS,
            "domainFilters": [{"fieldName": "symbolCode", "values": sorted(symbols)}],
            "dateRangeFilters": [{"fieldName": "settlementDate", "startDate": str(today - timedelta(days=lookback)),
                                  "endDate": str(today)}]}
    payload = client.json(SI_URL, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Accept": "application/json"})
    rows = parse_short_interest(payload, symbols, now)
    if not rows:
        failed.append({"source": "finra_short_interest", "url": SI_URL,
                       "error": f"no rows for the watchlist in the last {lookback} days (settlements are twice a month)"})
        return rows
    latest = max(r["settlement_date"] for r in rows)
    missing = sorted(set(symbols.values()) - {r["ticker"] for r in rows if r["settlement_date"] == latest})
    if missing:
        failed.append({"source": "finra_short_interest", "url": SI_URL,
                       "error": f"settlement {latest}: no row for watchlist tickers {missing}"})
    notes.append(f"short_interest: {len(rows)} rows, settlements "
                 f"{', '.join(sorted({r['settlement_date'] for r in rows}))}")
    return rows


def collect(cfg: dict, client, today: date, now: str) -> dict:
    market, conf = cfg["market"], cfg["shorts"]
    new, failed, notes, warnings = {}, [], [], []
    if (conf.get("daily_volume") or {}).get("enabled", True):
        rows, ok = daily_volume(client, cfg, today, conf.get("daily_volume") or {}, now, failed, notes)
        new["shorts"] = store_changed(market, "shorts", rows, today,
                                      ["short_volume", "short_exempt_volume", "total_volume", "complete"]) if ok else None
    if (conf.get("short_interest") or {}).get("enabled", True):
        try:
            rows = short_interest(client, cfg, today, conf.get("short_interest") or {}, now, failed, notes)
            new["short_interest"] = store_changed(market, "short_interest", rows, today,
                                                  ["short_interest", "avg_daily_volume", "days_to_cover"]) if rows else None
        except FetchError as exc:
            failed.append(exc.entry("finra_short_interest"))
            new["short_interest"] = None
    return summary("shorts", market, new, failed, notes, warnings, client)


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    if not cfg.get("shorts"):
        print(json.dumps({"collector": "shorts", "market": cfg["market"],
                          "skipped": "no `shorts:` section in this market's config"}))
        return 0
    client = FreeSourceClient(pause=float(cfg["shorts"].get("pause_seconds", 0.5)))
    out = collect(cfg, client, utc_today(), utc_now())
    print(json.dumps(out, indent=2))
    return 1 if out["new"] and all(v is None for v in out["new"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
