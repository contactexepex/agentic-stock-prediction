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
filings come from its mapped CIK plus `fundamentals.predecessor_ciks` (sec_filings.ticker_submissions).
Requires SEC_USER_AGENT (see marketbrief/sources/sec_filings.py)."""
from __future__ import annotations

import json
from datetime import timedelta

from marketbrief.constants.columns import COL_ACCESSION, COL_ID, COL_TICKER
from marketbrief.constants.config_keys import CFG_MARKET
from marketbrief.constants.kinds import KIND_INSIDERS
from marketbrief.constants.sec_collection import (CFG_RELATIONSHIPS, CODE_PURCHASE, CODE_SALE, COLLECTOR_INSIDERS,
                                                  DEFAULT_INSIDER_FORMS, DEFAULT_LOOKBACK_DAYS, DERIVATIVE_TABLE,
                                                  ERROR_TEXT_LIMIT, INSIDER_VALUE_DECIMALS, ISO_DATE_LENGTH,
                                                  NON_DERIVATIVE_TABLE, ROLE_DIRECTOR, ROLE_OFFICER, ROLE_OTHER,
                                                  ROLE_TEN_PCT_OWNER, SEEN_LOOKBACK_DAYS)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file, recent_ids
from marketbrief.sources.sec_acceptance import time_summary, time_warnings
from marketbrief.sources.sec_client import Edgar, archive_url
from marketbrief.sources.sec_filings import (filings_of_forms, related_ciks, require_sec, ticker_submissions,
                                             watch_ciks)
from marketbrief.sources.sec_xml import raw_doc, xml_flag, xml_root, xml_text
from marketbrief.utils.numbers import parse_sec_number


def owner_role(relationship) -> tuple[str, dict]:
    """(role text, flags) of a reporting owner's relationship to the issuer (officer title, director, 10% owner)."""
    flags = {"is_director": bool(xml_flag(xml_text(relationship, "isDirector"))),
             "is_officer": bool(xml_flag(xml_text(relationship, "isOfficer"))),
             "is_ten_pct_owner": bool(xml_flag(xml_text(relationship, "isTenPercentOwner")))}
    parts = []
    if flags["is_officer"]:
        parts.append(xml_text(relationship, "officerTitle") or ROLE_OFFICER)
    if flags["is_director"]:
        parts.append(ROLE_DIRECTOR)
    if flags["is_ten_pct_owner"]:
        parts.append(ROLE_TEN_PCT_OWNER)
    if xml_flag(xml_text(relationship, "isOther")):
        parts.append(xml_text(relationship, "otherText") or ROLE_OTHER)
    return "; ".join(parts), flags


