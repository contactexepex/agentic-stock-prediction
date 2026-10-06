#!/usr/bin/env python3
"""Per-company connection map (DESIGN.md phase 5) for one market.

Edges link a watchlist ticker to a person or company (board, group, subsidiary, supplier,
customer, competitor, promoter, major_holder). They are written by the graph-builder agent,
each citing a public source, and stored append-only in data/<market>/graph/YYYY/MM/<date>.jsonl.
The id is <ticker>|<relation>|<target slug>: a newer row with the same id replaces the edge,
and status "removed" retracts it (view graph_edges).

  graph.py status            JSON: edge counts, tickers without edges, refresh_due
  graph.py edges [--ticker]  Markdown table of current edges
  graph.py hits [--days N]   second-order news: articles about a linked entity, not the ticker
  graph.py add FILE          validate a JSONL file of edges and append new or changed ones
  graph.py attempt [--note]  record a refresh attempt in data/<market>/graph_runs/ (run after
                             every graph-builder run, even one that added nothing)
A refresh is due when no attempt has been recorded in the current UTC month, so a run that
finds nothing to add is not repeated until the next month."""
from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.utils.markdown import cursor_markdown_table
from marketbrief.utils.text import slugify

RELATIONS = ("board", "group", "subsidiary", "supplier", "customer", "competitor", "promoter", "major_holder")
TARGET_KINDS = ("person", "company")
STATUSES = ("active", "removed")
COMPARE = ("ticker", "relation", "target", "target_kind", "target_ticker", "aliases", "detail",
           "weight", "status", "as_of", "source_url")
MIN_NAME = 3          # shorter names/aliases are never matched against headlines


def edge_id(ticker: str, relation: str, target: str) -> str:
    return f"{ticker}|{relation}|{slugify(target)}"


