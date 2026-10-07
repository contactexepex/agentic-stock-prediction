"""scripts/company.py: the watchlist's command line (F8; research only: a company record, never an order).

  company.py --market us add --symbol MSFT [--amount 2000] [--sector Tech] [--name "..."] --key K [--skip-backfill]
  company.py --market us deactivate --ticker DAL [--reason "pause airlines"] --key K
  company.py --market us reactivate --ticker DAL --key K
  company.py --market india set-amount --ticker MARUTI (--amount 10000 | --default) --key K
  company.py --market us delete --ticker MSFT --confirm MSFT --key K       (typed confirmation; never from Slack)
  company.py --market us list
  company.py --market us seed                         (one time: the config's tickers as add events)
  company.py --market us import-inbox [--inbox FILE]  (MotherDuck market_brief_inbox, or a local DuckDB file)

Writes take --channel (cli | claude_code; default cli) and record requested_by = <channel>:session; the inbox
import takes channel and actor from each inbox row. stdout is one JSON object; exit 2 when a write is refused."""
from __future__ import annotations

import argparse
import json

from marketbrief.core.cli import market_arg, require_market
from marketbrief.lifecycle import commands
from marketbrief.lifecycle.constants import (
    EVENT_DEACTIVATE,
    EVENT_DELETE,
    EVENT_REACTIVATE,
    EVENT_SET_AMOUNT,
)
from marketbrief.lifecycle.sources import sources_for

EXIT_REFUSED = 2
WRITE_CHANNELS = ("cli", "claude_code")


def parser() -> argparse.ArgumentParser:
    """The argument parser with every subcommand."""
    root = market_arg(__doc__.splitlines()[0])
    sub = root.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="onboard a company and add it")
    add.add_argument("--symbol", required=True)
    add.add_argument("--amount", type=float)
    add.add_argument("--sector")
    add.add_argument("--name")
    add.add_argument("--skip-backfill", action="store_true", help="identifiers and sector only (tests, dry checks)")
    writers = {"add": add}
    for name in ("deactivate", "reactivate", "set-amount", "delete"):
        writers[name] = sub.add_parser(name)
        writers[name].add_argument("--ticker", required=True)
    writers["set-amount"].add_argument("--amount", type=float)
    writers["set-amount"].add_argument("--default", action="store_true", help="back to the market default")
    writers["delete"].add_argument("--confirm", required=True, help="type the ticker again")
    for writer in writers.values():
        writer.add_argument("--key", required=True, help="idempotency key (8-64 of A-Z a-z 0-9 _ -)")
        writer.add_argument("--reason")
        writer.add_argument("--channel", default="cli", choices=WRITE_CHANNELS)
    sub.add_parser("list")
    sub.add_parser("seed")
    inbox = sub.add_parser("import-inbox")
    inbox.add_argument("--inbox", help="a local DuckDB inbox file (default: MotherDuck with MOTHERDUCK_INBOX_TOKEN)")
    inbox.add_argument("--skip-backfill", action="store_true")
    return root


def request_of(args, market: str, event: str) -> dict:
    """The lifecycle request of a write subcommand."""
    request = {"market": market, "ticker": (args.ticker if event != "add" else args.symbol).strip().upper(),
               "event": event, "idempotency_key": args.key, "reason": args.reason, "channel": args.channel,
               "requested_by": f"{args.channel}:session"}
    if event == EVENT_SET_AMOUNT:
        if args.default == (args.amount is not None):
            request["amount"] = "missing"   # refused by the validator: exactly one of --amount and --default
        else:
            request["amount"] = None if args.default else args.amount
    if event == EVENT_DELETE:
        request["confirm"] = args.confirm.strip().upper()
    if event == "add":
        request.update(amount=args.amount, sector=args.sector, name=args.name)
    return request


EVENT_OF_COMMAND = {"deactivate": EVENT_DEACTIVATE, "reactivate": EVENT_REACTIVATE, "set-amount": EVENT_SET_AMOUNT,
                    "delete": EVENT_DELETE}


def run(args, cfg: dict) -> dict:
    """The result of one command."""
    market = cfg["market"]
    if args.command == "list":
        return commands.list_watchlist(market)
    if args.command == "seed":
        from marketbrief.lifecycle.seed import seed

        return seed(market, sources_for(cfg))
    if args.command == "import-inbox":
        from marketbrief.lifecycle.inbox import import_inbox

        return import_inbox(market, args.inbox, sources_for(cfg), skip_backfill=args.skip_backfill)
    if args.command == "add":
        return commands.add_company(request_of(args, market, "add"), sources_for(cfg), args.skip_backfill)
    return commands.submit(request_of(args, market, EVENT_OF_COMMAND[args.command]))


def main(argv: list[str] | None = None) -> int:
    """Parse, run and print the JSON."""
    args = parser().parse_args(argv)
    cfg = require_market(args)
    result = run(args, cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return EXIT_REFUSED if result.get("ok") is False else 0