def transaction_line(transaction, derivative: bool) -> dict:
    """One transaction line (non-derivative or derivative) of a Form 4."""
    shares = parse_sec_number(xml_text(transaction, "transactionAmounts/transactionShares/value"))
    price = parse_sec_number(xml_text(transaction, "transactionAmounts/transactionPricePerShare/value"))
    return {
        "derivative": derivative,
        "security": xml_text(transaction, "securityTitle/value"),
        "transaction_date": (xml_text(transaction, "transactionDate/value") or "")[:ISO_DATE_LENGTH] or None,
        "code": xml_text(transaction, "transactionCoding/transactionCode"),
        "acquired_disposed": xml_text(transaction, "transactionAmounts/transactionAcquiredDisposedCode/value"),
        "shares": shares, "price": price,
        "value": (round(shares * price, INSIDER_VALUE_DECIMALS)
                  if shares is not None and price is not None else None),
        "shares_after": parse_sec_number(xml_text(
            transaction, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
        "ownership": xml_text(transaction, "ownershipNature/directOrIndirectOwnership/value"),
    }


def parse_form4(data: bytes) -> dict:
    """Form 4 XML -> issuer, reporting owners and transaction lines (holdings-only lines skipped)."""
    root = xml_root(data)
    owners = []
    for owner in root.findall("reportingOwner"):
        role, flags = owner_role(owner.find("reportingOwnerRelationship"))
        owners.append({"name": xml_text(owner, "reportingOwnerId/rptOwnerName"),
                       "cik": xml_text(owner, "reportingOwnerId/rptOwnerCik"), "role": role, **flags})
    lines = []
    for table, tag, derivative in (NON_DERIVATIVE_TABLE, DERIVATIVE_TABLE):
        lines += [transaction_line(t, derivative) for t in root.findall(f"{table}/{tag}")]
    return {"form": xml_text(root, "documentType"), "issuer_cik": xml_text(root, "issuer/issuerCik"),
            "symbol": xml_text(root, "issuer/issuerTradingSymbol"), "owners": owners,
            "plan_10b5_1": xml_flag(xml_text(root, "aff10b5One")), "lines": lines}


def to_rows(filing: dict, parsed: dict, ticker: str, url: str, now: str) -> list[dict]:
    """The `insiders` rows of one Form 4: one per transaction line."""
    owners = parsed["owners"] or [{"name": None, "cik": None, "role": "", "is_director": False,
                                   "is_officer": False, "is_ten_pct_owner": False}]
    first = owners[0]
    head = {
        COL_TICKER: ticker, "issuer_cik": str(int(parsed["issuer_cik"])),
        "form": filing["form"], "filing_date": filing["filing_date"], "accepted_at": filing["accepted_at"],
        # joint filings (e.g. a fund and its manager) list every owner; the first owner's CIK and flags
        "insider_name": "; ".join(o["name"] for o in owners if o["name"]) or None,
        "insider_cik": first["cik"], "role": "; ".join(dict.fromkeys(o["role"] for o in owners if o["role"])) or None,
        "is_director": any(o["is_director"] for o in owners), "is_officer": any(o["is_officer"] for o in owners),
        "is_ten_pct_owner": any(o["is_ten_pct_owner"] for o in owners),
    }
    return [{COL_ID: f"{filing['accession']}-{i}", COL_ACCESSION: filing["accession"], "line": i, **head, **line,
             "plan_10b5_1": parsed["plan_10b5_1"], "url": url, "first_seen_at": now}
            for i, line in enumerate(parsed["lines"], start=1)]


def main() -> int:
    """Entry point of scripts/collect_insiders.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg[CFG_MARKET]
    user_agent = require_sec(cfg, COLLECTOR_INSIDERS)
    if user_agent is None:
        return 0
    settings = cfg.get(CFG_RELATIONSHIPS, {}).get(COLLECTOR_INSIDERS, {})
    forms = set(settings.get("forms", DEFAULT_INSIDER_FORMS))
    since = utc_today() - timedelta(days=int(settings.get("lookback_days", DEFAULT_LOOKBACK_DAYS)))
    seen = {i.rsplit("-", 1)[0] for i in recent_ids(market, KIND_INSIDERS, days=SEEN_LOOKBACK_DAYS)}
    edgar, now = Edgar(user_agent), utc_now()
    ciks, skipped = watch_ciks(cfg, edgar)
    related = related_ciks(cfg)

    rows, failed, read, other_issuer = [], [], 0, 0
    for ticker, cik in ciks.items():
        recent, errors = ticker_submissions(edgar, ticker, cik, related)
        failed += errors
        if recent is None:
            continue
        own = {int(cik), *related.get(ticker.upper(), [])}   # the mapped CIK and its predecessor/related CIKs
        for filing in filings_of_forms(recent, forms, since):
            if filing["accession"] in seen:
                continue
            url = archive_url(filing["cik"], filing["accession"], raw_doc(filing["primary_doc"]))
            try:
                parsed = parse_form4(edgar.get(url))
            except Exception as exc:
                failed.append({COL_TICKER: ticker, COL_ACCESSION: filing["accession"],
                               "error": str(exc)[:ERROR_TEXT_LIMIT]})
                continue
            read += 1
            seen.add(filing["accession"])
            # the company itself may file Form 4s as an owner of another issuer: keep only its own stock
            if not parsed["issuer_cik"] or int(parsed["issuer_cik"]) not in own:
                other_issuer += 1
                continue
            rows += to_rows(filing, parsed, ticker, url, now)

    written = append_jsonl(day_file(market, KIND_INSIDERS, utc_today()), rows)
    print(json.dumps({
        "collector": COLLECTOR_INSIDERS, "market": market, "since": str(since), "filings_read": read,
        "new_rows": written, "open_market_buys": sum(r["code"] == CODE_PURCHASE for r in rows),
        "open_market_sales": sum(r["code"] == CODE_SALE for r in rows), "other_issuer_skipped": other_issuer,
        "requests": edgar.requests, "sec_times": time_summary(edgar), "warnings": time_warnings(edgar),
        "skipped_not_sec": skipped, "failed": failed}, indent=2))
    return 0
