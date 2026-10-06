"""Column types of the SEC-sourced kinds: US relationships, acceptance-time checks and fundamentals."""

from __future__ import annotations

from marketbrief.core.schema_base import Schemas

# Relationships (docs/DESIGN.md phase 5), US from SEC EDGAR: one row per Form 4 transaction
# line (insiders), per Schedule 13D/13G filing (stakes), per 13F filing x watchlist ticker (holdings).
SEC_RELATIONSHIP_SCHEMAS: Schemas = {
    "insiders": (
        "jsonl",
        {
            "id": "VARCHAR",
            "accession": "VARCHAR",
            "line": "INTEGER",
            "ticker": "VARCHAR",
            "issuer_cik": "VARCHAR",
            "form": "VARCHAR",
            "filing_date": "DATE",
            "accepted_at": "TIMESTAMPTZ",
            "insider_name": "VARCHAR",
            "insider_cik": "VARCHAR",
            "role": "VARCHAR",
            "is_director": "BOOLEAN",
            "is_officer": "BOOLEAN",
            "is_ten_pct_owner": "BOOLEAN",
            "derivative": "BOOLEAN",
            "security": "VARCHAR",
            "transaction_date": "DATE",
            "code": "VARCHAR",
            "acquired_disposed": "VARCHAR",
            "shares": "DOUBLE",
            "price": "DOUBLE",
            "value": "DOUBLE",
            "shares_after": "DOUBLE",
            "ownership": "VARCHAR",
            "plan_10b5_1": "BOOLEAN",
            "url": "VARCHAR",
            "first_seen_at": "TIMESTAMPTZ",
        },
    ),
    "stakes": (
        "jsonl",
        {
            "id": "VARCHAR",
            "ticker": "VARCHAR",
            "issuer_cik": "VARCHAR",
            "form": "VARCHAR",
            "kind": "VARCHAR",
            "amendment": "BOOLEAN",
            "filing_date": "DATE",
            "accepted_at": "TIMESTAMPTZ",
            "event_date": "DATE",
            "filer_name": "VARCHAR",
            "filer_cik": "VARCHAR",
            "reporting_persons": "VARCHAR[]",
            "percent": "DOUBLE",
            "shares": "DOUBLE",
            "purpose": "VARCHAR",
            "url": "VARCHAR",
            "first_seen_at": "TIMESTAMPTZ",
        },
    ),
    "holdings": (
        "jsonl",
        {
            "id": "VARCHAR",
            "accession": "VARCHAR",
            "filer_cik": "VARCHAR",
            "filer_name": "VARCHAR",
            "period": "DATE",
            "filing_date": "DATE",
            "accepted_at": "TIMESTAMPTZ",
            "ticker": "VARCHAR",
            "cusip": "VARCHAR",
            "issuer_name": "VARCHAR",
            "shares": "DOUBLE",
            "value_usd": "DOUBLE",
            "put_call": "VARCHAR",
            "n_lines": "INTEGER",
            "url": "VARCHAR",
            "first_seen_at": "TIMESTAMPTZ",
            "report_type": "VARCHAR",
            "complete": "BOOLEAN",
            "note": "VARCHAR",
        },
    ),
}

# SEC acceptance-time checks (scripts/check_sec_times.py; see sec.py): one row per stored accession
# checked against its SGML header. accepted_at = the header's time (authoritative, UTC),
# json_accepted_at = the value stored from the submissions JSON. connect() reads accepted_at of
# filings, insiders, stakes, holdings and fundamentals through it (ACCEPTED_KEYS), so a value
# stored from a shifted submissions file is corrected on read without editing data/.
SEC_TIMES_SCHEMA: tuple[str, dict[str, str]] = (
    "jsonl",
    {
        "accession": "VARCHAR",
        "cik": "VARCHAR",
        "accepted_at": "TIMESTAMPTZ",
        "json_accepted_at": "TIMESTAMPTZ",
        "source": "VARCHAR",
        "checked_at": "TIMESTAMPTZ",
    },
)

# kind -> its accession column, for the sec_times correction in connect()
ACCEPTED_KEYS = {
    "filings": "id",
    "insiders": "accession",
    "stakes": "id",
    "holdings": "accession",
    "fundamentals": "accession",
}

# Fundamentals, US from SEC XBRL company facts (collect_fundamentals.py): one row per ticker x
# tag x period x filing that first reported the value or changed it (prev_value = earlier value).
FUNDAMENTALS_SCHEMA: tuple[str, dict[str, str]] = (
    "jsonl",
    {
        "id": "VARCHAR",
        "ticker": "VARCHAR",
        "cik": "VARCHAR",
        "concept": "VARCHAR",
        "tag": "VARCHAR",
        "tag_rank": "INTEGER",
        "unit": "VARCHAR",
        "period_start": "DATE",
        "period_end": "DATE",
        "period": "VARCHAR",
        "fiscal_year": "INTEGER",
        "fiscal_period": "VARCHAR",
        "form": "VARCHAR",
        "accession": "VARCHAR",
        "filing_date": "DATE",
        "accepted_at": "TIMESTAMPTZ",
        "value": "DOUBLE",
        "prev_value": "DOUBLE",
        "first_seen_at": "TIMESTAMPTZ",
    },
)
