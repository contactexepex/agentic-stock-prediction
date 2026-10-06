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
for SEC markets with SEC_USER_AGENT set, 8-K item 2.02 (results of operations) acceptance times;
for SEC markets each 10-Q/10-K acceptance is also stored, as a `periodic_report` row with its
`period_end`. Not every 2.02 is a quarter's results release (Tesla's quarterly delivery reports,
pre-announcements, guidance updates): every 2.02 is stored as it was filed, and
range_inputs.results_filter keeps one release per quarter when the dates are read, using only
the reports accepted by the as-of date (so the walk-forward backtest never looks ahead); a
past yfinance date within 45 days of a release that a 10-Q/10-K confirms loses to it (new report
rows are counted as `sec_reports` in the summary). NSE markets (`relations.source: nse`) take
earnings dates from NSE results filings (see nse_earnings), polled only for tickers that are due
(see nse_due). Tickers whose SEC submissions or NSE requests fail are
listed in the summary (`sec_failed`, `nse_failed`; a failed SEC step as a whole in `sec_error`).

yfinance hides most request errors behind empty answers, so `failed` lists the Yahoo gaps (with
`what`): `calendar` (an error or an empty calendar), `dividends` (an error, or no dividends
although some are stored for the ticker or its calendar lists an ex-dividend date in the backfill
window) and `earnings_history` (both yfinance methods raised). The earnings-calendar page
(finance.yahoo.com) is tried first; if it fails (e.g. a network that refuses the host) the
screener fallback (query1) supplies the dates. `earnings_history_sources` counts which method was
used."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import events as ev
from common import append_jsonl, data_dir, day_file, market_arg, require_market, utc_now, utc_today
from nse import IST, FetchError, Nse, nse_symbols, parse_day, parse_ts, pick, rows_of
from sec import time_warnings

FIELDS = {"Earnings Date": "earnings", "Ex-Dividend Date": "ex_dividend"}
NEAR_DAYS = 3  # earnings dates this close together are the same report
# NSE announcement categories that carry a results release (the PDF filed after the board meeting)
RESULTS_ANNOUNCEMENTS = ("Outcome of Board Meeting", "Financial Result Updates", "Integrated Filing- Financial")
RELEASE_WINDOW = timedelta(hours=36)  # such an announcement this long before the first XBRL filing = its release
NSE_STALE_DAYS = 100  # poll a ticker with NSE results again when its newest past earnings date is this old
QUARTER_GAP_DAYS = 120  # consecutive quarterly results are at most this far apart (45/60-day deadlines)
REPORT_FORMS = ("10-Q", "10-K")  # periodic reports (not amendments) that date each quarter's results release


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


def yf_earnings(cfg: dict, tk, limit: int = 40) -> tuple[list[tuple[date, str | None, int]], str | None, list[str]]:
    """Past earnings (date, timing, priority) from yfinance: the earnings-calendar page
    (finance.yahoo.com), else the screener endpoint (query1). Report rows beat earnings-call rows
    (a call only times the release if it is before the open). The third value lists each
    method's error ("<method>: <error>") when every method tried raised, so nothing was learnt;
    a method that answers with no rows is a real "no earnings dates", not an error."""
    df, used, errors, answered = None, None, [], False
    for fn in ("get_earnings_dates", "_get_earnings_dates_using_screener"):
        f = getattr(tk, fn, None)
        if f is None:
            continue
        try:
            df = f(limit=limit)
            answered = True
        except Exception as exc:
            df = None
            errors.append(f"{fn.strip('_')}: {str(exc)[:120]}")
        if df is not None and not df.empty:
            used = fn.strip("_")
            break
    if df is None or df.empty:
        return [], None, ([] if answered else errors)
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
    return out, used, []


def dividends_expected(cal: dict | None, n_stored: int, since: date) -> str | None:
    """Why this ticker should have dividends in the backfill window (some are stored for it, or
    Yahoo's calendar lists an ex-dividend date inside the window), or None."""
    if n_stored:
        return f"{n_stored} stored"
    listed = [d for d in as_dates((cal or {}).get("Ex-Dividend Date")) if d >= since]
    return f"calendar lists ex-dividend {max(listed)}" if listed else None


