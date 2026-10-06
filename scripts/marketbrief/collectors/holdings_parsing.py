"""Parsers and row builders of the 13F holdings collector: the cover page, the (stream-parsed) information table,
the completeness rule and the `holdings` rows of one filing."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from typing import NamedTuple

from marketbrief.constants.columns import COL_ACCESSION, COL_ID, COL_TICKER
from marketbrief.constants.sec_collection import (MSG_INCOMPLETE_CONFIDENTIAL,
                                                  MSG_INCOMPLETE_OTHER_MANAGERS, MSG_INCOMPLETE_PLACEHOLDER,
                                                  MSG_INCOMPLETE_TABLE_LINES, MSG_NO_INFORMATION_TABLE,
                                                  MSG_UNKNOWN_REPORT_TYPE, REPORT_TYPE_HOLDINGS)
from marketbrief.sources.sec_client import Edgar, archive_url
from marketbrief.sources.sec_xml import xml_flag, xml_root, xml_text
from marketbrief.utils.numbers import parse_sec_number

SHARES_TYPE = "SH"
Aggregates = dict[tuple[str, str | None], dict]


class FilingRef(NamedTuple):
    """The filing a set of rows comes from: its listing, the filer's CIK and name, the document URL and the time."""
    filing: dict
    cik: int
    filer: str
    url: str
    now: str


def quarter_end(day: date) -> date:
    """Latest calendar quarter end strictly before `day`."""
    quarter = (day.month - 1) // 3
    return date(day.year - 1, 12, 31) if quarter == 0 else date(day.year, 3 * quarter, 30 if quarter in (2, 3) else 31)


def parse_cover(data: bytes) -> dict:
    """13F cover page (primary_doc.xml of a 13F-HR or 13F-NT)."""
    root = xml_root(data)
    total = parse_sec_number(xml_text(root, "formData/summaryPage/tableEntryTotal"))
    managers = root.findall("formData/coverPage/otherManagersInfo/otherManager")
    return {"report_type": (xml_text(root, "formData/coverPage/reportType") or "").upper(),
            "entry_total": int(total) if total is not None else None,
            "confidential": bool(xml_flag(xml_text(root, "formData/summaryPage/isConfidentialOmitted"))),
            "other_managers": [xml_text(m, "name") for m in managers if xml_text(m, "name")]}


def local_name(tag: str) -> str:
    """An XML tag without its namespace."""
    return tag.split("}")[-1]


def add_line(aggregates: Aggregates, children: dict, ticker: str, cusip: str) -> None:
    """Add one information-table line of a watched CUSIP (shares only, not principal amounts) to the aggregates."""
    amounts = ({local_name(c.tag): (c.text or "").strip() for c in children["shrsOrPrnAmt"]}
               if "shrsOrPrnAmt" in children else {})
    if amounts.get("sshPrnamtType", SHARES_TYPE) != SHARES_TYPE:
        return
    put_call = (children["putCall"].text or "").strip().upper() if "putCall" in children else None
    aggregate = aggregates.setdefault((ticker, put_call or None), {
        "cusip": cusip, "shares": 0.0, "value_usd": 0.0, "n_lines": 0,
        "issuer_name": (children["nameOfIssuer"].text or "").strip()})
    aggregate["shares"] += parse_sec_number(amounts.get("sshPrnamt")) or 0.0
    aggregate["value_usd"] += parse_sec_number(children["value"].text if "value" in children else None) or 0.0
    aggregate["n_lines"] += 1


def parse_info_table(stream, cusips: dict[str, str]) -> tuple[Aggregates, int, bool]:
    """Stream a 13F information table; sum shares/value per (ticker, put/call) for watched
    CUSIPs. Returns (aggregates, number of table lines, placeholder line seen)."""
    aggregates: Aggregates = {}
    total, placeholder = 0, False
    for _, element in ET.iterparse(stream):
        if local_name(element.tag) != "infoTable":
            continue
        total += 1
        children = {local_name(c.tag): c for c in element}
        cusip = (children["cusip"].text or "").strip().upper() if "cusip" in children else ""
        placeholder |= cusip.strip("0") == ""
        ticker = cusips.get(cusip)
        if ticker:
            add_line(aggregates, children, ticker, cusip)
        element.clear()
    return aggregates, total, placeholder


def incomplete_reason(cover: dict, n_lines: int, placeholder: bool) -> str | None:
    """Why a filing cannot show exits (None = complete: zero rows may be written)."""
    if cover["report_type"] != REPORT_TYPE_HOLDINGS:
        return MSG_INCOMPLETE_OTHER_MANAGERS.format(report_type=cover["report_type"] or MSG_UNKNOWN_REPORT_TYPE)
    if cover["confidential"]:
        return MSG_INCOMPLETE_CONFIDENTIAL
    if placeholder:
        return MSG_INCOMPLETE_PLACEHOLDER
    if cover["entry_total"] is not None and cover["entry_total"] != n_lines:
        return MSG_INCOMPLETE_TABLE_LINES.format(lines=n_lines, total=cover["entry_total"])
    return None


def info_table_url(edgar: Edgar, cik: int, accession: str) -> str:
    """The URL of a filing's information table (its largest XML besides primary_doc.xml)."""
    items = edgar.json(archive_url(cik, accession, "index.json"))["directory"]["item"]
    xmls = [i for i in items if i["name"].lower().endswith(".xml") and i["name"] != "primary_doc.xml"]
    if not xmls:
        raise ValueError(MSG_NO_INFORMATION_TABLE)
    best = max(xmls, key=lambda i: int(i.get("size") or 0))
    return archive_url(cik, accession, best["name"])


def base_row(ref: FilingRef) -> dict:
    """The columns every `holdings` row of a filing shares."""
    filing = ref.filing
    return {COL_ACCESSION: filing["accession"], "filer_cik": str(ref.cik), "filer_name": ref.filer,
            "period": filing["report_date"], "filing_date": filing["filing_date"],
            "accepted_at": filing["accepted_at"], "url": ref.url, "first_seen_at": ref.now}


def filing_row(ref: FilingRef, report_type: str, n_lines: int | None, complete: bool, note: str | None) -> dict:
    """The filing row (ticker null): report type, table lines, `complete`, and a note."""
    return {COL_ID: f"{ref.filing['accession']}-FILING", **base_row(ref), COL_TICKER: None, "cusip": None,
            "issuer_name": None, "shares": None, "value_usd": None, "put_call": None, "n_lines": n_lines,
            "report_type": report_type, "complete": complete, "note": note}


def to_rows(ref: FilingRef, aggregates: Aggregates, zero_fill: list[str], report_type: str,
            complete: bool) -> list[dict]:
    """One row per watched (ticker[, put/call]) held, plus a zero row for each `zero_fill` ticker not held."""
    for ticker in zero_fill:
        aggregates.setdefault((ticker, None), {"cusip": None, "shares": 0.0, "value_usd": 0.0, "n_lines": 0,
                                               "issuer_name": None})
    rows = []
    for (ticker, put_call), aggregate in sorted(aggregates.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        rows.append({COL_ID: f"{ref.filing['accession']}-{ticker}" + (f"-{put_call}" if put_call else ""),
                     **base_row(ref), COL_TICKER: ticker, "cusip": aggregate["cusip"],
                     "issuer_name": aggregate["issuer_name"], "shares": aggregate["shares"],
                     "value_usd": aggregate["value_usd"], "put_call": put_call, "n_lines": aggregate["n_lines"],
                     "report_type": report_type, "complete": complete, "note": None})
    return rows
