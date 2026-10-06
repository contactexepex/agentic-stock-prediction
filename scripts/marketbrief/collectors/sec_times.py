"""Check the stored SEC acceptance times against the authoritative SGML header and append the
results to data/<market>/sec_times/YYYY/MM/<today>.jsonl (append-only; see marketbrief/sources/sec_filings.py
for the submissions-JSON shift this repairs).

Every accession stored in filings, insiders, stakes, holdings or fundamentals with an
`accepted_at` and not checked before (no sec_times row yet) is looked up once in its
`<accession>.hdr.sgml` (cached in work/sec_acceptance.json, one throttled request per new
accession). One row per accession: accepted_at = the header's time (UTC), json_accepted_at = the
stored value. core.database.connect() then reads accepted_at of those kinds through the newest row per
accession, so a value stored from a shifted submissions file is corrected on read, without editing
data/. --dry-run prints the summary without appending. Only for markets with `filings: sec`; needs
SEC_USER_AGENT. The daily routine runs it after the SEC collectors (routine/PROMPT.md step 3):
the collectors already store corrected times from a file proven shifted, so this catches rows
stored from an unverified file (listed in the collectors' `warnings`) and rows stored before the
fix; each new accession costs one request once. `failed` lists headers that could not be read."""

from __future__ import annotations

import json
import re

from marketbrief.constants.columns import COL_ACCEPTED_AT, COL_ACCESSION, COL_CHECKED_AT, COL_SOURCE
from marketbrief.constants.config_keys import CFG_MARKET
from marketbrief.constants.sec_times import (
    COLLECTOR_SEC_TIMES,
    ERROR_TEXT_LIMIT,
    MSG_NO_HEADER_TIME,
    SEC_TIME_CHECKED_SQL,
    SEC_TIME_ONLY_ACCEPTED,
    SEC_TIME_SOURCES,
    SOURCE_SGML_HEADER,
    WRONG_ROWS_LIMIT,
)
from marketbrief.constants.kinds import KIND_SEC_TIMES
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_FAILED, SUMMARY_MARKET, SUMMARY_REQUESTS
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.paths import data_dir
from marketbrief.core.schemas import SCHEMAS
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.sources.sec_client import Edgar
from marketbrief.sources.sec_filings import require_sec
from marketbrief.utils.timefmt import format_utc_z, parse_utc_z

ARCHIVE_FOLDER = re.compile(r"/edgar/data/(\d+)/")


def raw_rows_sql(base, kind: str, query: str) -> str:
    """The SQL of one kind's raw stored rows, with the file reader and its typed columns filled in."""
    spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in SCHEMAS[kind][1].items()) + "}"
    source = f"read_json('{(base / kind).as_posix()}/**/*.jsonl', format='newline_delimited', columns={spec})"
    return query.format(src=source) + SEC_TIME_ONLY_ACCEPTED


def stored(market: str) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """(accession -> (CIK folder, stored accepted_at as iso_z), accessions already checked)."""
    base = data_dir(market)
    connection = connect(market)
    found: dict[str, tuple[str, str]] = {}
    for kind, query in SEC_TIME_SOURCES.items():
        if not any((base / kind).glob("**/*.jsonl")):
            continue
        for accession, cik, accepted_at, url in connection.execute(raw_rows_sql(base, kind, query)).fetchall():
            if not accession or accession in found:
                continue
            match = ARCHIVE_FOLDER.search(url or "")
            folder = match.group(1) if match else cik  # the archive folder the filing is served from
            if folder:
                found[accession] = (str(int(folder)), format_utc_z(accepted_at))
    checked = {row[0] for row in connection.execute(SEC_TIME_CHECKED_SQL).fetchall()}
    return found, checked


def check_accession(edgar: Edgar, accession: str, cik: str, stored_at: str, now: str) -> dict:
    """The sec_times row of one accession, or {"failed": entry} when its header could not be read."""
    try:
        header_time = edgar.acceptance(cik, accession)
    except Exception as exc:
        return {"failed": {COL_ACCESSION: accession, "cik": cik, "error": str(exc)[:ERROR_TEXT_LIMIT]}}
    if header_time is None:
        return {"failed": {COL_ACCESSION: accession, "cik": cik, "error": MSG_NO_HEADER_TIME}}
    return {
        COL_ACCESSION: accession,
        "cik": cik,
        COL_ACCEPTED_AT: header_time,
        "json_accepted_at": stored_at,
        COL_SOURCE: SOURCE_SGML_HEADER,
        COL_CHECKED_AT: now,
    }


def wrong_entry(row: dict) -> dict | None:
    """The summary entry of a stored time that differs from its header, or None when they agree."""
    header, stored_at = row[COL_ACCEPTED_AT], row["json_accepted_at"]
    if parse_utc_z(header) == parse_utc_z(stored_at):
        return None
    return {
        COL_ACCESSION: row[COL_ACCESSION],
        "stored": stored_at,
        "header": header,
        "stored_minus_true_h": (parse_utc_z(stored_at) - parse_utc_z(header)).total_seconds() / 3600,
    }


def main() -> int:
    """Entry point of scripts/check_sec_times.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--dry-run", action="store_true", help="check and print, do not append")
    args = parser.parse_args()
    cfg = require_market(args)
    user_agent = require_sec(cfg, COLLECTOR_SEC_TIMES)
    if user_agent is None:
        return 0
    market = cfg[CFG_MARKET]
    rows_in, done = stored(market)
    edgar = Edgar(user_agent)
    now = utc_now()
    rows, failed, wrong = [], [], []
    for accession, (cik, stored_at) in sorted(rows_in.items()):
        if accession in done:
            continue
        result = check_accession(edgar, accession, cik, stored_at, now)
        if "failed" in result:
            failed.append(result["failed"])
            continue
        rows.append(result)
        mismatch = wrong_entry(result)
        if mismatch:
            wrong.append(mismatch)
    written = 0 if args.dry_run else append_jsonl(day_file(market, KIND_SEC_TIMES, utc_today()), rows)
    print(
        json.dumps(
            {
                SUMMARY_COLLECTOR: COLLECTOR_SEC_TIMES,
                SUMMARY_MARKET: market,
                "stored_accessions": len(rows_in),
                "already_checked": len(done & set(rows_in)),
                "checked": len(rows),
                "written": written,
                "wrong": len(wrong),
                "wrong_rows": wrong[:WRONG_ROWS_LIMIT],
                SUMMARY_FAILED: failed,
                SUMMARY_REQUESTS: edgar.requests,
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 1 if failed and not rows else 0
