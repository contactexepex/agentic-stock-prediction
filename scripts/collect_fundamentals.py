#!/usr/bin/env python3
"""Collect quarterly, half-yearly and annual financial data for watchlist tickers from SEC
EDGAR's free XBRL "company facts" API (data.sec.gov/api/xbrl/companyfacts/CIK##########.json)
into data/<market>/fundamentals/YYYY/MM/<today>.jsonl.

Facts come from 10-Q and 10-K filings (and their amendments and 10-KT). Each standard concept
(revenue, gross profit, operating income, net income, diluted EPS, operating cash flow, capex,
cash, debt parts, shares) is read from a short list of us-gaap/dei tags in priority order
(CONCEPTS); companies use different tags, and every row keeps the tag it came from. Only
non-dimensional (company total) facts exist in company facts.

One row per ticker x tag x period (start, end) x filing, written only when a filing first
reports that period's value or reports a different value than the one before it (a
restatement, a split adjustment or a rounding change: `prev_value` holds the earlier value).
A comparative period repeated unchanged in a later filing adds nothing. Rows are append-only;
the views in sql/views.sql pick, per period, the best-ranked tag and its newest filing.

`period` is `quarter` (70-130 days; 16-week quarters included), `ytd` (150-300 days: `H1` =
6 months / 2 quarters, `9M` = 3 quarters), `annual` (340-380 days, `FY`) or `instant`
(balance-sheet items and share counts). Fiscal year and period are those of the filing whose
own reporting period ends on that date (SEC's fy/fp describe the filing, not the fact). A
fiscal Q4 is rarely reported as such: the views derive it as FY minus 9M (and quarterly cash
flows from the year-to-date totals) and mark it derived.

Cheap to run daily: one submissions request per ticker; the company facts file (1-8 MB) is
downloaded only for a ticker never loaded before, or when a 10-Q/10-K filed in the last
`recheck_days` is not stored yet (the XBRL API can lag a filing by a few hours, so it is
retried on the next run). The first load stores periods ending in the last `history_years`.
Settings: `fundamentals:` in config/markets/<market>.yaml (history_years, recheck_days,
predecessor_ciks for a ticker whose history sits under an earlier registrant).
Only for markets with `filings: sec`. Requires SEC_USER_AGENT (see scripts/sec.py)."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta

import sec
from common import append_jsonl, data_dir, day_file, market_arg, require_market, utc_now, utc_today

PERIODIC_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A", "10-KT", "10-KT/A"}
USD, PER_SHARE, SHARES = "USD", "USD/shares", "shares"

# concept -> (unit, tags in priority order). "dei:" marks a dei tag, others are us-gaap.
# Revenue: banks report net revenue (net of interest expense) as their headline; `Revenues`
# (total revenues) ranks above revenue from contracts with customers, which for some companies
# (banks, oil majors, GM) is only a part of total revenue.
CONCEPTS: dict[str, tuple[str, list[str]]] = {
    "revenue": (USD, ["RevenuesNetOfInterestExpense", "Revenues",
                      "RevenueFromContractWithCustomerExcludingAssessedTax",
                      "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet"]),
    "cost_of_revenue": (USD, ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]),
    "gross_profit": (USD, ["GrossProfit"]),
    "operating_income": (USD, ["OperatingIncomeLoss"]),
    "net_income": (USD, ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"]),
    "eps_diluted": (PER_SHARE, ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]),
    "operating_cash_flow": (USD, ["NetCashProvidedByUsedInOperatingActivities",
                                  "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
    "capex": (USD, ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                    "PaymentsToAcquireOtherPropertyPlantAndEquipment"]),
    "cash": (USD, ["CashAndCashEquivalentsAtCarryingValue", "CashAndDueFromBanks", "Cash",
                   "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    # Debt parts; the fundamentals_debt view adds them up into total debt.
    "debt_combined": (USD, ["DebtLongtermAndShorttermCombinedAmount"]),
    "debt_long_term_total": (USD, ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"]),
    "debt_noncurrent": (USD, ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"]),
    "debt_current": (USD, ["DebtCurrent"]),
    "long_term_debt_current": (USD, ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"]),
    "short_term_borrowings": (USD, ["ShortTermBorrowings", "CommercialPaper", "OtherShortTermBorrowings"]),
    "shares_outstanding": (SHARES, ["dei:EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"]),
    "shares_diluted_avg": (SHARES, ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
}


def facts_url(cik: int) -> str:
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"


def extract(doc: dict, cik: int) -> list[dict]:
    """Company facts JSON -> one dict per fact of a CONCEPTS tag (expected unit, periodic forms)."""
    out = []
    for concept, (unit, tags) in CONCEPTS.items():
        for rank, tag in enumerate(tags):
            ns, name = tag.split(":", 1) if ":" in tag else ("us-gaap", tag)
            for f in doc.get("facts", {}).get(ns, {}).get(name, {}).get("units", {}).get(unit, []):
                if f.get("form") not in PERIODIC_FORMS or f.get("val") is None:
                    continue
                out.append({"concept": concept, "tag": f"{ns}:{name}", "tag_rank": rank, "unit": unit,
                            "start": f.get("start"), "end": f["end"], "value": f["val"], "accession": f["accn"],
                            "form": f["form"], "filing_date": f["filed"], "fy": f.get("fy"), "fp": f.get("fp"),
                            "cik": str(int(cik))})
    return out


def period_kind(start: str | None, end: str) -> str | None:
    if not start:
        return "instant"
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if 70 <= days <= 130:
        return "quarter"
    if 150 <= days <= 300:
        return "ytd"
    if 340 <= days <= 380:
        return "annual"
    return None  # stub or transition period


def report_periods(facts: list[dict]) -> tuple[dict[str, tuple], dict[str, tuple]]:
    """Each filing's own reporting period = the latest end date of its duration facts.
    Returns accession -> (report end, fy, fp) and report end -> (fy, fp) of the earliest filing."""
    by_accn: dict[str, tuple] = {}
    for f in facts:
        if f["start"] and (f["accession"] not in by_accn or f["end"] > by_accn[f["accession"]][0]):
            by_accn[f["accession"]] = (f["end"], f["fy"], f["fp"], f["filing_date"])
    by_end: dict[str, tuple] = {}
    for end, fy, fp, filed in sorted(by_accn.values(), key=lambda r: r[3], reverse=True):
        if fy and fp:
            by_end[end] = (fy, fp)       # earliest filing for the period wins (sorted newest first)
    return {a: r[:3] for a, r in by_accn.items()}, by_end


def fiscal_label(kind: str, f: dict, by_accn: dict, by_end: dict) -> tuple[int | None, str | None]:
    lab = by_end.get(f["end"])
    if lab is None:
        rep = by_accn.get(f["accession"])
        if rep and f["end"] > rep[0] and rep[1] and rep[2]:   # after the period, e.g. a cover-page share count
            lab = (rep[1], rep[2])
    if lab is None:                                          # one year before a known period end
        end = date.fromisoformat(f["end"])
        for e, (fy, fp) in by_end.items():
            if 357 <= (date.fromisoformat(e) - end).days <= 371:
                lab = (fy - 1, fp)
                break
    if lab is None:
        return None, None
    fy, fp = lab
    if kind == "annual":
        return fy, "FY"
    if kind == "quarter":
        return fy, "Q4" if fp == "FY" else fp
    if kind == "ytd":
        return fy, {"Q2": "H1", "Q3": "9M"}.get(fp)
    return fy, fp


def row_id(ticker: str, f: dict) -> str:
    return f"{ticker}-{f['tag']}-{f['start'] or 'instant'}-{f['end']}-{f['accession']}"


def new_rows(ticker: str, facts: list[dict], stored_ids: set[str], since: str, accepted: dict[str, str],
             now: str) -> list[dict]:
    """Rows for facts not stored yet whose value is new for their (tag, period): walk each
    period's facts in filing order; a value equal to the previous filing's is skipped."""
    by_accn, by_end = report_periods(facts)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for f in facts:
        if f["end"] >= since:
            groups[(f["tag"], f["unit"], f["start"], f["end"])].append(f)
    rows = []
    for key in sorted(groups, key=lambda k: (k[0], k[2] or "", k[3])):
        kind = period_kind(key[2], key[3])
        if kind is None:
            continue
        last = None
        for f in sorted(groups[key], key=lambda x: (x["filing_date"], x["accession"])):
            rid = row_id(ticker, f)
            if rid in stored_ids:
                last = f["value"]
                continue
            if last is not None and f["value"] == last:
                continue
            fy, fp = fiscal_label(kind, f, by_accn, by_end)
            rows.append({"id": rid, "ticker": ticker, "cik": f["cik"], "concept": f["concept"], "tag": f["tag"],
                         "tag_rank": f["tag_rank"], "unit": f["unit"], "period_start": f["start"],
                         "period_end": f["end"], "period": kind, "fiscal_year": fy, "fiscal_period": fp,
                         "form": f["form"], "accession": f["accession"], "filing_date": f["filing_date"],
                         "accepted_at": accepted.get(f["accession"]), "value": f["value"], "prev_value": last,
                         "first_seen_at": now})
            stored_ids.add(rid)
            last = f["value"]
    return rows


def stored(market: str) -> tuple[set[str], dict[str, set[str]]]:
    """Row ids already stored, and the accessions stored per ticker."""
    ids, accs = set(), defaultdict(set)
    for p in (data_dir(market) / "fundamentals").glob("**/*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                ids.add(r["id"])
                accs[r["ticker"]].add(r["accession"])
    return ids, accs


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--force", action="store_true", help="download company facts even when no new filing is listed")
    args = ap.parse_args()
    cfg = require_market(args)
    market = cfg["market"]
    ua = sec.require_sec(cfg, "fundamentals")
    if ua is None:
        return 0
    fc = cfg.get("fundamentals", {})
    today = utc_today()
    since = str(today - timedelta(days=round(365.25 * float(fc.get("history_years", 3)))))
    recheck = today - timedelta(days=int(fc.get("recheck_days", 10)))
    predecessors = {t: [int(c) for c in cs] for t, cs in (fc.get("predecessor_ciks") or {}).items()}

    ids, accs = stored(market)
    edgar, now = sec.Edgar(ua), utc_now()
    ciks, skipped = sec.watch_ciks(cfg, edgar)
    rows, loaded, up_to_date, new_filings, not_in_xbrl, failed = [], [], [], [], [], []
    for ticker, cik in ciks.items():
        try:
            recent = edgar.recent(cik)
        except Exception as exc:
            failed.append({"ticker": ticker, "error": str(exc)[:200]})
            continue
        periodic = sec.filings(recent, PERIODIC_FORMS)
        accepted = {f["accession"]: f["accepted_at"] for f in periodic}
        pending = [f for f in periodic if date.fromisoformat(f["filing_date"]) >= recheck
                   and f["accession"] not in accs[ticker]]
        if accs[ticker] and not pending and not args.force:
            up_to_date.append(ticker)
            continue
        try:
            facts = []
            for c in [cik, *predecessors.get(ticker, [])]:
                facts += extract(edgar.json(facts_url(c)), c)
        except Exception as exc:
            failed.append({"ticker": ticker, "error": str(exc)[:200]})
            continue
        loaded.append(ticker)
        got = new_rows(ticker, facts, ids, since, accepted, now)
        rows += got
        got_accs = {r["accession"] for r in got}
        for f in pending:
            # a filing without new values (e.g. a 10-K/A for Part III only, or not in the XBRL API yet)
            # adds no rows and is checked again until it is older than recheck_days
            (new_filings if f["accession"] in got_accs else not_in_xbrl).append(
                {"ticker": ticker, "form": f["form"], "accession": f["accession"],
                 "filing_date": f["filing_date"], "report_date": f["report_date"]})
        accs[ticker] |= got_accs

    written = append_jsonl(day_file(market, "fundamentals", today), rows)
    print(json.dumps({
        "collector": "fundamentals", "market": market, "since": since, "new_rows": written,
        "loaded": loaded, "up_to_date": len(up_to_date), "new_filings": new_filings,
        "revised_rows": sum(r["prev_value"] is not None for r in rows),
        "filings_without_new_values": not_in_xbrl,
        "requests": edgar.requests, "skipped_not_sec": skipped, "failed": failed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