def sec_earnings(cfg: dict, tickers: dict, ua: str, reports: dict | None = None, times: dict | None = None
                 ) -> tuple[dict[str, list[tuple[date, str | None, int]]], list[dict]]:
    """Item 2.02 filings from SEC EDGAR: 8-K/6-K filings with item 2.02 (results of operations),
    timed by acceptance. Not every one is a quarter's results release (Tesla's delivery reports,
    pre-announcements, guidance updates also use 2.02): range_inputs.results_filter keeps one per
    quarter when the dates are read, using the 10-Q/10-K reports. Given a dict, `reports`
    receives those per ticker: (acceptance date, timing, form, period end). Acceptance times are
    the checked/corrected ones of sec.Edgar.recent; given a dict, `times` receives the summary of
    those checks (sec.time_summary).
    Each ticker's filings are those of its mapped CIK plus the predecessor/related CIKs in
    `fundamentals.predecessor_ciks` (sec.ticker_submissions), each filing once.
    Returns (rows per ticker, one entry per ticker and CIK whose submissions request failed)."""
    # shared SEC client: one throttle, backoff on 429/503, test fixtures; a ticker's submissions
    # are those of its mapped CIK plus its predecessor/related CIKs, de-duplicated by accession
    from sec import Edgar, related_ciks, ticker_submissions, time_summary

    edgar = Edgar(ua)
    cik_by_ticker = edgar.cik_map()
    related = related_ciks(cfg)
    out: dict[str, list] = {}
    failed: list[dict] = []
    for key, meta in tickers.items():
        cik = cik_by_ticker.get(meta.get("sec_ticker", key).upper())
        if cik is None:
            continue
        recent, errors = ticker_submissions(edgar, key, cik, related)
        failed += errors
        if recent is None:
            continue
        n = len(recent["form"])
        items = recent.get("items") or [""] * n
        period = recent.get("reportDate") or [None] * n
        for i, form in enumerate(recent["form"]):
            if not recent["acceptanceDateTime"][i]:
                continue
            if form in ("8-K", "6-K") and "2.02" in (items[i] or ""):
                d, tm = timing(cfg, pd.Timestamp(recent["acceptanceDateTime"][i]))
                out.setdefault(key, []).append((d, tm, 0))
            elif form in REPORT_FORMS and reports is not None:
                d, tm = timing(cfg, pd.Timestamp(recent["acceptanceDateTime"][i]))
                pe = date.fromisoformat(period[i][:10]) if period[i] else None
                reports.setdefault(key, []).append((d, tm, form, pe))
    if times is not None:
        times.update(time_summary(edgar))
    return out, failed


# ---------- NSE (India): results filings ----------

def max_filing_lag(period_end: date) -> int:
    """SEBI LODR regulation 33: quarterly results within 45 days of the quarter end, the annual
    (March quarter) results within 60. A first filing later than that (plus 3 days' grace) is a
    late XBRL upload, not the release, so its date is not used."""
    return 63 if period_end.month == 3 else 48


def nse_results_filings(nse: Nse, symbol: str, backfill: bool) -> tuple[list[tuple[date, datetime]], list[str]]:
    """(period end, broadcast time UTC) of each results filing NSE lists for a symbol: SEBI
    Integrated Filing (Financials), used from the March 2025 quarter on, and, when backfilling,
    the older financial-results list (quarters to December 2024). Returns (filings, notes)."""
    notes = []
    payload = nse.json("integrated-filing-results", {"index": "equities", "symbol": symbol,
                                                     "type": "Integrated Filing- Financials"})
    rows = rows_of(payload)
    total = payload.get("totalCount") if isinstance(payload, dict) else None
    if isinstance(total, int) and total > len(rows):
        notes.append(f"{symbol}: integrated filings list {len(rows)} of {total} rows")
    out = [(parse_day(pick(r, "qe_Date")), parse_ts(pick(r, "broadcast_Date", "creation_Date"))) for r in rows]
    if backfill:
        rows = rows_of(nse.json("corporates-financial-results", {"index": "equities", "period": "Quarterly",
                                                               "symbol": symbol}))
        out += [(parse_day(pick(r, "toDate")), parse_ts(pick(r, "broadCastDate", "exchdisstime", "filingDate")))
                for r in rows]
    return [(pe, ts) for pe, ts in out if pe and ts], notes