def load_edges(con, ticker: str | None = None) -> list[dict]:
    sql = "SELECT * FROM graph_edges" + (" WHERE ticker = ?" if ticker else "") + " ORDER BY ticker, relation, target"
    cur = con.execute(sql, [ticker] if ticker else [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def validate(row: dict, tickers: set[str], today: date) -> tuple[dict | None, list[str]]:
    """Normalise one edge from the agent; return (edge, errors)."""
    errs = []
    r = {k: row.get(k) for k in COMPARE + ("prompt_version",)}
    if r["ticker"] not in tickers:
        errs.append(f"ticker {r['ticker']!r} not in the watchlist")
    if r["relation"] not in RELATIONS:
        errs.append(f"relation {r['relation']!r} not one of {RELATIONS}")
    if not isinstance(r["target"], str) or len(r["target"].strip()) < 2:
        errs.append("target name missing")
    if r["target_kind"] not in TARGET_KINDS:
        errs.append(f"target_kind {r['target_kind']!r} not one of {TARGET_KINDS}")
    if not str(r["source_url"] or "").startswith(("https://", "http://")):
        errs.append("source_url must be the http(s) page that states this edge")
    r["status"] = r["status"] or "active"
    if r["status"] not in STATUSES:
        errs.append(f"status {r['status']!r} not one of {STATUSES}")
    try:
        as_of = date.fromisoformat(str(r["as_of"]))
        if as_of > today:
            errs.append("as_of is in the future")
        r["as_of"] = str(as_of)
    except ValueError:
        errs.append("as_of must be YYYY-MM-DD (date of the source)")
    aliases = r["aliases"] or []
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        errs.append("aliases must be a list of strings")
    else:
        r["aliases"] = sorted({a.strip() for a in aliases if a.strip()})
    if r["weight"] is not None and not isinstance(r["weight"], (int, float)):
        errs.append("weight must be a number or null")
    if r["target_ticker"] is not None and not isinstance(r["target_ticker"], str):
        errs.append("target_ticker must be a string or null")
    if errs:
        return None, errs
    r["target"] = r["target"].strip()
    r["id"] = edge_id(r["ticker"], r["relation"], r["target"])
    r["prompt_version"] = r["prompt_version"] or "graph-v4"
    return r, []


def add(cfg: dict, con, path: Path, dry_run: bool = False) -> dict:
    """Validate the edges in path and append the new or changed ones. dry_run (`check`) only
    validates and counts what would be written: the graph-builder runs it, the caller runs `add`
    after the judge passes the file."""
    today, now = utc_today(), utc_now()
    current = {e["id"]: e for e in load_all_latest(con)}
    tickers = set(cfg["tickers"])
    new, rejected, unchanged = {}, [], 0
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            rejected.append({"line": n, "errors": [f"not JSON: {exc}"]})
            continue
        edge, errs = validate(row, tickers, today)
        if errs:
            rejected.append({"line": n, "target": row.get("target"), "errors": errs})
            continue
        old = current.get(edge["id"])
        if old and all(_same(old.get(k), edge.get(k)) for k in COMPARE):
            unchanged += 1
            continue
        if edge["status"] == "removed" and not old:
            rejected.append({"line": n, "target": edge["target"], "errors": ["removing an edge that does not exist"]})
            continue
        new[edge["id"]] = {"id": edge["id"], **{k: edge[k] for k in COMPARE}, "added_at": now,
                           "prompt_version": edge["prompt_version"]}
    if dry_run:
        return {"step": "graph_check", "market": cfg["market"], "would_write": len(new), "unchanged": unchanged,
                "rejected": rejected}
    written = append_jsonl(day_file(cfg["market"], "graph", today), new.values())
    return {"step": "graph_add", "market": cfg["market"], "written": written, "unchanged": unchanged,
            "rejected": rejected}


def load_all_latest(con) -> list[dict]:
    """Latest version of every edge id, including removed ones (to compare before appending)."""
    cur = con.execute("SELECT DISTINCT ON (id) * FROM graph ORDER BY id, added_at DESC")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _same(a, b) -> bool:
    norm = lambda v: sorted(v) if isinstance(v, (list, tuple)) else (str(v) if v is not None else None)  # noqa: E731
    return norm(a) == norm(b)


def status(cfg: dict, con) -> dict:
    edges = load_edges(con)
    last = con.execute("SELECT max(added_at) FROM graph").fetchone()[0]
    last_run = con.execute("SELECT max(run_at) FROM graph_runs").fetchone()[0]
    month = f"{utc_today():%Y-%m}"
    by_rel: dict[str, int] = {}
    for e in edges:
        by_rel[e["relation"]] = by_rel.get(e["relation"], 0) + 1
    covered = {e["ticker"] for e in edges}
    # Due until a refresh attempt is recorded for the current UTC month (edges or not).
    attempted = con.execute("SELECT count(*) FROM graph_runs WHERE month = ?", [month]).fetchone()[0] > 0
    return {"market": cfg["market"], "edges": len(edges), "by_relation": by_rel,
            "tickers_without_edges": [t for t in cfg["tickers"] if t not in covered],
            "last_added_at": last.isoformat() if last else None,
            "last_attempt_at": last_run.isoformat() if last_run else None, "refresh_due": not attempted}


def attempt(cfg: dict, con, note: str | None = None) -> dict:
    """Append one refresh-attempt record (current edge count) to data/<market>/graph_runs/."""
    st, now = status(cfg, con), utc_now()
    row = {"id": f"{cfg['market']}-graph-run-{now}", "run_at": now, "month": f"{utc_today():%Y-%m}",
           "edges": st["edges"], "tickers_without_edges": len(st["tickers_without_edges"]), "note": note}
    append_jsonl(day_file(cfg["market"], "graph_runs", utc_today()), [row])
    return {"step": "graph_attempt", **row}


def name_patterns(edges: list[dict]) -> list[tuple[dict, re.Pattern]]:
    out = []
    for e in edges:
        names = [n for n in {e["target"], *(e.get("aliases") or [])} if len(n) >= MIN_NAME]
        if names:
            out.append((e, re.compile(r"(?<!\w)(" + "|".join(map(re.escape, sorted(names, key=len, reverse=True)))
                                      + r")(?!\w)", re.I)))
    return out


def hits(cfg: dict, con, days: int = 1, today: date | None = None) -> list[dict]:
    """Second-order news: an article that names a linked entity (or is tagged with a linked
    watchlist ticker) but is not itself tagged with the ticker. One row per (ticker, article)."""
    edges = load_edges(con)
    if not edges:
        return []
    since = (today or utc_today()) - timedelta(days=days)
    news = con.execute("""
        SELECT n.id, n.title, n.source, n.tickers, CAST(coalesce(n.published_at, n.first_seen_at) AS DATE) AS day,
               e.sentiment, e.materiality
        FROM (SELECT DISTINCT ON (id) * FROM news ORDER BY id, first_seen_at) n
        LEFT JOIN enriched_latest e USING (id)
        WHERE CAST(coalesce(n.published_at, n.first_seen_at) AS DATE) >= ?""", [since]).fetchall()
    pats = name_patterns(edges)
    found: dict[tuple[str, str], dict] = {}
    for nid, title, source, tagged, day, sentiment, materiality in news:
        tagged = set(tagged or [])
        for e, pat in pats:
            m = pat.search(title or "")
            via_ticker = e.get("target_ticker") and e["target_ticker"] in tagged
            if e["ticker"] in tagged or not (m or via_ticker):
                continue
            key = (e["ticker"], nid)
            link = f"{e['relation']}: {e['target']}"
            if key in found:
                if link not in found[key]["via"]:
                    found[key]["via"].append(link)
                continue
            found[key] = {"ticker": e["ticker"], "via": [link], "news_id": nid, "day": str(day),
                          "title": title, "source": source, "sentiment": sentiment, "materiality": materiality}
    return sorted(found.values(), key=lambda h: (h["ticker"], h["day"], h["news_id"]))


def context_section(cfg: dict, con, days: int = 1, limit: int = 40) -> tuple[str, str]:
    """('Connections ...', markdown) for context.py."""
    st = status(cfg, con)
    title = f"Connections: second-order news, last {days} day(s) (news about a linked company or person)"
    if not st["edges"]:
        return title, "_no connection map yet (graph-builder runs monthly)_\n"
    rows = hits(cfg, con, days)
    head = (f"Map: {st['edges']} edges, last changed {str(st['last_added_at'])[:10]}"
            f"{', refresh due' if st['refresh_due'] else ''}.\n\n")
    if not rows:
        return title, head + "_none_\n"
    clean = lambda s: str(s).replace("|", "/")  # noqa: E731
    body = "| ticker | via | news_id | day | title | sentiment |\n|---|---|---|---|---|---|\n"
    body += "".join(f"| {h['ticker']} | {clean('; '.join(h['via']))} | {h['news_id']} | {h['day']} | "
                    f"{clean(h['title'])} | {'' if h['sentiment'] is None else round(h['sentiment'], 2)} |\n"
                    for h in rows[:limit])
    if len(rows) > limit:
        body += f"\n_{len(rows) - limit} more: `python scripts/graph.py hits`_\n"
    return title, head + body


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("command", choices=["status", "edges", "hits", "check", "add", "attempt"])
    ap.add_argument("--note", help="short note for `attempt`, e.g. tickers that could not be sourced")
    ap.add_argument("file", nargs="?", type=Path, help="JSONL edges for `check` / `add`")
    ap.add_argument("--ticker")
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()
    cfg = require_market(args)
    con = connect(cfg["market"])
    if args.command == "status":
        print(json.dumps(status(cfg, con), indent=2))
    elif args.command == "edges":
        cur = con.execute("SELECT ticker, relation, target, target_kind, target_ticker, aliases, detail, as_of, "
                          "source_url FROM graph_edges" + (" WHERE ticker = ?" if args.ticker else "") +
                          " ORDER BY ticker, relation, target", [args.ticker] if args.ticker else [])
        print(cursor_markdown_table(cur))
    elif args.command == "attempt":
        print(json.dumps(attempt(cfg, con, args.note), indent=2))
    elif args.command == "hits":
        print(json.dumps({"market": cfg["market"], "days": args.days, "hits": hits(cfg, con, args.days)},
                         indent=2, default=str))
    else:
        if not args.file or not args.file.exists():
            raise SystemExit(f"usage: graph.py {args.command} work/graph.jsonl")
        out = add(cfg, con, args.file, dry_run=args.command == "check")
        print(json.dumps(out, indent=2))
        return 1 if out["rejected"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
