#!/usr/bin/env python3
"""Collect quarterly 13F holdings of watchlist tickers from a short list of large institutional
filers (relationships.holdings in config/markets/<market>.yaml: filers by CIK, ticker CUSIPs)
into data/<market>/holdings/YYYY/MM/<today>.jsonl.

One row per (13F filing, ticker[, put/call]): shares, value (USD) and the number of table
lines summed. Every filing also gets a zero row for each watchlist ticker the filer does not
hold, so an exit shows up as a change. The first time a filer is seen its latest `quarters`
filings are loaded, so a quarter-on-quarter change exists from day one.

Cheap to run daily: it uses the network only in the ~50 days after a quarter end while some
filer has not yet filed that quarter (or a filer is new to the config), and then downloads
only 13F filings it has not stored yet; on other days it exits at once.
Original 13F-HR only; amendments (13F-HR/A) are ignored. Information tables (up to ~25 MB for
the largest filers) are stream-parsed. `--force` checks the filers even when up to date.
Only for markets with `filings: sec`. Requires SEC_USER_AGENT."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import date

import sec
from common import append_jsonl, data_dir, day_file, market_arg, require_market, utc_now, utc_today

FILING_WINDOW_DAYS = 50  # 13F deadline is 45 days after quarter end


def quarter_end(d: date) -> date:
    """Latest calendar quarter end strictly before d."""
    q = (d.month - 1) // 3
    return date(d.year - 1, 12, 31) if q == 0 else date(d.year, 3 * q, 30 if q in (2, 3) else 31)


def stored(market: str) -> tuple[set[str], dict[str, str]]:
    """Accessions already stored, and the latest stored period per filer CIK."""
    accs, latest = set(), {}
    for f in (data_dir(market) / "holdings").glob("**/*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                accs.add(r["accession"])
                latest[r["filer_cik"]] = max(latest.get(r["filer_cik"], ""), r["period"])
    return accs, latest


def parse_info_table(stream, cusips: dict[str, str]) -> tuple[dict[tuple[str, str | None], dict], int]:
    """Stream a 13F information table; sum shares/value per (ticker, put/call) for watched
    CUSIPs. Returns (aggregates, number of table lines read)."""
    out: dict[tuple[str, str | None], dict] = {}
    total = 0
    for _, el in ET.iterparse(stream):
        if el.tag.split("}")[-1] != "infoTable":
            continue
        total += 1
        g = {c.tag.split("}")[-1]: c for c in el}
        cusip = (g["cusip"].text or "").strip().upper() if "cusip" in g else ""
        ticker = cusips.get(cusip)
        if ticker:
            amt = {c.tag.split("}")[-1]: (c.text or "").strip() for c in g["shrsOrPrnAmt"]} if "shrsOrPrnAmt" in g else {}
            if amt.get("sshPrnamtType", "SH") == "SH":
                pc = (g["putCall"].text or "").strip().upper() if "putCall" in g else None
                agg = out.setdefault((ticker, pc or None), {"cusip": cusip, "shares": 0.0, "value_usd": 0.0, "n_lines": 0,
                                                            "issuer_name": (g["nameOfIssuer"].text or "").strip()})
                agg["shares"] += sec.num(amt.get("sshPrnamt")) or 0.0
                agg["value_usd"] += sec.num(g["value"].text if "value" in g else None) or 0.0
                agg["n_lines"] += 1
        el.clear()
    return out, total


def filing_docs(edgar: sec.Edgar, cik: int, accession: str) -> tuple[str, bool]:
    """(information table URL, confidential) for a 13F filing. A filing that omits holdings
    under a confidential-treatment request cannot show exits, so it gets no zero rows."""
    items = edgar.json(sec.archive_url(cik, accession, "index.json"))["directory"]["item"]
    xmls = [i for i in items if i["name"].lower().endswith(".xml") and i["name"] != "primary_doc.xml"]
    if not xmls:
        raise ValueError("no information table in filing")
    best = max(xmls, key=lambda i: int(i.get("size") or 0))
    cover = sec.xml_root(edgar.get(sec.archive_url(cik, accession, "primary_doc.xml")))
    confidential = bool(sec.flag(sec.text(cover, "formData/summaryPage/isConfidentialOmitted")))
    return sec.archive_url(cik, accession, best["name"]), confidential


def to_rows(f: dict, cik: int, filer: str, agg: dict, zero_fill: list[str], url: str, now: str) -> list[dict]:
    rows = []
    for t in zero_fill:
        agg.setdefault((t, None), {"cusip": None, "shares": 0.0, "value_usd": 0.0, "n_lines": 0, "issuer_name": None})
    for (t, pc), a in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        rows.append({"id": f"{f['accession']}-{t}" + (f"-{pc}" if pc else ""), "accession": f["accession"],
                     "filer_cik": str(cik), "filer_name": filer, "period": f["report_date"],
                     "filing_date": f["filing_date"], "accepted_at": f["accepted_at"], "ticker": t,
                     "cusip": a["cusip"], "issuer_name": a["issuer_name"], "shares": a["shares"],
                     "value_usd": a["value_usd"], "put_call": pc, "n_lines": a["n_lines"], "url": url,
                     "first_seen_at": now})
    return rows


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--force", action="store_true", help="check the filers even if up to date")
    args = ap.parse_args()
    cfg = require_market(args)
    market = cfg["market"]
    ua = sec.require_sec(cfg, "holdings")
    if ua is None:
        return 0
    rel = cfg.get("relationships", {}).get("holdings", {})
    filers = {int(k): v for k, v in (rel.get("filers") or {}).items()}
    cusips = {}
    for t, cs in (rel.get("cusips") or {}).items():
        for c in [cs] if isinstance(cs, str) else cs:
            cusips[str(c).upper()] = t
    quarters = int(rel.get("quarters", 2))
    if not filers or not cusips:
        print(json.dumps({"collector": "holdings", "market": market, "skipped": "no filers or cusips configured"}))
        return 0

    accs, latest = stored(market)
    qend = quarter_end(utc_today())
    due = str(qend)
    waiting = [n for c, n in filers.items() if latest.get(str(c), "") < due]
    new_filers = [n for c, n in filers.items() if str(c) not in latest]
    # 13F is due 45 days after quarter end: poll only inside that window (plus a few days' slack)
    in_window = (utc_today() - qend).days <= FILING_WINDOW_DAYS
    if not args.force and not new_filers and (not waiting or not in_window):
        reason = f"up to date (quarter {due})" if not waiting else f"no new quarter due (quarter {due} window closed)"
        print(json.dumps({"collector": "holdings", "market": market, "skipped": reason, "not_filed": waiting}))
        return 0

    edgar, now = sec.Edgar(ua), utc_now()
    tickers = sorted(set(cusips.values()))
    rows, loaded, empty, failed = [], [], [], []
    for cik, name in filers.items():
        try:
            hrs = sec.filings(edgar.recent(cik), {"13F-HR"})
        except Exception as exc:
            failed.append({"filer": name, "error": str(exc)[:200]})
            continue
        newest: dict[str, dict] = {}            # latest original filing per period
        for f in hrs:
            if f["report_date"] and f["report_date"] not in newest:
                newest[f["report_date"]] = f
        for period in sorted(newest, reverse=True)[:quarters]:
            f = newest[period]
            if f["accession"] in accs:
                continue
            try:
                url, confidential = filing_docs(edgar, cik, f["accession"])
                with edgar.open(url) as stream:
                    agg, n_lines = parse_info_table(stream, cusips)
            except Exception as exc:
                failed.append({"filer": name, "accession": f["accession"], "error": str(exc)[:200]})
                continue
            if n_lines == 0:                   # nothing disclosed (e.g. all confidential): no signal
                empty.append(f"{name} {period}")
                continue
            rows += to_rows(f, cik, name, agg, [] if confidential else tickers, url, now)
            held = sum(1 for (_, pc), a in agg.items() if pc is None and a["shares"] > 0)
            loaded.append(f"{name} {period}: {held} held" + (" (partly confidential)" if confidential else ""))

    written = append_jsonl(day_file(market, "holdings", utc_today()), rows)
    _, latest = stored(market)
    print(json.dumps({
        "collector": "holdings", "market": market, "quarter_due": due, "filings_loaded": loaded,
        "empty_skipped": empty, "new_rows": written, "requests": edgar.requests,
        "waiting_on": [n for c, n in filers.items() if latest.get(str(c), "") < due], "failed": failed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
