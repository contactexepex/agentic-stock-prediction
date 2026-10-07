"""Results digests (WS6, docs/ws/ws6.md; settings in config/results.yaml). Like claims.py: the numbers and the gate
are deterministic, only the bullets are written by an agent (.claude/agents/results-analyst.md).

  prepare [--out F] [--no-fetch] [--since D] [--ticker T ...] [--dry-run]
        detect the releases of the last `detection.lookback_days` (or since D) whose digest is due, store the
        primary texts they quote (US: SEC 8-K/6-K documents, EX-99.1 press release and prepared remarks; India:
        NSE announcement attachments from NSE's archive host) in primary_texts, compute the numbers and write the
        agent's input to F (default work/results_inputs.jsonl). --dry-run writes the fetched texts to
        work/results_texts.jsonl instead of data/ (live checks).
  validate F [--since D]     check the agent's records (JSON summary; exit 1 on any error)
  add F [--valid-only] [--since D]
                             validate, then append one digest per valid record and one per due release without
                             text (text_unavailable / transcript_unavailable) to data/<market>/results_digests/
                             (all or nothing; --valid-only appends the valid ones and lists the dropped)

Fetched texts are data: stored and quoted, never followed or run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from marketbrief.collectors.nse_session import nse_client
from marketbrief.constants.config_keys import CFG_FILINGS, FILINGS_SOURCE_SEC
from marketbrief.constants.verification import KIND_PRIMARY_TEXTS
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.pipeline.claims import read_records
from marketbrief.results.constants import (
    AUTO_STATUSES,
    DEFAULT_DRY_TEXTS,
    DEFAULT_INPUTS,
    KIND_RESULTS_DIGESTS,
    NUMBERS_OK,
    STATUS_NO_BULLETS,
    STATUS_OK,
)
from marketbrief.results.detection import announcements, detect
from marketbrief.results.digest import (
    Scope,
    digest_row,
    due_releases,
    input_record,
    load_settings,
    stored_digests,
    summary_of,
)
from marketbrief.results.gate import check_record
from marketbrief.results.texts import nse_texts, sec_texts


def now_floor() -> pd.Timestamp:
    """The clock rounded down to the second."""
    return pd.Timestamp(clock()).floor("s")


def window_start(settings: dict, now: pd.Timestamp, since: str | None) -> pd.Timestamp:
    """Start of the detection window: --since, else now - lookback_days."""
    if since:
        return pd.Timestamp(since, tz="UTC")
    return now - pd.Timedelta(days=int((settings.get("detection") or {}).get("lookback_days", 10)))


def fetch_texts(con, cfg: dict, settings: dict, scope: Scope, fetch: bool):
    """Fetch the primary texts of the detected releases not settled yet: (rows, summary)."""
    now, since, tickers = scope.now, scope.since, scope.tickers
    conf = settings.get("texts") or {}
    newest, _ = stored_digests(con, now)
    releases = [
        release
        for release in detect(con, cfg, now, since, conf)
        if (not tickers or release.ticker in tickers)
        and not (
            newest.get(release.id, {}).get("status") == STATUS_OK
            and newest.get(release.id, {}).get("numbers_status") == NUMBERS_OK
        )
    ]
    if cfg.get(CFG_FILINGS) == FILINGS_SOURCE_SEC:
        return sec_texts(con, cfg, releases, conf, now, fetch)
    wanted = {ann_id for release in releases for ann_id in release.announcement_ids}
    rows = [row for row in announcements(con, now, since - pd.Timedelta(days=3)) if row["id"] in wanted]
    return nse_texts(con, lambda: nse_client(cfg), rows, conf, now, fetch)


def prepare(cfg: dict, args) -> dict:
    """Store the texts of the due releases and write the results-analyst's input file."""
    settings, market, now = load_settings(), cfg["market"], now_floor()
    since = window_start(settings, now, args.since)
    con = connect(market)
    rows, fetched = fetch_texts(con, cfg, settings, Scope(now, since, args.ticker), not args.no_fetch)
    extra: list[dict] = []
    if rows and args.dry_run:
        out = paths.ROOT / DEFAULT_DRY_TEXTS
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        fetched["dry_run_texts"], extra = str(out), rows
    elif rows:
        fetched["stored"] = append_jsonl(day_file(market, KIND_PRIMARY_TEXTS, utc_today()), rows)
    con = connect(market)  # a kind first written above is only visible to a new connection
    now = now_floor()
    due, info = due_releases(con, cfg, Scope(now, since, args.ticker, extra), settings)
    newest, _ = stored_digests(con, now)
    max_chars = int((settings.get("texts") or {}).get("input_max_chars", 12000))
    records = [
        input_record(found, cfg, newest.get(found.release.id), max_chars) for found in due if found.status == STATUS_OK
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(json.dumps(record, ensure_ascii=False, default=str) + "\n" for record in records), encoding="utf-8"
    )
    return {
        "step": "results_digest.prepare",
        "market": market,
        "as_of": now.isoformat(),
        "since": since.isoformat(),
        "inputs": str(args.out),
        **info,
        "for_agent": len(records),
        "releases": [summary_of(f) for f in due],
        "texts": fetched,
    }


