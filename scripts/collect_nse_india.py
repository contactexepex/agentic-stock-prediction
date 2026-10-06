#!/usr/bin/env python3
"""Collect India primary-source data for watchlist tickers from NSE (session code in nse.py):
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

import csv
import io
import re
import sys
from datetime import date, datetime, timedelta

from collect_relations_india import due_tickers, latest_quarter_end
from nse import (IST, collector_main, coverage, date_windows, iso, nse_symbols, parse_day, parse_ts, pick,
                 recent_ids, rows_of, since_arg, store, summary_of, xbrl)
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_client import Nse
from marketbrief.utils.numbers import parse_nse_number

KINDS = ["announcements", "financials", "flows", "delivery"]

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


def first(f: dict, names: tuple) -> tuple[float | None, str | None]:
    for n in names:
        v = parse_nse_number(f.get(n))
        if v is not None:
            return v, n
    return None, None


# ---------- announcements ----------

def announcements(nse: Nse, symbols: dict[str, str], today: date, lookback: int, now: str, notes: list,
                  warnings: list, since: date | None = None) -> list[dict]:
    """One market-wide call over the last `lookback` days; with `since` (backfill), one call per
    week from `since` to today."""
    windows = [(today - timedelta(days=lookback), today)] if since is None else date_windows(since, today)
    rows = []
    for start, end in windows:
        got = nse.json("corporate-announcements", {"index": "equities", "from_date": f"{start:%d-%m-%Y}",
                                                   "to_date": f"{end:%d-%m-%Y}"})
        rows += rows_of(got if isinstance(got, list) else got.get("data", []))
    label = f"{lookback} days" if since is None else f"since {since}, {len(windows)} weekly calls"
    coverage(f"announcements ({label})", len(rows),
             sum((r.get("symbol") or "").strip().upper() in symbols for r in rows), notes, warnings)
    out = []
    for r in rows:
        ticker = symbols.get((r.get("symbol") or "").strip().upper())
        seq = pick(r, "seq_id")
        if not ticker or not seq:
            continue
        out.append({"id": f"nse-ann-{seq}", "ticker": ticker, "company": pick(r, "sm_name"),
                    "published_at": iso(parse_ts(pick(r, "an_dt", "exchdisstime", "sort_date"))),
                    "category": pick(r, "desc"), "subject": pick(r, "attchmntText"),
                    "url": pick(r, "attchmntFile"), "source": "nse_announcements", "first_seen_at": now})
    return out


# ---------- financials ----------

def financial_rows(xml: str, ticker: str, meta: dict, now: str) -> list[dict]:
    """One record per non-dimensional duration context that carries results (quarter, YTD, year)."""
    contexts, facts = xbrl(xml)
    main = next((facts[c] for c in facts if "NatureOfReportStandaloneConsolidated" in facts[c]), {})
    basis = (main.get("NatureOfReportStandaloneConsolidated") or meta.get("consolidated") or "").lower() or None
    taxonomy = m.group(1) if (m := re.search(r"INTEGRATED_FILING_([A-Z]+)_", meta.get("xbrl") or "")) else None
    out = []
    for cid, c in contexts.items():
        f = facts.get(cid, {})
        if c["dimensional"] or not c["start"] or not c["end"]:
            continue
        revenue, revenue_item = first(f, REVENUE)
        net, _ = first(f, NET_PROFIT)
        if revenue is None and net is None:
            continue
        start, end = date.fromisoformat(c["start"]), date.fromisoformat(c["end"])
        months = round((end - start).days / 30.44)
        out.append({
            "id": f"nse-fin-{ticker}-{basis}-{start}-{end}-{meta['seq']}", "ticker": ticker, "basis": basis,
            "period_type": PERIOD_TYPES.get(months, f"{months}m"), "period_start": str(start), "period_end": str(end),
            "revenue": revenue, "revenue_item": revenue_item, "total_income": first(f, TOTAL_INCOME)[0],
            "profit_before_tax": first(f, PBT)[0], "net_profit": net, "profit_to_owners": first(f, TO_OWNERS)[0],
            "eps_basic": first(f, EPS_BASIC)[0], "eps_diluted": first(f, EPS_DILUTED)[0],
            "audited": main.get("WhetherResultsAreAuditedOrUnaudited") or meta.get("audited"),
            "taxonomy": taxonomy, "filing_type": meta.get("type_Sub"), "filed_at": meta.get("filed_at"),
            "url": meta.get("xbrl"), "seq_id": meta["seq"], "first_seen_at": now,
        })
    return out


def financials(nse: Nse, symbols: dict[str, str], today: date, now: str, market: str, failed: list,
               notes: list, warnings: list, limit: int | None, per_ticker: int | None,
               since: date | None = None) -> tuple[list[dict], int]:
    """Results filings of the tickers missing the latest quarter (at most `limit` tickers, the
    newest `per_ticker` unseen filings each). With `since` (backfill): every ticker, and every
    unseen filing broadcast on or after `since`."""
    ids = recent_ids(market, "financials", days=400)
    done = {i.rsplit("-", 1)[1] for i in ids if i.startswith("nse-fin-")}
    latest: dict[str, str] = {}
    for i in ids:
        if i.startswith("nse-fin-"):
            body = i.rsplit("-", 1)[0]
            t = body[len("nse-fin-"):].rsplit("-", 7)[0]     # <ticker>-<basis>-<start yyyy-mm-dd>-<end yyyy-mm-dd>
            latest[t] = max(latest.get(t, ""), body[-10:])
    by_ticker = {t: s for s, t in symbols.items()}
    due = due_tickers(latest, list(by_ticker), today, limit) if since is None else list(by_ticker)
    notes.append(f"financials: {len(due)} ticker(s) polled for quarter {latest_quarter_end(today)}")
    out, ok, total = [], 0, 0
    for ticker in due:
        try:
            idx = rows_of(nse.json("integrated-filing-results", {"index": "equities", "symbol": by_ticker[ticker],
                                                                 "type": "Integrated Filing- Financials"}))
        except FetchError as exc:
            failed.append(exc.entry(f"financials:{ticker}"))
            if exc.host:
                return out, ok
            continue
        ok += 1
        total += len(idx)
        if not idx:
            notes.append(f"financials: no integrated filings listed for {ticker}")
        filings = sorted((r for r in idx if pick(r, "seq_Id") and pick(r, "seq_Id") not in done and pick(r, "xbrl")),
                         key=lambda r: (parse_day(pick(r, "qe_Date")) or date.min, pick(r, "broadcast_Date") or ""),
                         reverse=True)
        if since is not None:
            filings = [r for r in filings if (parse_day(pick(r, "broadcast_Date", "creation_Date")) or date.min) >= since]
        for r in filings[:per_ticker]:
            meta = {"seq": pick(r, "seq_Id"), "xbrl": pick(r, "xbrl"), "consolidated": pick(r, "consolidated"),
                    "audited": pick(r, "audited"), "type_Sub": pick(r, "type_Sub"),
                    "filed_at": iso(parse_ts(pick(r, "broadcast_Date", "creation_Date")))}
            try:
                out += financial_rows(nse.text(meta["xbrl"]), ticker, meta, now)
            except FetchError as exc:
                failed.append(exc.entry(f"financials:{ticker}:{meta['seq']}"))
                if exc.host:
                    return out, ok
    if ok and total == 0:
        coverage(f"financials: {ok} per-ticker index calls", 0, 0, notes, warnings)
    return out, ok


# ---------- flows ----------

def flows(nse: Nse, now: str, notes: list, warnings: list) -> list[dict]:
    out, rows = [], rows_of(nse.json("fiidiiTradeReact"))
    coverage("flows: FII/DII report", len(rows), None, notes, warnings)
    for r in rows:
        day, cat = parse_day(pick(r, "date")), pick(r, "category")
        if day is None or not cat:
            continue
        out.append({"id": f"nse-fiidii-{day}-{re.sub(r'[^a-z]+', '', cat.lower())}", "date": str(day),
                    "category": cat, "buy_cr": parse_nse_number(pick(r, "buyValue")),
                    "sell_cr": parse_nse_number(pick(r, "sellValue")),
                    "net_cr": parse_nse_number(pick(r, "netValue")), "provisional": True, "source": "nse_fiidii",
                    "first_seen_at": now})
    return out


# ---------- delivery ----------

def delivery(nse: Nse, symbols: dict[str, str], today: date, lookback: int, now: str, market: str,
             notes: list, failed: list, warnings: list) -> tuple[list[dict], int]:
    stored = {i.split("-", 2)[2][:10] for i in recent_ids(market, "delivery", days=60) if i.startswith("nse-dlv-")}
    ist_now = datetime.now(IST)
    out, ok = [], 0
    for back in range(lookback, -1, -1):
        d = today - timedelta(days=back)
        if d.weekday() >= 5 or str(d) in stored or (d == ist_now.date() and ist_now.hour < 19):
            continue                   # weekend, already stored, or today's file not published yet
        try:
            text = nse.text(f"/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv")
        except FetchError as exc:
            if exc.host:
                failed.append(exc.entry("delivery"))
                return out, ok
            notes.append(f"delivery: no bhavcopy for {d} ({exc.error[:40]}); holiday or not yet published")
            continue
        ok += 1
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]
        served = {str(parse_day(r.get("DATE1"))) for r in rows if parse_day(r.get("DATE1"))}
        if served and str(d) not in served:     # on a holiday NSE serves the previous session's file
            notes.append(f"delivery: file for {d} holds {', '.join(sorted(served))} (holiday); ids use the file's date")
        matched = 0
        for r in rows:
            ticker = symbols.get(r.get("SYMBOL", "").upper())
            if not ticker or r.get("SERIES") != "EQ":
                continue
            matched += 1
            day = parse_day(r.get("DATE1")) or d
            out.append({"id": f"nse-dlv-{day}-{ticker}", "date": str(day), "ticker": ticker, "series": "EQ",
                        "close": parse_nse_number(r.get("CLOSE_PRICE")),
                        "volume": parse_nse_number(r.get("TTL_TRD_QNTY")),
                        "delivery_qty": parse_nse_number(r.get("DELIV_QTY")),
                        "delivery_pct": parse_nse_number(r.get("DELIV_PER")),
                        "trades": parse_nse_number(r.get("NO_OF_TRADES")),
                        "turnover_lacs": parse_nse_number(r.get("TURNOVER_LACS")),
                        "source": "nse_bhavcopy", "first_seen_at": now})
        coverage(f"delivery: bhavcopy {d}", len(rows), matched, notes, warnings)
    return out, ok


def collect(cfg: dict, nse: Nse, kinds: list[str], today: date | None = None, args=None) -> dict:
    from marketbrief.core.clock import utc_now, utc_today
    market, rel = cfg["market"], cfg.get("relations") or {}
    symbols, today, now = nse_symbols(cfg), today or utc_today(), utc_now()
    full = bool(getattr(args, "full", False))
    limit = None if full else int(rel.get("symbol_calls_per_run", 10))
    per_ticker = None if full else int(rel.get("financial_filings_per_ticker", 4))
    since = getattr(args, "since", None)
    if since is not None:
        limit = per_ticker = None
    new, failed, notes, warnings = {}, [], [], []
    for kind in kinds:
        n_failed = len(failed)
        try:
            if kind == "announcements":
                rows, ok = announcements(nse, symbols, today, int(rel.get("announcement_lookback_days", 2)), now,
                                         notes, warnings, since), 1
            elif kind == "financials":
                rows, ok = financials(nse, symbols, today, now, market, failed, notes, warnings, limit, per_ticker,
                                      since)
            elif kind == "flows":
                rows, ok = flows(nse, now, notes, warnings), 1
            else:
                rows, ok = delivery(nse, symbols, today, int(rel.get("delivery_lookback_days", 5)), now, market,
                                    notes, failed, warnings)
        except FetchError as exc:
            failed.append(exc.entry(kind))
            new[kind] = None
            continue
        if not ok and len(failed) > n_failed:
            new[kind] = None
            continue
        new[kind] = store(market, kind, rows, today)
    return summary_of("nse_india", market, new, failed, notes, nse, warnings)


def extra_args(ap) -> None:
    ap.add_argument("--full", action="store_true",
                    help="poll every ticker missing the latest quarter and parse all its listed filings")
    since_arg(ap)   # announcements by week, and every ticker's results filings broadcast since then


def main() -> int:
    return collector_main(__doc__, "nse_india", KINDS, collect, extra_args)


if __name__ == "__main__":
    sys.exit(main())
