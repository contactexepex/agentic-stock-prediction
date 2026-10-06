#!/usr/bin/env python3
"""Collect India relationship data for watchlist tickers from NSE (session code in nse.py):
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

import csv
import io
import sys
from datetime import date, timedelta

from nse import (collector_main, coverage, date_windows, iso, nse_symbols, parse_day, parse_ts, pick, recent_ids,
                 rows_of, short_hash, since_arg, store, summary_of, xbrl)
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_client import Nse
from marketbrief.utils.numbers import parse_nse_number

KEEP_QUARTERS = 4   # shareholding periods kept per ticker on a first fetch (enough for q/q changes)
KINDS = ["insiders", "deals", "holdings"]


def latest_quarter_end(today: date) -> date:
    """The most recent calendar quarter end strictly before today."""
    q = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1) - timedelta(days=1)
    return q


def due_tickers(stored: dict[str, str], tickers: list[str], today: date, limit: int | None) -> list[str]:
    """Tickers whose latest stored period is before the latest quarter end, capped per run so a
    filing season spreads its calls over several runs: tickers with nothing stored come first
    (oldest stored period first), ties rotated by a daily hash."""
    q = str(latest_quarter_end(today))
    due = [t for t in tickers if stored.get(t, "") < q]
    due.sort(key=lambda t: (stored.get(t, ""), short_hash(t, today)))
    return due if limit is None else due[:limit]


# ---------- insiders: SEBI PIT ----------

def pit_rows(xml: str, ticker: str, app: str, disclosed, url: str, now: str) -> list[dict]:
    """One record per disclosure context in a PIT V2 XBRL instance."""
    _, facts = xbrl(xml)
    out = []
    for ctx, f in sorted(facts.items()):
        if "NameOfThePerson" not in f:
            continue
        pct = lambda k: round(v * 100, 4) if (v := parse_nse_number(f.get(k))) is not None else None  # noqa: E731
        out.append({
            "id": f"nse-pit-{ticker}-{app}-{ctx}", "ticker": ticker, "source": "nse_pit",
            "person": f.get("NameOfThePerson"), "person_category": f.get("CategoryOfPerson"),
            "security_type": f.get("TypeOfInstrument"),
            "transaction": f.get("SecuritiesAcquiredOrDisposedTransactionType"),
            "mode": f.get("ModeOfAcquisitionOrDisposal"),
            "shares": parse_nse_number(f.get("SecuritiesAcquiredOrDisposedNumberOfSecurity")),
            "value": parse_nse_number(f.get("SecuritiesAcquiredOrDisposedValueOfSecurity")),
            # XBRL "pure" values are fractions (0.0019 = 0.19%); stored as percent
            "holding_before_pct": pct("SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding"),
            "holding_after_pct": pct("SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding"),
            "trade_from": f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate") or None,
            "trade_to": f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate") or None,
            "disclosed_at": iso(disclosed), "url": url, "first_seen_at": now,
        })
    return out


def insiders(nse: Nse, symbols: dict[str, str], today: date, lookback: int, now: str, market: str,
             failed: list, notes: list, warnings: list, since: date | None = None) -> list[dict]:
    """The PIT filing index over the last `lookback` days (with `since`: one call per week from
    `since` to today), then each new watchlist filing's XBRL."""
    windows = [(today - timedelta(days=lookback), today)] if since is None else date_windows(since, today)
    idx = []
    for start, end in windows:
        idx += rows_of(nse.json("corporates-pit-gg", {"index": "equities", "from_date": f"{start:%d-%m-%Y}",
                                                      "to_date": f"{end:%d-%m-%Y}"}))
    label = f"{lookback} days" if since is None else f"since {since}, {len(windows)} weekly calls"
    coverage(f"insiders: PIT filings index ({label})", len(idx),
             sum((r.get("symbol") or "").strip().upper() in symbols for r in idx), notes, warnings)
    done = {i.rsplit("-", 1)[0] for i in recent_ids(market, "insiders", days=400) if i.startswith("nse-pit-")}
    out = []
    for r in idx:
        ticker = symbols.get((r.get("symbol") or "").strip().upper())
        app, xml_url = pick(r, "appId"), pick(r, "xmlFileName")
        if not ticker or not app or f"nse-pit-{ticker}-{app}" in done:
            continue
        if since is not None:
            done.add(f"nse-pit-{ticker}-{app}")   # backfill: a filing listed in two windows is read once
        if not xml_url:
            failed.append({"source": f"insiders:{ticker}:{app}", "url": None, "error": "filing has no XBRL file"})
            continue
        try:
            xml = nse.text(xml_url)
        except FetchError as exc:
            failed.append(exc.entry(f"insiders:{ticker}:{app}"))
            if exc.host:
                break
            continue
        out += pit_rows(xml, ticker, app, parse_ts(pick(r, "broadcastDateTime", "exchdisstime")),
                        pick(r, "ixbrl") or xml_url, now)
    return out