def nse_release_times(nse: Nse, symbol: str, start: date, today: date) -> list[datetime]:
    """Times (UTC) of the symbol's results-type announcements (board meeting outcome, results
    PDF) from start to today: the first public release, usually before the XBRL filing."""
    rows = rows_of(nse.json("corporate-announcements", {"index": "equities", "symbol": symbol,
                                                      "from_date": f"{start:%d-%m-%Y}",
                                                      "to_date": f"{today:%d-%m-%Y}"}))
    return [ts for r in rows if pick(r, "desc") in RESULTS_ANNOUNCEMENTS
            and (ts := parse_ts(pick(r, "an_dt", "exchdisstime", "sort_date")))]


def nse_reports(cfg: dict, filings: list[tuple[date, datetime]], releases: list[datetime],
                after: date | None = None) -> tuple[list[tuple[date, str | None, int]], int]:
    """One (date, timing, priority 0) per reported quarter: the earliest filing for the period
    end (standalone or consolidated, original or revised), moved earlier to a results
    announcement up to RELEASE_WINDOW before it. Only quarters first filed after `after` (IST).
    Returns (rows, quarters dropped because their first filing came after the SEBI deadline)."""
    first: dict[date, datetime] = {}
    for pe, ts in filings:
        first[pe] = min(first.get(pe, ts), ts)
    out, late = [], 0
    for pe, ts in sorted(first.items()):
        filed = ts.astimezone(IST).date()
        if after is not None and filed <= after:
            continue
        if not 0 < (filed - pe).days <= max_filing_lag(pe):
            late += 1
            continue
        release = min([a for a in releases if ts - RELEASE_WINDOW <= a <= ts] + [ts])
        d, tm = timing(cfg, pd.Timestamp(release))
        out.append((d, tm, 0))
    return out, late


def nse_due(stored: list[dict], tickers: list[str], today: date) -> dict[str, date | None]:
    """Tickers to poll -> newest stored past earnings date (a `_history` row of any source), or
    None = no NSE results stored yet: backfill (retried on the next run if it fails). A ticker
    with NSE results is due when an upcoming earnings date stored earlier has passed since its
    newest past date, or when that date is NSE_STALE_DAYS old. Otherwise it is not polled, so a
    quiet day costs no NSE calls."""
    last: dict[str, date] = {}
    has_nse: set[str] = set()
    known: dict[str, list[date]] = {}
    for r in stored:
        if r.get("type") != "earnings" or r.get("ticker") not in tickers:
            continue
        d = date.fromisoformat(str(r["date"])[:10])
        known.setdefault(r["ticker"], []).append(d)
        if str(r.get("source", "")).endswith("_history"):
            last[r["ticker"]] = max(last.get(r["ticker"], d), d)
        if r.get("source") == "nse_history":
            has_nse.add(r["ticker"])
    due: dict[str, date | None] = {}
    for t in tickers:
        if t not in has_nse:
            due[t] = None
        elif (today - last[t]).days >= NSE_STALE_DAYS or any(
                last[t] + timedelta(days=NEAR_DAYS) < d <= today for d in known.get(t, [])):
            due[t] = last[t]
    return due


