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
from pathlib import Path

from marketbrief.constants.connection_map import (
    MSG_USAGE_GRAPH_PY_WORK_GRAPH_JSONL,
)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.database import connect
from marketbrief.graph.connection_map import add, attempt, status
from marketbrief.graph.news_hits import hits
from marketbrief.utils.markdown import cursor_markdown_table


def main() -> int:
    """Run `status`, `edges`, `hits`, `add`, `check` or `attempt` of the connection map."""
    parser = market_arg(__doc__)
    parser.add_argument("command", choices=["status", "edges", "hits", "check", "add", "attempt"])
    parser.add_argument("--note", help="short note for `attempt`, e.g. tickers that could not be sourced")
    parser.add_argument("file", nargs="?", type=Path, help="JSONL edges for `check` / `add`")
    parser.add_argument("--ticker")
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()
    cfg = require_market(args)
    con = connect(cfg["market"])
    if args.command == "status":
        print(json.dumps(status(cfg, con), indent=2))
    elif args.command == "edges":
        cur = con.execute(
            "SELECT ticker, relation, target, target_kind, target_ticker, aliases, detail, as_of, "
            "source_url FROM graph_edges"
            + (" WHERE ticker = ?" if args.ticker else "")
            + " ORDER BY ticker, relation, target",
            [args.ticker] if args.ticker else [],
        )
        print(cursor_markdown_table(cur))
    elif args.command == "attempt":
        print(json.dumps(attempt(cfg, con, args.note), indent=2))
    elif args.command == "hits":
        print(
            json.dumps(
                {"market": cfg["market"], "days": args.days, "hits": hits(cfg, con, args.days)}, indent=2, default=str
            )
        )
    else:
        if not args.file or not args.file.exists():
            raise SystemExit(MSG_USAGE_GRAPH_PY_WORK_GRAPH_JSONL.format(command=args.command))
        out = add(cfg, con, args.file, dry_run=args.command == "check")
        print(json.dumps(out, indent=2))
        return 1 if out["rejected"] else 0
    return 0