# ---------- deals ----------

def deal_record(r: dict, deal_type: str, source: str, symbols: dict[str, str], now: str) -> dict | None:
    """One bulk/block deal from any NSE shape: historical (BD_*), snapshot (camelCase), archive CSV."""
    sym = (pick(r, "BD_SYMBOL", "symbol", "Symbol") or "").upper()
    ticker = symbols.get(sym)
    if not ticker:
        return None
    day = parse_day(pick(r, "BD_DT_DATE", "date", "Date"))
    client = pick(r, "BD_CLIENT_NAME", "clientName", "Client Name")
    side = (pick(r, "BD_BUY_SELL", "buySell", "Buy/Sell", "Buy / Sell") or "").lower() or None
    shares = parse_nse_number(pick(r, "BD_QTY_TRD", "qty", "Quantity Traded"))
    price = parse_nse_number(pick(r, "BD_TP_WATP", "watp", "Trade Price / Wght. Avg. Price"))
    if day is None or shares is None:
        return None
    return {
        "id": f"nse-{deal_type}-{day}-{ticker}-" + short_hash(client, side, shares, price),
        "date": str(day), "ticker": ticker, "deal_type": deal_type, "client": client, "side": side,
        "shares": shares, "price": price, "value": round(shares * price, 2) if price else None,
        "remarks": pick(r, "BD_REMARKS", "remarks", "Remarks"), "source": source, "first_seen_at": now,
    }


def deals(nse: Nse, symbols: dict[str, str], today: date, lookback: int, now: str, notes: list,
          failed: list, warnings: list, backfill_days: int = 0) -> tuple[list[dict], int]:
    """Latest session from the snapshot (archive CSV if it fails), plus optional per-ticker
    backfill. Ids ignore the source, so a deal seen twice is stored once. Returns (rows, sources_ok)."""
    since, out, ok = today - timedelta(days=lookback), [], 0
    try:
        snap = nse.json("snapshot-capital-market-largedeal")
        total = 0
        for deal_type in ("bulk", "block"):
            rows = rows_of(snap, f"{deal_type.upper()}_DEALS_DATA")
            total += len(rows)
            out += [d for r in rows if (d := deal_record(r, deal_type, "nse_snapshot", symbols, now))]
        coverage(f"deals: bulk+block snapshot as on {snap.get('as_on_date')}", total, len(out), notes, warnings)
        ok += 1
    except FetchError as exc:
        failed.append(exc.entry("deals:snapshot"))
        for deal_type in ("bulk", "block"):
            try:
                rows = list(csv.DictReader(io.StringIO(nse.text(f"/content/equities/{deal_type}.csv"))))
            except FetchError as exc2:
                failed.append(exc2.entry(f"deals:{deal_type}:archive"))
                continue
            rows = [{(k or "").strip(): v for k, v in r.items()} for r in rows]
            rows = [r for r in rows if (r.get("Date") or "").strip().upper() != "NO RECORDS"]
            recs = [d for r in rows if (d := deal_record(r, deal_type, "nse_archive", symbols, now))]
            notes.append(f"deals: {deal_type}.csv archive has {len(rows)} rows, {len(recs)} for watchlist tickers")
            out += recs
            ok += 1
    if backfill_days:
        start, calls, found = today - timedelta(days=backfill_days), 0, 0
        for sym in symbols:
            for deal_type in ("bulk", "block"):
                try:
                    rows = rows_of(nse.json("historicalOR/bulk-block-short-deals", {
                        "optionType": f"{deal_type}_deals", "symbol": sym,
                        "from": f"{start:%d-%m-%Y}", "to": f"{today:%d-%m-%Y}"}))
                except FetchError as exc:
                    failed.append(exc.entry(f"deals:{deal_type}:backfill:{sym}"))
                    if exc.host:
                        return out, ok
                    continue
                ok += 1
                calls, found = calls + 1, found + len(rows)
                if len(rows) >= 70:
                    notes.append(f"{deal_type} backfill for {sym} hit NSE's 70-row cap; older deals may be missing")
                out += [d for r in rows if (d := deal_record(r, deal_type, "nse_historical", symbols, now))]
        notes.append(f"deals backfill: {calls} per-ticker calls since {start}, {found} rows returned")
        since = start
    return [d for d in out if d["date"] >= str(since)], ok


