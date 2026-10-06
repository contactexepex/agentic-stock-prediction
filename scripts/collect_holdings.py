#!/usr/bin/env python3
"""Collect quarterly 13F holdings of watchlist tickers from a short list of large institutional
filers (relationships.holdings in config/markets/<market>.yaml: filers by CIK, ticker CUSIPs)
into data/<market>/holdings/YYYY/MM/<today>.jsonl.

Rows per processed filing:
- one filing row (ticker null): report type, table lines, `complete`, and in `note` why the
  filing is incomplete or, for a 13F notice, which manager reports the holdings instead;
- one row per watched (ticker[, put/call]) held: shares, value (USD), table lines summed;
- only for a complete filing, a zero row for each watchlist ticker the filer does not hold,
  so a real exit shows up as a change.
A filing is complete only if it is a 13F HOLDINGS REPORT (not a COMBINATION report, where other
managers report part of the holdings), omits nothing as confidential, has as many table lines
as the cover page's tableEntryTotal, and is not a placeholder table (CUSIP 000000000).
A 13F-NT (notice: "reported by another manager") gets only the filing row and counts as filed.

The first time a filer is seen its latest `quarters` periods are loaded, so a quarter-on-quarter
change exists from day one. Cheap to run daily: it uses the network only in the ~50 days after
a quarter end while some filer has not yet filed that quarter (or a filer is new to the
config), and then downloads only filings it has not stored yet; on other days it exits at once.
Original 13F-HR/13F-NT only; amendments (13F-HR/A) are ignored. Information tables (up to
~25 MB) are stream-parsed. `--force` checks the filers even when up to date.
Only for markets with `filings: sec`. Requires SEC_USER_AGENT."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import date

import sec
from common import append_jsonl, data_dir, day_file, market_arg, require_market, utc_now, utc_today

FILING_WINDOW_DAYS = 50  # 13F deadline is 45 days after quarter end
PLACEHOLDER_CUSIP = "000000000"


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


def parse_cover(data: bytes) -> dict:
    """13F cover page (primary_doc.xml of a 13F-HR or 13F-NT)."""
    root = sec.xml_root(data)
    total = sec.num(sec.text(root, "formData/summaryPage/tableEntryTotal"))
    return {"report_type": (sec.text(root, "formData/coverPage/reportType") or "").upper(),
            "entry_total": int(total) if total is not None else None,
            "confidential": bool(sec.flag(sec.text(root, "formData/summaryPage/isConfidentialOmitted"))),
            "other_managers": [sec.text(m, "name") for m in root.findall("formData/coverPage/otherManagersInfo/otherManager")
                               if sec.text(m, "name")]}


def parse_info_table(stream, cusips: dict[str, str]) -> tuple[dict[tuple[str, str | None], dict], int, bool]:
    """Stream a 13F information table; sum shares/value per (ticker, put/call) for watched
    CUSIPs. Returns (aggregates, number of table lines, placeholder line seen)."""
    out: dict[tuple[str, str | None], dict] = {}
    total, placeholder = 0, False
    for _, el in ET.iterparse(stream):
        if el.tag.split("}")[-1] != "infoTable":
            continue
        total += 1
        g = {c.tag.split("}")[-1]: c for c in el}
        cusip = (g["cusip"].text or "").strip().upper() if "cusip" in g else ""
        placeholder |= cusip.strip("0") == ""
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
    return out, total, placeholder


def incomplete_reason(cover: dict, n_lines: int, placeholder: bool) -> str | None:
    """Why a filing cannot show exits (None = complete: zero rows may be written)."""
    if cover["report_type"] != "13F HOLDINGS REPORT":
        return f"{cover['report_type'] or 'unknown report type'}: other managers report part of the holdings"
    if cover["confidential"]:
        return "holdings omitted as confidential"
    if placeholder:
        return "placeholder table (CUSIP 000000000)"
    if cover["entry_total"] is not None and cover["entry_total"] != n_lines:
        return f"table has {n_lines} of {cover['entry_total']} lines"
    return None


def info_table_url(edgar: sec.Edgar, cik: int, accession: str) -> str:
    items = edgar.json(sec.archive_url(cik, accession, "index.json"))["directory"]["item"]
    xmls = [i for i in items if i["name"].lower().endswith(".xml") and i["name"] != "primary_doc.xml"]
    if not xmls:
        raise ValueError("no information table in filing")
    best = max(xmls, key=lambda i: int(i.get("size") or 0))
    return sec.archive_url(cik, accession, best["name"])


def base_row(f: dict, cik: int, filer: str, url: str, now: str) -> dict:
    return {"accession": f["accession"], "filer_cik": str(cik), "filer_name": filer, "period": f["report_date"],
            "filing_date": f["filing_date"], "accepted_at": f["accepted_at"], "url": url, "first_seen_at": now}


def filing_row(f: dict, cik: int, filer: str, url: str, now: str, report_type: str, n_lines: int | None,
               complete: bool, note: str | None) -> dict:
    return {"id": f"{f['accession']}-FILING", **base_row(f, cik, filer, url, now), "ticker": None, "cusip": None,
            "issuer_name": None, "shares": None, "value_usd": None, "put_call": None, "n_lines": n_lines,
            "report_type": report_type, "complete": complete, "note": note}


def to_rows(f: dict, cik: int, filer: str, agg: dict, zero_fill: list[str], url: str, now: str,
            report_type: str, complete: bool) -> list[dict]:
    rows = []
    for t in zero_fill:
        agg.setdefault((t, None), {"cusip": None, "shares": 0.0, "value_usd": 0.0, "n_lines": 0, "issuer_name": None})
    for (t, pc), a in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        rows.append({"id": f"{f['accession']}-{t}" + (f"-{pc}" if pc else ""), **base_row(f, cik, filer, url, now),
                     "ticker": t, "cusip": a["cusip"], "issuer_name": a["issuer_name"], "shares": a["shares"],
                     "value_usd": a["value_usd"], "put_call": pc, "n_lines": a["n_lines"],
                     "report_type": report_type, "complete": complete, "note": None})
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
    rows, loaded, notices, failed = [], [], [], []
    for cik, name in filers.items():
        try:
            found = sec.filings(edgar.recent(cik), {"13F-HR", "13F-NT"})
        except Exception as exc:
            failed.append({"filer": name, "error": str(exc)[:200]})
            continue
        newest: dict[str, dict] = {}            # latest original filing per period; a report beats a notice
        for f in found:
            p = f["report_date"]
            if p and (p not in newest or (newest[p]["form"] == "13F-NT" and f["form"] == "13F-HR")):
                newest[p] = f
        for period in sorted(newest, reverse=True)[:quarters]:
            f = newest[period]
            if f["accession"] in accs:
                continue
            try:
                cover_url = sec.archive_url(cik, f["accession"], "primary_doc.xml")
                cover = parse_cover(edgar.get(cover_url))
                if f["form"] == "13F-NT":
                    by = "; ".join(cover["other_managers"]) or "unnamed manager"
                    rows.append(filing_row(f, cik, name, cover_url, now, "13F NOTICE", None, False, f"reported by {by}"))
                    notices.append(f"{name} {period}: reported by {by}")
                    continue
                url = info_table_url(edgar, cik, f["accession"])
                with edgar.open(url) as stream:
                    agg, n_lines, placeholder = parse_info_table(stream, cusips)
            except Exception as exc:
                failed.append({"filer": name, "accession": f["accession"], "error": str(exc)[:200]})
                continue
            why = incomplete_reason(cover, n_lines, placeholder)
            rows.append(filing_row(f, cik, name, url, now, cover["report_type"], n_lines, why is None, why))
            rows += to_rows(f, cik, name, agg, tickers if why is None else [], url, now, cover["report_type"], why is None)
            held = sum(1 for (_, pc), a in agg.items() if pc is None and a["shares"] > 0)
            loaded.append(f"{name} {period}: {held} held" + (f" (incomplete: {why})" if why else ""))

    written = append_jsonl(day_file(market, "holdings", utc_today()), rows)
    _, latest = stored(market)
    print(json.dumps({
        "collector": "holdings", "market": market, "quarter_due": due, "filings_loaded": loaded,
        "reported_by_other_manager": notices, "new_rows": written, "requests": edgar.requests, "sec_times": sec.time_summary(edgar),
        "waiting_on": [n for c, n in filers.items() if latest.get(str(c), "") < due], "failed": failed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
