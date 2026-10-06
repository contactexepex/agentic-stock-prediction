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
plus `fundamentals.predecessor_ciks` (sec_filings.ticker_submissions). Requires SEC_USER_AGENT."""

from __future__ import annotations

import json
from datetime import timedelta

from marketbrief.constants.columns import COL_ACCESSION, COL_ID, COL_TICKER
from marketbrief.constants.config_keys import CFG_MARKET
from marketbrief.constants.kinds import KIND_STAKES
from marketbrief.constants.sec_collection import (
    AMENDMENT_SUFFIX,
    CFG_RELATIONSHIPS,
    COLLECTOR_STAKES,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_STAKE_FORMS,
    ERROR_TEXT_LIMIT,
    KIND_13D,
    KIND_13G,
    PURPOSE_LIMIT,
    SEEN_LOOKBACK_DAYS,
)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file, recent_ids
from marketbrief.sources.sec_acceptance import time_summary, time_warnings
from marketbrief.sources.sec_client import Edgar, archive_url
from marketbrief.sources.sec_filings import filings_of_forms, related_ciks, require_sec, ticker_submissions, watch_ciks
from marketbrief.sources.sec_xml import parse_us_date, raw_doc, xml_root, xml_text
from marketbrief.utils.numbers import parse_sec_number


def schedule_13d_persons(root) -> list[dict]:
    """The reporting persons of a Schedule 13D (name, cik, shares, percent of class)."""
    return [
        {
            "name": xml_text(p, "reportingPersonName"),
            "cik": xml_text(p, "reportingPersonCIK"),
            "shares": parse_sec_number(xml_text(p, "aggregateAmountOwned")),
            "percent": parse_sec_number(xml_text(p, "percentOfClass")),
        }
        for p in root.findall("formData/reportingPersons/reportingPersonInfo")
    ]


def schedule_13g_persons(root) -> list[dict]:
    """The reporting persons of a Schedule 13G (name, shares, percent of class; no CIK listed)."""
    return [
        {
            "name": xml_text(p, "reportingPersonName"),
            "cik": None,
            "shares": parse_sec_number(xml_text(p, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares")),
            "percent": parse_sec_number(xml_text(p, "classPercent")),
        }
        for p in root.findall("formData/coverPageHeaderReportingPersonDetails")
    ]


def parse_schedule13(data: bytes) -> dict:
    """Schedule 13D or 13G XML -> issuer, reporting persons (name, cik, shares, percent), dates."""
    root = xml_root(data)
    form = xml_text(root, "headerData/submissionType") or ""
    cover = root.find("formData/coverPageHeader")
    if KIND_13D in form:
        persons = schedule_13d_persons(root)
        event = xml_text(cover, "dateOfEvent")
        item4 = root.find("formData/items1To7/item4")
        purpose = " ".join(text.strip() for text in item4.itertext() if text.strip()) if item4 is not None else None
    else:
        persons = schedule_13g_persons(root)
        event = xml_text(cover, "eventDateRequiresFilingThisStatement")
        purpose = None
    issuer = cover.find("issuerInfo") if cover is not None else None
    return {
        "form": form,
        "kind": KIND_13D if KIND_13D in form else KIND_13G,
        "amendment": form.endswith(AMENDMENT_SUFFIX),
        "issuer_cik": xml_text(issuer, "issuerCIK") or xml_text(issuer, "issuerCik"),
        "issuer_name": xml_text(issuer, "issuerName"),
        "filer_cik": xml_text(root, "headerData/filerInfo/filer/filerCredentials/cik"),
        "event_date": parse_us_date(event),
        "persons": persons,
        "purpose": purpose[:PURPOSE_LIMIT] if purpose else None,
    }


def to_row(filing: dict, parsed: dict, ticker: str, url: str, now: str) -> dict:
    """The `stakes` row of one Schedule 13D/13G."""
    percents = [x["percent"] for x in parsed["persons"] if x["percent"] is not None]
    shares = [x["shares"] for x in parsed["persons"] if x["shares"] is not None]
    names = [x["name"] for x in parsed["persons"] if x["name"]]
    filer_cik = parsed["filer_cik"] or next((x["cik"] for x in parsed["persons"] if x["cik"]), None)
    return {
        COL_ID: filing["accession"],
        COL_TICKER: ticker,
        "issuer_cik": str(int(parsed["issuer_cik"])),
        "form": filing["form"],
        "kind": parsed["kind"],
        "amendment": parsed["amendment"],
        "filing_date": filing["filing_date"],
        "accepted_at": filing["accepted_at"],
        "event_date": parsed["event_date"],
        "filer_name": names[0] if names else None,
        "filer_cik": str(int(filer_cik)) if filer_cik else None,
        "reporting_persons": names,
        "percent": max(percents) if percents else None,
        "shares": max(shares) if shares else None,
        "purpose": parsed["purpose"],
        "url": url,
        "first_seen_at": now,
    }


def main() -> int:
    """Entry point of scripts/collect_stakes.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg[CFG_MARKET]
    user_agent = require_sec(cfg, COLLECTOR_STAKES)
    if user_agent is None:
        return 0
    settings = cfg.get(CFG_RELATIONSHIPS, {}).get(COLLECTOR_STAKES, {})
    forms = set(settings.get("forms", DEFAULT_STAKE_FORMS))
    since = utc_today() - timedelta(days=int(settings.get("lookback_days", DEFAULT_LOOKBACK_DAYS)))
    seen = recent_ids(market, KIND_STAKES, days=SEEN_LOOKBACK_DAYS)
    edgar, now = Edgar(user_agent), utc_now()
    ciks, skipped = watch_ciks(cfg, edgar)
    related = related_ciks(cfg)

    rows, failed, read, as_investor = [], [], 0, 0
    for ticker, cik in ciks.items():
        recent, errors = ticker_submissions(edgar, ticker, cik, related)
        failed += errors
        if recent is None:
            continue
        own = {int(cik), *related.get(ticker.upper(), [])}  # the mapped CIK and its predecessor/related CIKs
        for filing in filings_of_forms(recent, forms, since):
            if filing["accession"] in seen:
                continue
            if int(filing["accession"].split("-")[0]) in own:  # self-filed: the company as an investor
                as_investor += 1
                continue
            url = archive_url(filing["cik"], filing["accession"], raw_doc(filing["primary_doc"]))
            try:
                parsed = parse_schedule13(edgar.get(url))
            except Exception as exc:
                failed.append(
                    {COL_TICKER: ticker, COL_ACCESSION: filing["accession"], "error": str(exc)[:ERROR_TEXT_LIMIT]}
                )
                continue
            read += 1
            seen.add(filing["accession"])
            if not parsed["issuer_cik"] or int(parsed["issuer_cik"]) not in own:
                as_investor += 1
                continue
            rows.append(to_row(filing, parsed, ticker, url, now))

    written = append_jsonl(day_file(market, KIND_STAKES, utc_today()), rows)
    print(
        json.dumps(
            {
                "collector": COLLECTOR_STAKES,
                "market": market,
                "since": str(since),
                "filings_read": read,
                "new_rows": written,
                "new_13d": sum(r["kind"] == KIND_13D and not r["amendment"] for r in rows),
                "as_investor_skipped": as_investor,
                "requests": edgar.requests,
                "sec_times": time_summary(edgar),
                "warnings": time_warnings(edgar),
                "skipped_not_sec": skipped,
                "failed": failed,
            },
            indent=2,
        )
    )
    return 0