def nse_earnings(cfg: dict, nse: Nse, due: dict[str, date | None], since: date,
                 today: date) -> tuple[dict[str, list[tuple[date, str | None, int]]], list[dict], list[str]]:
    """Past results releases from NSE for the due tickers (see nse_due), dated and timed by the
    results filings and refined by the results announcements. A backfill reaches back to
    `since`; a ticker with stored history only takes quarters filed more than NEAR_DAYS after
    its newest stored date. Returns (rows per ticker, failures, notes); a host the
    egress proxy refuses stops the remaining calls."""
    symbol_of = {t: s for s, t in nse_symbols(cfg).items()}
    out: dict[str, list] = {}
    failed: list[dict] = []
    notes: list[str] = []
    for ticker, last in due.items():
        symbol = symbol_of[ticker]
        after = None if last is None else last + timedelta(days=NEAR_DAYS)
        try:
            filings, n = nse_results_filings(nse, symbol, backfill=last is None)
            notes += n
            filings = [(pe, ts) for pe, ts in filings if ts.astimezone(IST).date() >= since]
            new = [ts for _, ts in filings if after is None or ts.astimezone(IST).date() > after]
            releases = nse_release_times(nse, symbol, min(new).astimezone(IST).date() - timedelta(days=2),
                                         today) if new else []
            rows, late = nse_reports(cfg, filings, releases, after)
        except FetchError as exc:
            failed.append(exc.entry(f"nse_earnings:{ticker}"))
            if exc.host:
                break
            continue
        if late:
            notes.append(f"{ticker}: {late} quarter(s) first filed after the SEBI deadline, not used")
        if rows:
            out[ticker] = rows
    return out, failed, notes


def between_quarters(d: date, nse_dates: list[date]) -> bool:
    """Is d between two consecutive NSE results dates at most QUARTER_GAP_DAYS apart? Then the
    filings list that quarter and d adds nothing (a later gap, e.g. a quarter whose first filing
    missed the SEBI deadline, is left for other sources to fill)."""
    before = max((x for x in nse_dates if x <= d), default=None)
    after = min((x for x in nse_dates if x >= d), default=None)
    return before is not None and after is not None and (after - before).days <= QUARTER_GAP_DAYS


def nse_client(cfg: dict) -> Nse:
    """One NSE session for the run (scripts/nse.py), paced as the market config says."""
    rel = cfg.get("relations") or {}
    return Nse(rel.get("base", "https://www.nseindia.com"), rel.get("archives", "https://nsearchives.nseindia.com"),
               pause=float(rel.get("pause_seconds", 0.7)))


