"""Intraday checks and the deviation explainer's gate (WS5; config/intraday.yaml, docs/ws/ws5.md).

  [run] [--out DIR]          one check now (MB_NOW-aware, truncated to the minute): Yahoo 5-minute bars of the
                             watchlist, benchmark and sector indices, compared with the session's published 1d/5d
                             ranges and open calls/model scores as of the check; flags and attribution candidates
                             -> data/<market>/intraday_checks/ (one row per ticker) and intraday_runs/ (one row per
                             check). Market closed: the run row only. A check time already stored writes nothing.
                             --out DIR writes the same tree under DIR instead of data/ (live tests).
  prepare [--check ID] [--out F]   the flagged rows of a check (default the newest) without a note
                             -> F (default work/intraday_flags.jsonl), for the deviation-explainer agent
  validate F                 checks the explainer's records (JSON summary; exit 1 on any error)
  add F                      validate, then append to data/<market>/intraday_explanations/ (all or nothing)

The explainer writes one JSON object per flagged row: {"check_row_id", "text", "cited_ids", "attribution",
"prompt_version"}. Research only: a note never predicts and never recommends a trade."""

from __future__ import annotations

import json
from pathlib import Path

from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock
from marketbrief.core.database import connect
from marketbrief.intraday import explain
from marketbrief.intraday.check import print_summary, run_check
from marketbrief.intraday.quotes import YahooIntraday
from marketbrief.intraday.settings import load_intraday_config


def parser():
    """The command line."""
    parser = market_arg(__doc__)
    sub = parser.add_subparsers(dest="cmd")
    run_parser = sub.add_parser("run", help="one check now")
    run_parser.add_argument("--out", type=Path, default=None, help="write under DIR instead of data/<market>/")
    prepare_parser = sub.add_parser("prepare", help="flagged rows without a note, for the explainer")
    prepare_parser.add_argument("--check", default=None, help="check id (default: the newest check)")
    prepare_parser.add_argument("--out", type=Path, default=paths.ROOT / "work" / "intraday_flags.jsonl")
    for name in ("validate", "add"):
        sub.add_parser(name).add_argument("file", type=Path)
    return parser


def main() -> int:
    """Entry point of scripts/intraday_check.py."""
    args = parser().parse_args()
    cfg = require_market(args)
    market, settings = cfg["market"], load_intraday_config()
    con = connect(market)
    if args.cmd in (None, "run"):
        out = getattr(args, "out", None)
        summary = run_check(cfg, settings, con, YahooIntraday(), clock(), out)
        print_summary(summary)
        return 0
    if args.cmd == "prepare":
        print_summary({"step": "intraday.prepare", "market": market, **explain.prepare(con, args.out, args.check)})
        return 0
    good, bad, count, rows = explain.check_file(con, args.file, settings)
    summary = {"step": f"intraday.{args.cmd}", "market": market, "file": str(args.file), "records": count,
               "valid": len(good), "errors": bad, "appended": 0}
    if args.cmd == "validate" or bad:
        print(json.dumps(summary, indent=2, default=str))
        return 1 if bad else 0
    appended, to = explain.add(market, good, rows)
    print(json.dumps({**summary, "appended": appended, "to": to}, indent=2))
    return 0