# ---------- holdings ----------

def stored_periods(market: str, prefix: str) -> dict[str, str]:
    """Latest stored period per ticker from ids like <prefix>-<TICKER>-<YYYY-MM-DD>-<hash>."""
    latest: dict[str, str] = {}
    for i in recent_ids(market, "holdings", days=400):
        if i.startswith(prefix + "-"):
            body = i[len(prefix) + 1:].rsplit("-", 1)[0]
            t, p = body[:-11], body[-10:]
            latest[t] = max(latest.get(t, ""), p)
    return latest


def shp_record(r: dict, ticker: str, now: str) -> dict | None:
    period = parse_day(pick(r, "date"))
    if period is None:
        return None
    vals = {"promoter_pct": parse_nse_number(pick(r, "pr_and_prgrp")),   # "0" is a real 0 (no promoter), not a default
            "public_pct": parse_nse_number(pick(r, "public_val")),
            "employee_trust_pct": parse_nse_number(pick(r, "employeeTrusts"))}
    filed = parse_ts(pick(r, "broadcastDate", "submissionDate"))
    return {"id": f"nse-shp-{ticker}-{period}-" + short_hash(filed, *vals.values()), "ticker": ticker,
            "period_end": str(period), "source": "nse_shp", "filed_at": iso(filed), "url": pick(r, "xbrl"),
            "first_seen_at": now, **vals}


def pledge_record(r: dict, ticker: str, now: str) -> dict | None:
    period = parse_day(pick(r, "shp"))
    if period is None:
        return None
    vals = {
        "sdd_promoter_pct": parse_nse_number(pick(r, "percPromoterHolding")),
                 # depository-flagged promoters only
        "promoter_shares": parse_nse_number(pick(r, "totPromoterHolding")),
        "total_shares": parse_nse_number(pick(r, "totIssuedShares")),
        "promoter_encumbered_shares": parse_nse_number(pick(r, "totPromoterShares")),
        "pledged_pct_of_promoter": parse_nse_number(pick(r, "percPromoterShares")),    # encumbered / promoter holding
        "pledged_pct_of_total": parse_nse_number(pick(r, "percTotShares")),            # encumbered / all shares
        "depository_pledged_shares": parse_nse_number(pick(r, "numSharesPledged")),   # all holders' pledges
        "depository_pledged_pct": parse_nse_number(pick(r, "percSharesPledged")),     # ... as % of demat shares
    }
    # NSE re-stamps broadcastDt on every daily refresh, so the id hashes the values only: a new
    # row is stored only when a number changes.
    return {"id": f"nse-pledge-{ticker}-{period}-" + short_hash(*vals.values()), "ticker": ticker,
            "period_end": str(period), "source": "nse_pledge", "promoter_pct": None,
            "filed_at": iso(parse_ts(pick(r, "broadcastDt"))), "url": None, "first_seen_at": now, **vals}


