#!/usr/bin/env python3
"""Collect big-investor stakes (SEC Schedule 13D and 13G, incl. amendments) naming watchlist
companies as the issuer into data/<market>/stakes/YYYY/MM/<today>.jsonl, one row per filing:
filer, all reporting persons, percent of class and shares owned (largest reported by any
reporting person, i.e. the group's aggregate), event date, and for 13D the stated purpose.

13D = an active holder over 5% (possible activist); 13G = a passive holder over 5%. Since
December 2024 both are filed as structured XML ("SCHEDULE 13D"/"SCHEDULE 13G"); the older
free-text "SC 13D"/"SC 13G" forms are not parsed. A company's submission list also holds the
13D/13G it filed as an investor in other companies: those are recognised by the issuer CIK in
the document (or a self-filed accession number) and skipped.

Only for markets with `filings: sec`. Settings: relationships.stakes in
config/markets/<market>.yaml (lookback_days, forms). A ticker's filings come from its mapped CIK
plus `fundamentals.predecessor_ciks` (sec.ticker_submissions). Requires SEC_USER_AGENT."""
from __future__ import annotations

import json
import sys
from datetime import timedelta

import sec
from marketbrief.sources.sec_acceptance import time_summary, time_warnings
from marketbrief.sources.sec_client import Edgar, archive_url
from marketbrief.utils.numbers import parse_sec_number
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file, recent_ids

DEFAULT_FORMS = ["SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A"]


def parse_schedule13(data: bytes) -> dict:
    """Schedule 13D or 13G XML -> issuer, reporting persons (name, cik, shares, percent), dates."""
    root = sec.xml_root(data)
    form = sec.text(root, "headerData/submissionType") or ""
    cover = root.find("formData/coverPageHeader")
    persons = []
    if "13D" in form:
        for p in root.findall("formData/reportingPersons/reportingPersonInfo"):
            persons.append({"name": sec.text(p, "reportingPersonName"), "cik": sec.text(p, "reportingPersonCIK"),
                            "shares": parse_sec_number(sec.text(p, "aggregateAmountOwned")),
                            "percent": parse_sec_number(sec.text(p, "percentOfClass"))})
        event = sec.text(cover, "dateOfEvent")
        item4 = root.find("formData/items1To7/item4")
        purpose = " ".join(t.strip() for t in item4.itertext() if t.strip()) if item4 is not None else None
    else:
        for p in root.findall("formData/coverPageHeaderReportingPersonDetails"):
            persons.append({"name": sec.text(p, "reportingPersonName"), "cik": None,
                            "shares": parse_sec_number(sec.text(p,
                            "reportingPersonBeneficiallyOwnedAggregateNumberOfShares")),
                            "percent": parse_sec_number(sec.text(p, "classPercent"))})
        event = sec.text(cover, "eventDateRequiresFilingThisStatement")
        purpose = None
    issuer = cover.find("issuerInfo") if cover is not None else None
    return {"form": form, "kind": "13D" if "13D" in form else "13G", "amendment": form.endswith("/A"),
            "issuer_cik": sec.text(issuer, "issuerCIK") or sec.text(issuer, "issuerCik"),
            "issuer_name": sec.text(issuer, "issuerName"),
            "filer_cik": sec.text(root, "headerData/filerInfo/filer/filerCredentials/cik"),
            "event_date": sec.us_date(event), "persons": persons,
            "purpose": purpose[:600] if purpose else None}


def to_row(f: dict, p: dict, ticker: str, url: str, now: str) -> dict:
    pct = [x["percent"] for x in p["persons"] if x["percent"] is not None]
    shs = [x["shares"] for x in p["persons"] if x["shares"] is not None]
    names = [x["name"] for x in p["persons"] if x["name"]]
    filer_cik = p["filer_cik"] or next((x["cik"] for x in p["persons"] if x["cik"]), None)
    return {"id": f["accession"], "ticker": ticker, "issuer_cik": str(int(p["issuer_cik"])), "form": f["form"],
            "kind": p["kind"], "amendment": p["amendment"], "filing_date": f["filing_date"],
            "accepted_at": f["accepted_at"], "event_date": p["event_date"],
            "filer_name": names[0] if names else None, "filer_cik": str(int(filer_cik)) if filer_cik else None,
            "reporting_persons": names, "percent": max(pct) if pct else None, "shares": max(shs) if shs else None,
            "purpose": p["purpose"], "url": url, "first_seen_at": now}


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg["market"]
    ua = sec.require_sec(cfg, "stakes")
    if ua is None:
        return 0
    rel = cfg.get("relationships", {}).get("stakes", {})
    forms = set(rel.get("forms", DEFAULT_FORMS))
    since = utc_today() - timedelta(days=int(rel.get("lookback_days", 7)))
    seen = recent_ids(market, "stakes", days=120)
    edgar, now = Edgar(ua), utc_now()
    ciks, skipped = sec.watch_ciks(cfg, edgar)
    related = sec.related_ciks(cfg)

    rows, failed, read, as_investor = [], [], 0, 0
    for ticker, cik in ciks.items():
        recent, errors = sec.ticker_submissions(edgar, ticker, cik, related)
        failed += errors
        if recent is None:
            continue
        own = {int(cik), *related.get(ticker.upper(), [])}   # the mapped CIK and its predecessor/related CIKs
        for f in sec.filings(recent, forms, since):
            if f["accession"] in seen:
                continue
            if int(f["accession"].split("-")[0]) in own:   # self-filed: the company as an investor
                as_investor += 1
                continue
            url = archive_url(f["cik"], f["accession"], sec.raw_doc(f["primary_doc"]))
            try:
                parsed = parse_schedule13(edgar.get(url))
            except Exception as exc:
                failed.append({"ticker": ticker, "accession": f["accession"], "error": str(exc)[:200]})
                continue
            read += 1
            seen.add(f["accession"])
            if not parsed["issuer_cik"] or int(parsed["issuer_cik"]) not in own:
                as_investor += 1
                continue
            rows.append(to_row(f, parsed, ticker, url, now))

    written = append_jsonl(day_file(market, "stakes", utc_today()), rows)
    print(json.dumps({
        "collector": "stakes", "market": market, "since": str(since), "filings_read": read,
        "new_rows": written, "new_13d": sum(r["kind"] == "13D" and not r["amendment"] for r in rows),
        "as_investor_skipped": as_investor, "requests": edgar.requests, "sec_times": time_summary(edgar), "warnings": time_warnings(edgar),
        "skipped_not_sec": skipped, "failed": failed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
