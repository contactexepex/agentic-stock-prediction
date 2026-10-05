#!/usr/bin/env python3
"""Collect company events (earnings, ex-dividend) for watchlist tickers via yfinance
into data/<market>/events/YYYY/MM/<today>.jsonl. Append-only: an event id
(<ticker>-<type>-<date>) is written once; a moved date is a new event id, and the newest
first_seen_at wins when reading (see the `company_events` view).

Upcoming events come from the yfinance calendar; an ex-dividend row carries the dividend
`amount` (the announced one if Yahoo lists it, else the last dividend paid, marked "est.").
Unless --no-history, past events are backfilled for the range engine (source ending in
"_history", read through the `event_history` view): dividends with amounts, and earnings
dates with `timing` (before_open / during / after_close) from yfinance's earnings dates and,
for SEC markets with SEC_USER_AGENT set, 8-K item 2.02 (results) acceptance times."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import events as ev
from common import append_jsonl, data_dir, day_file, market_arg, require_market, utc_now, utc_today

FIELDS = {"Earnings Date": "earnings", "Ex-Dividend Date": "ex_dividend"}
NEAR_DAYS = 3  # earnings dates this close together are the same report


def as_dates(value) -> list[date]:
    values = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for v in values:
        if isinstance(v, datetime):
            out.append(v.date())
        elif isinstance(v, date):
            out.append(v)
        elif hasattr(v, "date"):
            out.append(v.date())
    return out


def stored_events(market: str) -> list[dict]:
    """Rows of every stored event file (for de-duplication). All files, not a recent window:
    the backfill reaches years back, so a window would let old history ids be written again."""
    rows = []
    for f in sorted((data_dir(market) / "events").glob("**/*.jsonl")):
        rows += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def timing(cfg: dict, ts) -> tuple[date, str | None]:
    """Local date of a timestamp and whether it falls before the open, during or after the close."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.date(), None
    local = ts.tz_convert(ZoneInfo(cfg["timezone"]))
    d = local.date()
    try:
        cal = ev._xcal(cfg["calendar"])
        if not cal.is_session(d.isoformat()):
            return d, "before_open"           # weekend/holiday: first reaction is the next session
        open_, close = cal.session_open(d.isoformat()), cal.session_close(d.isoformat())
    except Exception:
        return d, None
    t = ts.tz_convert("UTC")
    return d, "before_open" if t < open_ else ("after_close" if t >= close else "during")


def yf_earnings(cfg: dict, tk, limit: int = 40) -> tuple[list[tuple[date, str | None, int]], str | None]:
    """Past earnings (date, timing, priority) from yfinance: the earnings-calendar page, else the
    screener endpoint. Report rows beat earnings-call rows (a call only times the release if
    it is before the open)."""
    df, used = None, None
    for fn in ("get_earnings_dates", "_get_earnings_dates_using_screener"):
        f = getattr(tk, fn, None)
        if f is None:
            continue
        try:
            df = f(limit=limit)
        except Exception:
            df = None
        if df is not None and not df.empty:
            used = fn.strip("_")
            break
    if df is None or df.empty:
        return [], None
    kinds = df["Event Type"] if "Event Type" in df.columns else pd.Series("Earnings", index=df.index)
    out = []
    for ts, kind in zip(df.index, kinds):
        if kind not in ("Earnings", "Call"):
            continue
        d, tm = timing(cfg, ts)
        if kind == "Call":
            out.append((d, tm if tm == "before_open" else None, 2))
        else:
            out.append((d, tm, 1))
    return out, used


def sec_earnings(cfg: dict, tickers: dict, ua: str) -> dict[str, list[tuple[date, str | None, int]]]:
    """Past results releases from SEC EDGAR: 8-K filings with item 2.02, timed by acceptance."""
    from sec import Edgar  # shared SEC client: one throttle, backoff on 429/503, test fixtures

    edgar = Edgar(ua)
    cik_by_ticker = edgar.cik_map()
    out: dict[str, list] = {}
    for key, meta in tickers.items():
        cik = cik_by_ticker.get(meta.get("sec_ticker", key).upper())
        if cik is None:
            continue
        try:
            recent = edgar.recent(cik)
        except Exception:
            continue
        items = recent.get("items") or [""] * len(recent["form"])
        for i, form in enumerate(recent["form"]):
            if form in ("8-K", "6-K") and "2.02" in (items[i] or "") and recent["acceptanceDateTime"][i]:
                d, tm = timing(cfg, pd.Timestamp(recent["acceptanceDateTime"][i]))
                out.setdefault(key, []).append((d, tm, 0))
    return out