def holdings(nse: Nse, symbols: dict[str, str], today: date, now: str, market: str, failed: list,
             notes: list, warnings: list, limit: int | None) -> tuple[list[dict], int]:
    out, ok = [], 0
    by_ticker = {t: s for s, t in symbols.items()}
    for source, endpoint, prefix, make in (
            ("nse_shp", "corporate-share-holdings-master", "nse-shp", shp_record),
            ("nse_pledge", "corporate-pledgedata", "nse-pledge", pledge_record)):
        due = due_tickers(stored_periods(market, prefix), list(by_ticker), today, limit)
        notes.append(f"holdings {source}: {len(due)} ticker(s) polled for quarter {latest_quarter_end(today)}")
        total = 0
        for ticker in due:
            try:
                rows = rows_of(nse.json(endpoint, {"index": "equities", "symbol": by_ticker[ticker]}))
            except FetchError as exc:
                failed.append(exc.entry(f"holdings:{source}:{ticker}"))
                if exc.host:          # host unreachable: every other symbol fails the same way
                    return out, ok
                continue
            ok += 1
            total += len(rows)
            if not rows:
                notes.append(f"holdings {source}: no rows for {ticker}")
            recs = [x for r in rows if (x := make(r, ticker, now))]
            periods = sorted({x["period_end"] for x in recs}, reverse=True)[:KEEP_QUARTERS]
            out += [x for x in recs if x["period_end"] in periods]
        if due and total == 0 and not any(f["source"].startswith(f"holdings:{source}") for f in failed):
            coverage(f"holdings {source}: {len(due)} per-ticker calls", 0, 0, notes, warnings)
    return out, ok


def collect(cfg: dict, nse: Nse, kinds: list[str], today: date | None = None, args=None) -> dict:
    """Fetch, de-duplicate and append each kind; return the JSON summary."""
    from marketbrief.core.clock import utc_now, utc_today
    market, rel = cfg["market"], cfg.get("relations") or {}
    symbols, today, now = nse_symbols(cfg), today or utc_today(), utc_now()
    full = bool(getattr(args, "full", False))
    limit = None if full else int(rel.get("symbol_calls_per_run", 10))
    since = getattr(args, "since", None)
    backfill = int(getattr(args, "deals_backfill", 0) or 0)
    if since is not None:   # deals: the per-ticker historical API from `since`
        backfill = max(backfill, (today - since).days)
    new, failed, notes, warnings = {}, [], [], []
    for kind in kinds:
        n_failed = len(failed)
        try:
            if kind == "insiders":
                rows = insiders(nse, symbols, today, int(rel.get("insider_lookback_days", 14)), now, market, failed,
                                notes, warnings, since)
                ok = 1
            elif kind == "deals":
                rows, ok = deals(nse, symbols, today, int(rel.get("deal_lookback_days", 5)), now, notes, failed,
                                 warnings, backfill)
            else:
                rows, ok = holdings(nse, symbols, today, now, market, failed, notes, warnings, limit)
        except FetchError as exc:
            failed.append(exc.entry(kind))
            new[kind] = None
            continue
        if not ok and len(failed) > n_failed:
            new[kind] = None
            continue
        new[kind] = store(market, kind, rows, today)
    return summary_of("relations_india", market, new, failed, notes, nse, warnings)


def extra_args(ap) -> None:
    ap.add_argument("--deals-backfill", type=int, default=0, metavar="DAYS",
                    help="also query bulk/block deals per ticker for the last DAYS days (2 calls per ticker)")
    ap.add_argument("--full", action="store_true",
                    help="poll every ticker that misses the latest quarter (no per-run cap)")
    since_arg(ap)   # PIT index by week, and the deals backfill from that date


def main() -> int:
    return collector_main(__doc__, "relations_india", KINDS, collect, extra_args)


if __name__ == "__main__":
    sys.exit(main())