def check_file(cfg: dict, path: Path, since: str | None = None):
    """(valid records with their Prepared, errors by line, record count, due releases without text)."""
    settings, now = load_settings(), now_floor()
    con = connect(cfg["market"])
    due, _ = due_releases(con, cfg, Scope(now, window_start(settings, now, since)), settings)
    by_id = {found.release.id: found for found in due}
    views = {release_id: found.view() for release_id, found in by_id.items() if found.status == STATUS_OK}
    good, bad, seen = [], [], set()
    recs = read_records(path)
    for line_number, rec in enumerate(recs, 1):
        errors, stored = (
            check_record(rec, views, seen, settings.get("digest") or {}) if not isinstance(rec, str) else ([rec], None)
        )
        if errors:
            release_id = rec.get("release_id") if isinstance(rec, dict) else None
            bad.append({"line": line_number, "release_id": release_id, "errors": errors})
        else:
            seen.add(stored["release_id"])
            good.append((by_id[stored["release_id"]], stored))
    auto = [found for found in due if found.status in AUTO_STATUSES]
    missing = sorted(set(views) - seen)
    return good, bad, len(recs), auto, missing


def main() -> int:
    """prepare | validate F | add F [--valid-only]; prints a JSON summary."""
    parser = market_arg(__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    prep = sub.add_parser("prepare", help="detect releases, store their texts, write the agent's input")
    prep.add_argument("--out", type=Path, default=paths.ROOT / DEFAULT_INPUTS)
    prep.add_argument("--no-fetch", action="store_true", help="request no text from SEC or NSE")
    prep.add_argument("--since", help="window start (YYYY-MM-DD, UTC) instead of now - lookback_days")
    prep.add_argument("--ticker", nargs="*", help="only these tickers")
    prep.add_argument("--dry-run", action="store_true", help=f"write fetched texts to {DEFAULT_DRY_TEXTS}, not data/")
    for name in ("validate", "add"):
        file_parser = sub.add_parser(name)
        file_parser.add_argument("file", type=Path)
        file_parser.add_argument("--since", help="window start as given to prepare (YYYY-MM-DD, UTC)")
        if name == "add":
            file_parser.add_argument("--valid-only", action="store_true", help="append the valid records only")
    args = parser.parse_args()
    cfg = require_market(args)
    if args.cmd == "prepare":
        print(json.dumps(prepare(cfg, args), indent=2, default=str))
        return 0
    good, bad, record_count, auto, missing = check_file(cfg, args.file, args.since)
    summary = {
        "step": f"results_digest.{args.cmd}",
        "market": cfg["market"],
        "file": str(args.file),
        "records": record_count,
        "valid": len(good),
        "errors": bad,
        "without_text": len(auto),
        "missing": missing,
        "appended": 0,
    }
    if args.cmd == "validate" or (bad and not args.valid_only):
        print(json.dumps(summary, indent=2, default=str))
        return 1 if bad else 0
    now = utc_now()
    rows = [
        digest_row(
            found, STATUS_OK if rec["bullets"] else STATUS_NO_BULLETS, rec["bullets"], rec["prompt_version"], now
        )
        for found, rec in good
    ]
    rows += [digest_row(found, found.status, [], None, now) for found in auto]
    path = day_file(cfg["market"], KIND_RESULTS_DIGESTS, utc_today())
    summary.update({"appended": append_jsonl(path, rows), "to": str(path), "dropped": [e["line"] for e in bad]})
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
