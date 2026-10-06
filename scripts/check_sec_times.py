#!/usr/bin/env python3
"""Check the stored SEC acceptance times against the authoritative SGML header and append the
results to data/<market>/sec_times/YYYY/MM/<today>.jsonl (append-only; see sec.py for the
submissions-JSON shift this repairs).

Every accession stored in filings, insiders, stakes, holdings or fundamentals with an
`accepted_at` and not checked before (no sec_times row yet) is looked up once in its
`<accession>.hdr.sgml` (cached in work/sec_acceptance.json, one throttled request per new
accession). One row per accession: accepted_at = the header's time (UTC), json_accepted_at = the
stored value. common.connect() then reads accepted_at of those kinds through the newest row per
accession, so a value stored from a shifted submissions file is corrected on read, without editing
data/. --dry-run prints the summary without appending. Only for markets with `filings: sec`; needs
SEC_USER_AGENT. The daily routine runs it after the SEC collectors (routine/PROMPT.md step 3):
the collectors already store corrected times from a file proven shifted, so this catches rows
stored from an unverified file (listed in the collectors' `warnings`) and rows stored before the
fix; each new accession costs one request once. `failed` lists headers that could not be read."""
from __future__ import annotations

import json
import re
import sys

from common import append_jsonl, connect, day_file, market_arg, require_market, utc_now, utc_today

import sec

# kind -> SQL giving (accession, cik folder, stored accepted_at) of its rows, read raw from the files
SOURCES = {
    "filings": "SELECT id AS accession, cik, accepted_at, url FROM {src}",
    "insiders": "SELECT accession, issuer_cik AS cik, accepted_at, url FROM {src}",
    "stakes": "SELECT id AS accession, issuer_cik AS cik, accepted_at, url FROM {src}",
    "holdings": "SELECT accession, filer_cik AS cik, accepted_at, url FROM {src}",
    "fundamentals": "SELECT accession, cik, accepted_at, NULL AS url FROM {src}",
}


def stored(market: str) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """(accession -> (CIK folder, stored accepted_at as iso_z), accessions already checked)."""
    from common import SCHEMAS, data_dir
    base = data_dir(market)
    con = connect(market)
    out: dict[str, tuple[str, str]] = {}
    for kind, sql in SOURCES.items():
        if not any((base / kind).glob("**/*.jsonl")):
            continue
        spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in SCHEMAS[kind][1].items()) + "}"
        src = f"read_json('{(base / kind).as_posix()}/**/*.jsonl', format='newline_delimited', columns={spec})"
        for acc, cik, at, url in con.execute(sql.format(src=src) + " WHERE accepted_at IS NOT NULL").fetchall():
            if not acc or acc in out:
                continue
            m = re.search(r"/edgar/data/(\d+)/", url or "")
            folder = m.group(1) if m else cik     # the archive folder the filing is served from
            if folder:
                out[acc] = (str(int(folder)), sec.iso_z(at))
    done = {r[0] for r in con.execute("SELECT DISTINCT accession FROM sec_times").fetchall()}
    return out, done


def main() -> int:
    p = market_arg(__doc__)
    p.add_argument("--dry-run", action="store_true", help="check and print, do not append")
    args = p.parse_args()
    cfg = require_market(args)
    ua = sec.require_sec(cfg, "sec_times")
    if ua is None:
        return 0
    market = cfg["market"]
    rows_in, done = stored(market)
    edgar = sec.Edgar(ua)
    now = utc_now()
    rows, failed, wrong = [], [], []
    for acc, (cik, at) in sorted(rows_in.items()):
        if acc in done:
            continue
        try:
            true = edgar.acceptance(cik, acc)
        except Exception as exc:
            failed.append({"accession": acc, "cik": cik, "error": str(exc)[:200]})
            continue
        if true is None:
            failed.append({"accession": acc, "cik": cik, "error": "no ACCEPTANCE-DATETIME in header"})
            continue
        rows.append({"accession": acc, "cik": cik, "accepted_at": true, "json_accepted_at": at,
                     "source": "sgml_header", "checked_at": now})
        if sec.parse_z(true) != sec.parse_z(at):
            wrong.append({"accession": acc, "stored": at, "header": true,
                          "stored_minus_true_h": (sec.parse_z(at) - sec.parse_z(true)).total_seconds() / 3600})
    written = 0 if args.dry_run else append_jsonl(day_file(market, "sec_times", utc_today()), rows)
    print(json.dumps({"collector": "sec_times", "market": market, "stored_accessions": len(rows_in),
                      "already_checked": len(done & set(rows_in)), "checked": len(rows), "written": written,
                      "wrong": len(wrong), "wrong_rows": wrong[:50], "failed": failed,
                      "requests": edgar.requests, "dry_run": args.dry_run}, indent=2))
    return 1 if failed and not rows else 0


if __name__ == "__main__":
    sys.exit(main())
