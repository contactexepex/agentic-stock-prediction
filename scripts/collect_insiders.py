#!/usr/bin/env python3
"""Collect insider transactions (SEC Form 4 and 4/A) for watchlist tickers into
data/<market>/insiders/YYYY/MM/<today>.jsonl, one row per transaction line:
insider name and role, transaction code, shares, price, value, date and holding afterwards.
Rows are appended once; the id is <accession>-<line> (non-derivative lines first, then
derivative lines, numbered from 1).

Transaction codes (SEC): P open-market purchase, S open-market sale, A award, M option
exercise, F tax withholding, G gift, D disposition to the issuer, C conversion, X exercise of
an in-the-money option. Only P and S are discretionary trades; the views in sql/views.sql use them.

Only for markets with `filings: sec` (India insider disclosures come from the India collector).
Settings: relationships.insiders in config/markets/<market>.yaml (lookback_days, forms). A ticker's
filings come from its mapped CIK plus `fundamentals.predecessor_ciks` (sec.ticker_submissions).
Requires SEC_USER_AGENT (see scripts/sec.py)."""
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

DEFAULT_FORMS = ["4", "4/A"]


def owner_role(rel) -> tuple[str, dict]:
    flags = {"is_director": bool(sec.flag(sec.text(rel, "isDirector"))),
             "is_officer": bool(sec.flag(sec.text(rel, "isOfficer"))),
             "is_ten_pct_owner": bool(sec.flag(sec.text(rel, "isTenPercentOwner")))}
    parts = []
    if flags["is_officer"]:
        parts.append(sec.text(rel, "officerTitle") or "Officer")
    if flags["is_director"]:
        parts.append("Director")
    if flags["is_ten_pct_owner"]:
        parts.append("10% owner")
    if sec.flag(sec.text(rel, "isOther")):
        parts.append(sec.text(rel, "otherText") or "Other")
    return "; ".join(parts), flags


def parse_form4(data: bytes) -> dict:
    """Form 4 XML -> issuer, reporting owners and transaction lines (holdings-only lines skipped)."""
    root = sec.xml_root(data)
    owners = []
    for o in root.findall("reportingOwner"):
        role, flags = owner_role(o.find("reportingOwnerRelationship"))
        owners.append({"name": sec.text(o, "reportingOwnerId/rptOwnerName"),
                       "cik": sec.text(o, "reportingOwnerId/rptOwnerCik"), "role": role, **flags})
    lines = []
    for table, tag, derivative in (("nonDerivativeTable", "nonDerivativeTransaction", False),
                                   ("derivativeTable", "derivativeTransaction", True)):
        for t in root.findall(f"{table}/{tag}"):
            shares = parse_sec_number(sec.text(t, "transactionAmounts/transactionShares/value"))
            price = parse_sec_number(sec.text(t, "transactionAmounts/transactionPricePerShare/value"))
            lines.append({
                "derivative": derivative,
                "security": sec.text(t, "securityTitle/value"),
                "transaction_date": (sec.text(t, "transactionDate/value") or "")[:10] or None,
                "code": sec.text(t, "transactionCoding/transactionCode"),
                "acquired_disposed": sec.text(t, "transactionAmounts/transactionAcquiredDisposedCode/value"),
                "shares": shares, "price": price,
                "value": round(shares * price, 2) if shares is not None and price is not None else None,
                "shares_after": parse_sec_number(sec.text(t,
                "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                "ownership": sec.text(t, "ownershipNature/directOrIndirectOwnership/value"),
            })
    return {"form": sec.text(root, "documentType"), "issuer_cik": sec.text(root, "issuer/issuerCik"),
            "symbol": sec.text(root, "issuer/issuerTradingSymbol"), "owners": owners,
            "plan_10b5_1": sec.flag(sec.text(root, "aff10b5One")), "lines": lines}


def to_rows(f: dict, parsed: dict, ticker: str, url: str, now: str) -> list[dict]:
    owners = parsed["owners"] or [{"name": None, "cik": None, "role": "", "is_director": False,
                                   "is_officer": False, "is_ten_pct_owner": False}]
    first = owners[0]
    head = {
        "ticker": ticker, "issuer_cik": str(int(parsed["issuer_cik"])),
        "form": f["form"], "filing_date": f["filing_date"], "accepted_at": f["accepted_at"],
        # joint filings (e.g. a fund and its manager) list every owner; the first owner's CIK and flags
        "insider_name": "; ".join(o["name"] for o in owners if o["name"]) or None,
        "insider_cik": first["cik"], "role": "; ".join(dict.fromkeys(o["role"] for o in owners if o["role"])) or None,
        "is_director": any(o["is_director"] for o in owners), "is_officer": any(o["is_officer"] for o in owners),
        "is_ten_pct_owner": any(o["is_ten_pct_owner"] for o in owners),
    }
    return [{"id": f"{f['accession']}-{i}", "accession": f["accession"], "line": i, **head, **line,
             "plan_10b5_1": parsed["plan_10b5_1"], "url": url, "first_seen_at": now}
            for i, line in enumerate(parsed["lines"], start=1)]


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg["market"]
    ua = sec.require_sec(cfg, "insiders")
    if ua is None:
        return 0
    rel = cfg.get("relationships", {}).get("insiders", {})
    forms = set(rel.get("forms", DEFAULT_FORMS))
    since = utc_today() - timedelta(days=int(rel.get("lookback_days", 7)))
    seen = {i.rsplit("-", 1)[0] for i in recent_ids(market, "insiders", days=120)}
    edgar, now = Edgar(ua), utc_now()
    ciks, skipped = sec.watch_ciks(cfg, edgar)
    related = sec.related_ciks(cfg)

    rows, failed, read, other_issuer = [], [], 0, 0
    for ticker, cik in ciks.items():
        recent, errors = sec.ticker_submissions(edgar, ticker, cik, related)
        failed += errors
        if recent is None:
            continue
        own = {int(cik), *related.get(ticker.upper(), [])}   # the mapped CIK and its predecessor/related CIKs
        for f in sec.filings(recent, forms, since):
            if f["accession"] in seen:
                continue
            url = archive_url(f["cik"], f["accession"], sec.raw_doc(f["primary_doc"]))
            try:
                parsed = parse_form4(edgar.get(url))
            except Exception as exc:
                failed.append({"ticker": ticker, "accession": f["accession"], "error": str(exc)[:200]})
                continue
            read += 1
            seen.add(f["accession"])
            # the company itself may file Form 4s as an owner of another issuer: keep only its own stock
            if not parsed["issuer_cik"] or int(parsed["issuer_cik"]) not in own:
                other_issuer += 1
                continue
            rows += to_rows(f, parsed, ticker, url, now)

    written = append_jsonl(day_file(market, "insiders", utc_today()), rows)
    print(json.dumps({
        "collector": "insiders", "market": market, "since": str(since), "filings_read": read,
        "new_rows": written, "open_market_buys": sum(r["code"] == "P" for r in rows),
        "open_market_sales": sum(r["code"] == "S" for r in rows), "other_issuer_skipped": other_issuer,
        "requests": edgar.requests, "sec_times": time_summary(edgar), "warnings": time_warnings(edgar), "skipped_not_sec": skipped, "failed": failed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
