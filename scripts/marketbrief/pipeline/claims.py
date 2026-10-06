"""Claims of news events (news verification phase B, docs/DESIGN.md section 3b; settings under `claims:`
in config/news_sources.yaml). Like lessons.py: facts and gate are deterministic, only the claim
records are written by an agent (.claude/agents/claim-checker.md).

  prepare [--out F] [--no-fetch]   select this run's high-materiality watchlist clusters (title weight
                                   of `material_terms` >= min_priority; at most max_clusters_per_run;
                                   a cluster row already checked is skipped), store the text of their
                                   SEC 8-K/6-K primary sources (main document and EX-99 exhibits) in
                                   primary_texts, and write the claim-checker's input to F
                                   (default work/claim_inputs.jsonl)
  validate F                       check the agent's records (JSON summary; exit 1 on any error)
  add F [--valid-only]             validate, then append to data/<market>/news_claims/ (all or nothing;
                                   --valid-only appends the valid ones and lists the dropped)

The gate (marketbrief/analytics/claim_rules.py): the cluster is current and the quoted source is one of
its items or stored primary sources; the quote (<= 40 words) is verbatim in that source's stored text
(article extract or title; filing text; announcement subject); value_num with its unit is a number
stated in the quote and every number in subject and predicate appears in it; enums; no claim id
stored twice. Article and filing text is untrusted data, read only as data."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

import news_verify
from marketbrief.analytics.claim_rules import check_claim
from marketbrief.constants.environment import ENV_SEC_USER_AGENT
from marketbrief.constants.verification import KIND_NEWS_CLAIMS, KIND_PRIMARY_TEXTS
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.pipeline.claim_inputs import input_records, select_clusters
from marketbrief.pipeline.claim_sources import current_clusters, sources_by_cluster
from marketbrief.sources.primary_text import filing_text_rows
from marketbrief.sources.sec_client import Edgar

FILINGS_SQL = """
SELECT DISTINCT ON (id) id, ticker, cik, form, url, accepted_at FROM filings
WHERE list_contains(?, id) AND list_contains(?, form) AND accepted_at <= ?::TIMESTAMPTZ ORDER BY id, first_seen_at"""


def settings() -> dict:
    """The `claims:` section of config/news_sources.yaml."""
    return news_verify.load_sources().cfg.get("claims") or {}


def now_floor() -> pd.Timestamp:
    return pd.Timestamp(clock()).floor("s")


def fetch_primary_texts(con, market: str, clusters: list[dict], conf: dict, now: pd.Timestamp) -> dict:
    """Store the text of the selected clusters' SEC 8-K/6-K primary sources not stored yet."""
    wanted = sorted({p for c in clusters for p in c.get("primary_ids") or []})
    stored = {r[0] for r in con.execute("SELECT DISTINCT primary_id FROM primary_texts").fetchall()}
    forms = list(conf.get("primary_text_forms") or ["8-K", "6-K"])
    todo = [r for r in con.execute(FILINGS_SQL, [wanted, forms, now.isoformat()]).df().to_dict("records")
            if r["id"] not in stored]
    summary = {"filings": len(todo), "documents": 0, "failed": [], "skipped": None, "requests": 0}
    user_agent = os.environ.get(ENV_SEC_USER_AGENT)
    if todo and not user_agent:
        summary["skipped"] = f"{ENV_SEC_USER_AGENT} not set: no filing text fetched"
        return summary
    edgar = Edgar(user_agent) if todo else None
    limits = (int(conf.get("primary_max_docs", 3)), int(conf.get("primary_max_chars", 40000)))
    for filing in todo:
        filing["accepted_at"] = pd.Timestamp(filing["accepted_at"]).isoformat()
        try:
            rows = filing_text_rows(edgar, filing, limits, utc_now())
        except Exception as exc:  # noqa: BLE001 - one filing failing is listed, the run goes on
            summary["failed"].append({"id": filing["id"], "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            continue
        summary["documents"] += append_jsonl(day_file(market, KIND_PRIMARY_TEXTS, utc_today()), rows)
    summary["requests"] = edgar.requests if edgar else 0
    return summary


def prepare(cfg: dict, out: Path, fetch: bool) -> dict:
    """Select clusters, store their primary texts and write the claim-checker's input file."""
    market, conf, src = cfg["market"], settings(), news_verify.load_sources()
    now = now_floor()
    window = float(src.clusters.get("window_hours", 72))
    con = connect(market)
    clusters = current_clusters(con, now, window)
    selected, info = select_clusters(con, clusters, src, conf, now)
    fetched = {"skipped": "--no-fetch"} if not fetch else fetch_primary_texts(con, market, selected, conf, now)
    con = connect(market)            # a kind first written above is only visible to a new connection
    now = now_floor()                # the texts just stored (fetched_at) are available from now on
    sources = sources_by_cluster(con, selected, now)
    records = input_records(con, cfg, selected, sources, conf, now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records), encoding="utf-8")
    return {"step": "claims.prepare", "market": market, "as_of": now.isoformat(), "inputs": str(out),
            **info, "selected": len(records), "primary_texts": fetched}


def read_records(path: Path) -> list:
    """The agent's file: one JSON object per line (a bad line becomes an error entry)."""
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                out.append(f"line {n}: not JSON ({exc.msg})")
    return out


def check_file(cfg: dict, path: Path) -> tuple[list[dict], list[dict], int]:
    """(valid records to store, errors by line, number of records)."""
    now = now_floor()
    con = connect(cfg["market"])
    window = float(news_verify.load_sources().clusters.get("window_hours", 72))
    clusters = current_clusters(con, now, window)
    sources = sources_by_cluster(con, clusters, now)
    seen = {r[0] for r in con.execute("SELECT id FROM news_claims").fetchall()}
    good, bad = [], []
    recs = read_records(path)
    for n, rec in enumerate(recs, 1):
        errors, stored = check_claim(rec, sources, seen) if not isinstance(rec, str) else ([rec], None)
        if errors:
            bad.append({"line": n, "cluster_id": rec.get("cluster_id") if isinstance(rec, dict) else None,
                        "errors": errors})
        else:
            good.append(stored)
            seen.add(stored["id"])
    return good, bad, len(recs)


def main() -> int:
    """prepare | validate F | add F [--valid-only]; prints a JSON summary."""
    ap = market_arg(__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="select clusters, store primary texts, write the agent's input")
    p.add_argument("--out", type=Path, default=paths.ROOT / "work" / "claim_inputs.jsonl")
    p.add_argument("--no-fetch", action="store_true", help="do not request filing text from SEC")
    for name in ("validate", "add"):
        q = sub.add_parser(name)
        q.add_argument("file", type=Path)
        if name == "add":
            q.add_argument("--valid-only", action="store_true", help="append the valid records, drop the others")
    args = ap.parse_args()
    cfg = require_market(args)
    if args.cmd == "prepare":
        print(json.dumps(prepare(cfg, args.out, not args.no_fetch), indent=2, default=str))
        return 0
    good, bad, n = check_file(cfg, args.file)
    summary = {"step": f"claims.{args.cmd}", "market": cfg["market"], "file": str(args.file), "records": n,
               "valid": len(good), "errors": bad, "appended": 0}
    if args.cmd == "validate" or (bad and not args.valid_only):
        print(json.dumps(summary, indent=2, default=str))
        return 1 if bad else 0
    rows = [{**g, "extracted_at": utc_now()} for g in good]
    path = day_file(cfg["market"], KIND_NEWS_CLAIMS, utc_today())
    summary.update({"appended": append_jsonl(path, rows), "to": str(path), "dropped": [b["line"] for b in bad]})
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