def merge_near(cands: list[tuple[date, str | None, int]]) -> list[tuple[date, str | None, int]]:
    """One row per report: best source first (SEC, then yfinance report, then call)."""
    kept: list[tuple[date, str | None, int]] = []
    for c in sorted(cands, key=lambda x: (x[2], x[0])):
        if all(abs((c[0] - k[0]).days) > NEAR_DAYS for k in kept):
            kept.append(c)
    return kept


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--no-history", action="store_true", help="skip the past earnings/dividend backfill")
    ap.add_argument("--history-days", type=int, default=1100, help="how far back to backfill (default 1100)")
    args = ap.parse_args()
    cfg = require_market(args)
    import yfinance as yf

    market, now, today = cfg["market"], utc_now(), utc_today()
    since = today - timedelta(days=args.history_days)
    stored = stored_events(market)
    seen = {r["id"] for r in stored}
    hist_earn: dict[str, list[date]] = {}
    for r in stored:
        if r.get("type") == "earnings" and str(r.get("source", "")).endswith("_history"):
            hist_earn.setdefault(r["ticker"], []).append(date.fromisoformat(str(r["date"])[:10]))

    sec: dict[str, list] = {}
    sec_error = None
    ua = os.environ.get("SEC_USER_AGENT")
    if not args.no_history and cfg.get("filings") == "sec" and ua:
        try:
            sec = sec_earnings(cfg, cfg["tickers"], ua)
        except Exception as exc:
            sec_error = str(exc)[:200]

    rows, failed, hist = [], [], {"earnings": 0, "ex_dividend": 0}
    earn_sources: dict[str, int] = {}

    def add(key, meta, etype, d, source, amount=None, tm=None, note=""):
        eid = f"{key}-{etype}-{d}"
        if eid in seen:
            return False
        name = "earnings" if etype == "earnings" else "ex-dividend"
        rows.append({"id": eid, "date": d.isoformat(), "type": etype, "ticker": key,
                     "name": f"{meta['name']} {name}{note}", "source": source, "first_seen_at": now,
                     "amount": amount, "timing": tm})
        seen.add(eid)
        return True

    for key, meta in cfg["tickers"].items():
        tk = yf.Ticker(meta["yahoo"])
        try:
            cal = tk.calendar or {}
        except Exception as exc:
            failed.append({"ticker": key, "error": str(exc)[:200]})
            cal = None
        try:
            divs = tk.dividends
            divs = {ts.date(): round(float(a), 6) for ts, a in divs.items()} if divs is not None else {}
        except Exception:
            divs = {}
        last_div = divs[max(divs)] if divs else None

        # upcoming events (calendar), with the dividend amount
        for field, etype in FIELDS.items():
            for d in as_dates((cal or {}).get(field)):
                if d < today:
                    continue
                if etype == "ex_dividend":
                    amt = divs.get(d, last_div)
                    note = "" if d in divs or amt is None else f" (est. {amt:g}, last dividend)"
                    add(key, meta, etype, d, "yfinance", amount=amt, note=note)
                else:
                    add(key, meta, etype, d, "yfinance")
        if args.no_history:
            continue

        # dividends: announced ones are upcoming events, past ones are history
        for d, amt in sorted(divs.items()):
            if d >= today:
                add(key, meta, "ex_dividend", d, "yfinance", amount=amt)
            elif d >= since and add(key, meta, "ex_dividend", d, "yfinance_history", amount=amt):
                hist["ex_dividend"] += 1

        # past earnings days, timed where the source has a time
        yfe, used = yf_earnings(cfg, tk)
        if used:
            earn_sources[used] = earn_sources.get(used, 0) + 1
        for d, tm, prio in merge_near(sec.get(key, []) + yfe):
            if not (since <= d < today):
                continue
            if any(abs((d - k).days) <= NEAR_DAYS for k in hist_earn.get(key, [])):
                continue
            src = "sec_history" if prio == 0 else "yfinance_history"
            if add(key, meta, "earnings", d, src, tm=tm):
                hist["earnings"] += 1
                hist_earn.setdefault(key, []).append(d)

    written = append_jsonl(day_file(market, "events", today), rows)
    print(json.dumps({"collector": "events", "market": market, "new_events": written - sum(hist.values()),
                      "new_history": hist, "earnings_history_sources": earn_sources,
                      "sec_tickers": len(sec), "sec_error": sec_error, "failed": failed}, indent=2))
    return 1 if failed and len(failed) == len(cfg["tickers"]) else 0


if __name__ == "__main__":
    sys.exit(main())