def merge_near(cands: list[tuple[date, str | None, int]]) -> list[tuple[date, str | None, int]]:
    """One row per report: best source first (SEC or NSE filings, then yfinance report, then call)."""
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
    nse_dates: dict[str, list[date]] = {}
    n_divs: dict[str, int] = {}
    for r in stored:
        if r.get("type") == "earnings" and str(r.get("source", "")).endswith("_history"):
            hist_earn.setdefault(r["ticker"], []).append(date.fromisoformat(str(r["date"])[:10]))
            if r.get("source") == "nse_history":
                nse_dates.setdefault(r["ticker"], []).append(date.fromisoformat(str(r["date"])[:10]))
        if r.get("type") == "ex_dividend":
            n_divs[r["ticker"]] = n_divs.get(r["ticker"], 0) + 1

    sec: dict[str, list] = {}
    sec_reports: dict[str, list] = {}
    sec_error, sec_failed, sec_times = None, [], {}
    ua = os.environ.get("SEC_USER_AGENT")
    if not args.no_history and cfg.get("filings") == "sec" and ua:
        try:
            sec, sec_failed = sec_earnings(cfg, cfg["tickers"], ua, sec_reports, sec_times)
        except Exception as exc:
            sec_error = str(exc)[:200]

    nse: dict[str, list] = {}
    nse_info: dict = {}
    if not args.no_history and (cfg.get("relations") or {}).get("source") == "nse":
        due = nse_due(stored, list(cfg["tickers"]), today)
        nse_info = {"nse_polled": len(due), "nse_backfill": sum(v is None for v in due.values()),
                    "nse_failed": [], "nse_notes": []}
        if due:
            client = nse_client(cfg)
            nse, nse_info["nse_failed"], nse_info["nse_notes"] = nse_earnings(cfg, client, due, since, today)
            nse_info["nse_requests"] = client.requests
        nse_info["nse_tickers"] = len(nse)
    primary = "nse_history" if nse_info else "sec_history"   # the filings source (priority 0) of this market

    rows, failed, hist = [], [], {"earnings": 0, "ex_dividend": 0}
    earn_sources: dict[str, int] = {}

    def add(key, meta, etype, d, source, amount=None, tm=None, note="", extra=None):
        eid = f"{key}-{etype}-{d}"
        if eid in seen:
            return False
        name = {"earnings": "earnings", "ex_dividend": "ex-dividend"}.get(etype, etype.replace("_", " "))
        rows.append({"id": eid, "date": d.isoformat(), "type": etype, "ticker": key,
                     "name": f"{meta['name']} {name}{note}", "source": source, "first_seen_at": now,
                     "amount": amount, "timing": tm, **(extra or {})})
        seen.add(eid)
        return True

    # SEC 10-Q/10-K acceptances with their period end: range_inputs.results_filter picks each
    # quarter's results release among the 2.02 rows by them. Same window as the 2.02 rows.
    n_reports = 0
    for key, reps in sec_reports.items():
        for d, tm, form, pe in sorted(reps, key=lambda x: x[0]):
            if since <= d < today and add(key, cfg["tickers"][key], "periodic_report", d, "sec_history", tm=tm,
                                          note=f" ({form}, period {pe})",
                                          extra={"period_end": pe.isoformat() if pe else None}):
                n_reports += 1

    for key, meta in cfg["tickers"].items():
        tk = yf.Ticker(meta["yahoo"])
        try:
            cal = tk.calendar or {}
            if not cal:   # yfinance answers a failed request with {}; a listed stock has an earnings entry
                failed.append({"ticker": key, "what": "calendar", "error": "empty calendar"})
        except Exception as exc:
            failed.append({"ticker": key, "what": "calendar", "error": str(exc)[:200]})
            cal = None
        try:   # yfinance answers a failed price-history request with an empty series
            divs = tk.dividends
            divs = {ts.date(): round(float(a), 6) for ts, a in divs.items()} if divs is not None else {}
            why = None if divs else dividends_expected(cal, n_divs.get(key, 0), since)
            if why:
                failed.append({"ticker": key, "what": "dividends", "error": f"no dividends returned ({why})"})
        except Exception as exc:
            divs = {}
            failed.append({"ticker": key, "what": "dividends", "error": str(exc)[:200]})
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
        yfe, used, yf_errors = yf_earnings(cfg, tk)
        if used:
            earn_sources[used] = earn_sources.get(used, 0) + 1
        if yf_errors:
            failed.append({"ticker": key, "what": "earnings_history", "error": "; ".join(yf_errors)})
        # a yfinance date between two NSE results dates a quarter apart is either the same report
        # or not a results release (no quarter is missing there)
        known_nse = nse_dates.get(key, []) + [d for d, _, _ in nse.get(key, [])]
        yfe = [c for c in yfe if not between_quarters(c[0], known_nse)]
        for d, tm, prio in merge_near(sec.get(key, []) + nse.get(key, []) + yfe):
            if not (since <= d < today):
                continue
            if any(abs((d - k).days) <= NEAR_DAYS for k in hist_earn.get(key, [])):
                continue
            src = primary if prio == 0 else "yfinance_history"
            if add(key, meta, "earnings", d, src, tm=tm):
                hist["earnings"] += 1
                hist_earn.setdefault(key, []).append(d)

    written = append_jsonl(day_file(market, "events", today), rows)
    print(json.dumps({"collector": "events", "market": market, "new_events": written - sum(hist.values()) - n_reports,
                      "new_history": hist, "earnings_history_sources": earn_sources,
                      "sec_tickers": len(sec), "sec_reports": n_reports, "sec_error": sec_error, "sec_failed": sec_failed, **({"sec_times": sec_times, "warnings": time_warnings(sec_times)} if sec_times else {}), **nse_info,
                      "failed": failed}, indent=2))
    # exit 1 only when Yahoo's calendar failed for every ticker (several `failed` entries per ticker)
    no_calendar = {f["ticker"] for f in failed if f["what"] == "calendar"}
    return 1 if no_calendar and len(no_calendar) == len(cfg["tickers"]) else 0


if __name__ == "__main__":
    sys.exit(main())
