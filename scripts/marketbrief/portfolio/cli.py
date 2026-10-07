"""scripts/portfolio.py: the paper portfolio's command line (research only; a paper trade is a record).

  portfolio.py --market india add-trade --ticker HDFCBANK --side buy --quantity 10 --date 2026-10-07 \
      --basis open --source claude_code [--price P (with --basis manual)] [--note T] [--supersedes ID] [--key K]
  portfolio.py --market india cancel-trade --id ID --source claude_code [--note T] [--key K]
  portfolio.py --market india positions | pnl | list | signals | paper-follow
  portfolio.py --market india api-signals | api-portfolio   (the shapes of api/openapi.yaml SignalTiers, PaperPortfolio)
  portfolio.py --market us request-company --ticker MSFT | --name "..." --reason "..." --source claude_code
  portfolio.py --market us import-inbox [--inbox FILE]   (the web tier's add_paper_trade requests, issue #112)

stdout is one JSON object (machine-readable; {"ok": false, "errors": [...]} and exit code 2 on a rejected
write); a short readable table goes to stderr. Every read is as of the run's clock (MB_NOW-aware)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from marketbrief.core.cli import market_arg, require_market
from marketbrief.portfolio import api_shapes, inbox_import, paper_follow, service, signals
from marketbrief.portfolio.tables import render

EXIT_REJECTED = 2


def parser() -> argparse.ArgumentParser:
    """The argument parser with every subcommand."""
    root = market_arg(__doc__.splitlines()[0])
    sub = root.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-trade", help="record a validated paper trade")
    add.add_argument("--ticker", required=True)
    add.add_argument("--side", required=True)
    add.add_argument("--quantity", type=float, required=True)
    add.add_argument("--date", type=date.fromisoformat, required=True, help="trade date (a session)")
    add.add_argument("--basis", required=True, help="open | close (the stored bar's) | manual (with --price)")
    add.add_argument("--price", type=float)
    add.add_argument("--supersedes", help="the trade id this row corrects")
    cancel = sub.add_parser("cancel-trade", help="cancel a stored trade (a new row; nothing is edited)")
    cancel.add_argument("--id", required=True)
    request = sub.add_parser("request-company", help="request a company for the watchlist")
    request.add_argument("--ticker")
    request.add_argument("--name")
    request.add_argument("--reason", required=True)
    for writer in (add, cancel, request):
        writer.add_argument("--source", required=True, help="claude_code | slack | form")
        writer.add_argument("--key", help="idempotency key (default: derived from the fields)")
    for writer in (add, cancel):
        writer.add_argument("--note")
    for name in ("positions", "pnl", "list", "signals", "paper-follow", "api-signals", "api-portfolio"):
        sub.add_parser(name)
    inbox = sub.add_parser("import-inbox", help="import the add_paper_trade requests of the web tier (issue #112)")
    inbox.add_argument("--inbox", help="a local DuckDB file instead of MotherDuck (MOTHERDUCK_INBOX_TOKEN)")
    return root


def add(args, ctx: service.Context) -> dict:
    """add-trade."""
    return service.add_trade(ctx, service.TradeInput(
        args.ticker, args.side, args.quantity, args.date, args.basis, args.source, price=args.price,
        note=args.note, supersedes=args.supersedes, idempotency_key=args.key))


def payload(ctx: service.Context) -> dict:
    """The tier payload of the context's market."""
    return signals.cockpit_payload(ctx.con, ctx.clock, ctx.market, ctx.settings)


COMMANDS = {
    "add-trade": add,
    "cancel-trade": lambda a, c: service.cancel_trade(c, a.id, a.source, note=a.note, idempotency_key=a.key),
    "request-company": lambda a, c: service.request_company(c, a.source, a.reason, ticker=a.ticker, name=a.name,
                                                            idempotency_key=a.key),
    "positions": lambda _a, c: service.positions_report(c),
    "pnl": lambda _a, c: service.pnl_report(c),
    "list": lambda _a, c: service.list_report(c),
    "signals": lambda _a, c: payload(c),
    "paper-follow": lambda _a, c: paper_follow.simulate(c.con, c.cfg, c.clock, c.market, c.settings, c.costs),
    "api-signals": lambda _a, c: api_shapes.signal_tiers(payload(c), c.cfg),
    "api-portfolio": lambda _a, c: api_shapes.paper_portfolio(c),
    "import-inbox": lambda a, c: inbox_import.import_inbox(c, a.inbox, service.add_trade),
}


def run(args, ctx: service.Context) -> dict:
    """The result of one command."""
    return COMMANDS[args.command](args, ctx)


def main(argv: list[str] | None = None) -> int:
    """Parse, run, print the JSON (stdout) and the table (stderr)."""
    args = parser().parse_args(argv)
    cfg = require_market(args)
    result = run(args, service.context(cfg["market"]))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(render(args.command, result), file=sys.stderr)
    return EXIT_REJECTED if result.get("ok") is False else 0
